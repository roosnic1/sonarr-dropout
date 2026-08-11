# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this service does

A FastAPI app with two halves, wired together in `main.py`:

- A **Torznab indexer** (consumed by Sonarr, optionally via Prowlarr): given a `tvdbid`/season/episode, it resolves the corresponding dropout.tv episode URL via TheTVDB v4 API and returns a release for it. It does not scrape or search dropout.tv directly — the video URL comes straight out of TheTVDB's episode metadata (`remoteIds`).
- A **fake SABnzbd download client** (registered as Sonarr's download client): when Sonarr grabs a release, this service re-resolves the dropout.tv URL and downloads it with `yt-dlp` (authenticated via a `.netrc` file), reporting progress through SABnzbd's `queue`/`history` API so Sonarr imports the finished file from a shared volume like any other completed download.

This two-sided design exists because dropout.tv requires authentication and Sonarr has no "direct HTTP download" client type — only usenet/torrent clients — so this service has to impersonate one of those (SABnzbd) rather than handing Sonarr a raw link.

## Commands

```bash
pip install ".[dev]"          # install runtime + dev deps (pytest, ruff, pre-commit)
pre-commit install            # one-time: run ruff automatically on `git commit`
ruff check .                  # lint (CI runs this)
pytest -q                     # run full test suite
pytest tests/test_api.py -q   # run a single test file
pytest tests/test_api.py::TestSearch -q          # run a single class
pytest tests/test_api.py::TestSearch::test_x -q  # run a single test

python main.py                # run the service locally (needs TVDB_API_KEY, e.g. via .env)
docker build -t sonarr-dropout .
docker-compose up -d
```

CI (`.github/workflows/ci.yml`) requires `TVDB_API_KEY` to be set (a dummy value is fine) since `config.Settings` fails to construct without it — same requirement applies when running tests locally without a `.env` file.

## Architecture

- **`config.py`** — `pydantic-settings` `Settings`, loaded once at import time as the module-level `settings` singleton, sourced from env vars / `.env`. `tvdb_api_key` is required (no default); everything else has a default.
- **`tvdb_client.py`** — `TVDBClient`, an async wrapper around the official (synchronous, `urllib`-based) `tvdb_v4_official` package. Because that underlying client keeps pagination "links" as shared per-instance state, every call is run via `asyncio.to_thread` and serialized behind an `asyncio.Lock` — don't call it concurrently without going through this wrapper. `resolve_episode(series_id, season, episode)` is the main entry point: it finds the TVDB episode id for a season/episode number (paginating `get_series_episodes`), then reads that episode's `remoteIds` (via `get_episode_extended`) for the `watch.dropout.tv` URL. Results are cached in-memory per `settings.cache_ttl` since Sonarr's RSS sync re-queries the same episodes repeatedly.
- **`dropout_downloader.py`** — thin wrapper around `yt-dlp`'s Python API. `download(url, dest_dir, netrc_path)` runs the blocking yt-dlp call via `asyncio.to_thread` and returns `dest_dir` (not a filename — SABnzbd's `history` API reports a folder, and Sonarr's importer scans it). yt-dlp's dropout.tv extractor looks up credentials under netrc machine name `dropout` specifically. English subtitles (falling back to auto-generated captions if no manual ones exist) are downloaded and embedded via the `FFmpegEmbedSubtitle` postprocessor, and `merge_output_format` is forced to `mkv` since embedded subtitles need a container that supports them — ffmpeg (already required for muxing dropout.tv's separate video/audio streams, see Dockerfile) does the actual muxing/remuxing.
- **`sabnzbd_api.py`** — `APIRouter` (mounted at `/sabnzbd` in `main.py`) implementing just enough of the SABnzbd HTTP API for Sonarr's download client integration: `version`, `get_cats`, `get_config`, `fullstatus`, `addurl`, `addfile`, `queue`, `history` (plus `queue`/`history` `delete`), plus a non-API `GET /nzb/{tvdbid}/{season}/{episode}` route. `get_config`'s `misc.complete_dir` must be an absolute path (Sonarr's `GetCategories` falls back to a `fullstatus` call otherwise) and its `categories[].dir` must not end in `*` (Sonarr reads that as "job folders disabled" and raises a validation warning). `JobManager` holds an in-memory `nzo_id -> Job` dict and a background `asyncio.Task` per job that calls `tvdb_client.resolve_episode` then `dropout_downloader.download`. Sonarr's usenet download-client base class GETs the Torznab release link itself (enclosure `type="application/x-nzb"` triggers this) before ever calling the SABnzbd API, so `GET /nzb/...` must serve *something* fetchable — `build_nzb()` returns a placeholder nzb document with tvdbid/season/episode stashed in `<meta>` tags, and Sonarr then uploads those exact bytes back to us via `mode=addfile`, where `parse_nzb_content` reads the ids back out. `addurl`/`parse_nzb_link` (parsing tvdbid/season/episode out of the link string itself) are kept as a second code path for SABnzbd-API callers that pass a URL directly rather than fetching+uploading it, but Sonarr's own grab flow goes through `addfile`. `job_manager` is a module-level singleton set by `init_job_manager()` in `main.py`'s `lifespan` — same pattern as `main.py`'s own globals, see below.
- **`torznab_builder.py`** — `TorznabBuilder`, stateless static methods that turn a list of `ReleaseItem` dataclasses into Torznab-flavored XML (`lxml`) for `caps`, search results, and error responses. Categories are TV-only (`5000`/`5040`) — dropout.tv has no movies and is consistently HD.
- **`main.py`** — FastAPI app and all HTTP routes. Key things to know before touching it:
  - `tvdb_client`, `startup_time`, `last_successful_search`, and `api_status` are **module-level globals**, initialized in the `lifespan` context manager and mutated by request handlers. Tests reset them via the `reset_globals` fixture in `tests/conftest.py` — any new global state needs the same treatment.
  - `lifespan` also calls `sabnzbd_api.init_job_manager(...)` to set up that module's own singleton — tests need to reset/mock that too (see `tests/conftest.py`).
  - `/health` is intentionally passive: it never calls the TVDB API, it only reports the in-memory `api_status` dict (last updated by `lifespan` on startup and by `search_dropout` after each real search) plus live counts pulled from `sabnzbd_api.job_manager`. This was a deliberate fix to stop health checks from burning API quota — don't reintroduce an API call here.
  - `search_dropout()` treats a search with neither `tvdbid` nor `q` as a Sonarr/Prowlarr connection test and returns a synthetic single-result response without calling TVDB — also a quota-preservation measure. A search with `q` but no `tvdbid` returns no results (there's no metadata to resolve a URL from without one). A `season` with no `ep` resolves every episode in that season (one release each) since dropout.tv has no season-bundle equivalent.
  - Each `ReleaseItem.link` is built as `{public_url}/sabnzbd/nzb/{tvdbid}/{season}/{episode}` — Sonarr's usenet download client GETs this URL directly to fetch nzb bytes (`sabnzbd_api.get_nzb`/`build_nzb`) before uploading them back to us via `mode=addfile` (`sabnzbd_api.parse_nzb_content`). Keep the path segments (`main.py` building the link, `sabnzbd_api.get_nzb`'s route params, `build_nzb`/`parse_nzb_content`'s `<meta>` tags) in sync if the format changes.
  - `search_dropout()`'s `series_title` falls back to `f"tvdb-{tvdbid}"` when Sonarr omits `q` — which it does for its normal tvdbid-only search requests. That garbage series name in the title is harmless for matching only because `ReleaseItem.tvdbid` is also sent as a `newznab:attr`; Sonarr's `ParsingService` matches a release straight to `SearchCriteria.Series` when that attr equals the series it searched for, without needing the title's series name to parse correctly. The title also always carries literal `1080p WEB-DL English` tokens — not a real encode description, just there so Sonarr's title parser (which independently drives the Quality/Language columns and the interactive-search "Scene Info" tooltip) doesn't report them as Unknown. Don't drop either without checking both effects.
  - `/{indexer_id}/api` is an alias of `/api` for Prowlarr's path-based indexer convention; keep both in sync if the query signature changes.

## Testing conventions

`tests/conftest.py` provides the shared fixtures: `test_client` builds an ASGI `AsyncClient` against `main.app` with a mocked `TVDBClient` injected (no real network calls, lifespan is bypassed) and a `sabnzbd_api.job_manager` wired to it, and `mock_search` layers canned `TVDBClient` return values on top. Reuse these rather than hand-rolling app instances — `reset_globals` (an implicit dependency of `test_client`) is what keeps `main`'s and `sabnzbd_api`'s module-level state from leaking between tests. Downloads are never exercised for real in tests — `dropout_downloader.download` is mocked wherever a test needs a job to reach "completed"/"failed".