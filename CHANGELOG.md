# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.6] - 2026-08-31

### Changed
- Bumped `uvicorn` from 0.52.1 to 0.52.4 (patch release)
- Bumped the `python` base image digest in `Dockerfile` (still `3.14-slim`)
- Bumped `docker/login-action` from v3 to v4 in the CI and Docker-publish workflows

## [0.1.5] - 2026-08-12

### Added
- Real-time download progress: yt-dlp's progress hooks (bytes downloaded, total bytes, speed, ETA) are now wired through to the SABnzbd `queue` API, so Sonarr's Activity tab shows real progress/speed/time-left instead of hardcoded placeholder values
- Best-effort file size estimation on search results -- dropout.tv's HLS manifests carry a per-variant bitrate but no byte count, and yt-dlp deliberately leaves `filesize`/`filesize_approx` unset for such formats (a fragmented format's bitrate is often peak rather than average), so releases now report the same `tbr * duration` fallback yt-dlp's own `-F` table computes at print time, summing whichever video/audio component formats can be sized, instead of leaving Sonarr's size column blank
- CI publishes testable Docker images (`pr-<number>`, `sha-<short-sha>`) to ghcr.io for pull requests, gated behind the existing test job so failing PRs never produce one, with a sticky PR comment showing the pull command and a nightly cleanup workflow removing `pr-*` tags once their PR closes

### Fixed
- Release titles built from Sonarr's normal tvdbid-only search (which omits `q`) showed the placeholder `tvdb-<id>` instead of the real series name -- `TVDBClient.get_series_name` now resolves and caches it from TheTVDB, falling back to the placeholder only if that lookup itself comes back empty
- Release titles described the video codec as missing instead of naming it -- corrected the literal title tokens to include `H264` alongside the existing `WEB-DL`/`English` tokens Sonarr's title parser depends on
- Download ETAs at or past 24 hours broke Sonarr's queue polling: `str(timedelta(...))` prefixes `"X day(s), "` once `eta_seconds` reaches a day, which Sonarr's `SabnzbdQueueTimeConverter` (plain `H:MM:SS` parsed with `Int32.Parse` per part) can't handle. Replaced with a custom formatter that always emits `H:MM:SS`, also fixed to accept the float `eta` values yt-dlp actually reports rather than assuming `int`

## [0.1.4] - 2026-08-12

### Changed
- Reorganized all application modules (`main.py`, `config.py`, `tvdb_client.py`, `dropout_downloader.py`, `sabnzbd_api.py`, `torznab_builder.py`, `__version__.py`) from the repo root into a `sonarr_dropout/` package, replacing setuptools' `py-modules` list with `packages`. The service now runs via `python -m sonarr_dropout.main` instead of `python main.py`

## [0.1.3] - 2026-08-11

### Fixed
- Interactive search results showed "Unknown episode or series" plus Unknown language/quality in Sonarr's Scene Info tooltip. Sonarr's tvdbid-based tvsearch (used for interactive search) sends `tvdbid`/`season`/`ep` without `q`, so the release title's series name fell back to the placeholder `tvdb-<id>`, which can never fuzzy-match a library series by title; Sonarr's parser also derives quality/language purely from the release title text, which carried neither. Releases now carry a `tvdbid` newznab:attr, which Sonarr's `ParsingService` matches directly against the searched series independent of the title text, plus literal `1080p WEB-DL English` tokens in the title so Sonarr's parser resolves quality/language instead of reporting them as unknown
- Grabbing a release in Sonarr failed with a 404 and "Downloading nzb file ... failed since it no longer exists". Releases are advertised with enclosure `type="application/x-nzb"`, which makes Sonarr's usenet download client `GET` the release link itself to fetch nzb bytes *before* ever calling the SABnzbd API -- but no route served that link, since the original design assumed (incorrectly) that Sonarr would only ever hand the link back to `addurl`. Added a `GET /sabnzbd/nzb/{tvdbid}/{season}/{episode}` route serving a placeholder nzb (tvdbid/season/episode encoded in `<meta>` tags) plus a `mode=addfile` handler that reads those ids back out of the uploaded bytes and queues the job the same way `addurl` does
- The tag-triggered release workflow could create a GitHub Release twice for the same tag (the second attempt failing with `already_exists`): a separate `release.yml`, triggered via `workflow_run` after the build finished, duplicated release creation that had already been folded into `docker-publish.yml`'s own tag-triggered `release` job. Since `workflow_run` always runs the *default branch's* copy of the triggered workflow regardless of the tag's own commit, the stale `release.yml` kept firing until it was actually merged to `main`. Removed `release.yml` entirely -- release creation now lives solely in `docker-publish.yml`, which also marks the GitHub Release as a pre-release when the tag's version contains a `-` (e.g. `v0.1.3-rc1`), so test builds tagged from feature branches ahead of a real release don't show up as full releases

## [0.1.2] - 2026-08-11

### Fixed
- Implemented the SABnzbd `get_config` API mode, which Sonarr's SABnzbd download client calls during its connection test (and again on every `GetStatus`) to read the complete-download directory and validate the configured category. It was previously unimplemented, so Sonarr's "Test" always failed with a "missing mode" 400 error. The response reports an absolute `misc.complete_dir` (Sonarr falls back to a `fullstatus` call if it isn't rooted) and a `tv` category whose `dir` doesn't end in `*` (a trailing `*` reads to Sonarr as "job folders disabled" and raises a validation warning)

## [0.1.1] - 2026-08-11

### Fixed
- Release XML attributes (`category`, `size`, `season`, `episode`) are now emitted in the `newznab` namespace instead of `torznab`. Sonarr/Prowlarr add this service as a Newznab indexer (it emulates SABnzbd and serves `application/x-nzb` enclosures), and their `NewznabRssParser.GetCategory()` only recognizes `newznab:attr` elements -- `torznab:attr` was invisible to it, so every release (including the synthetic connection-test result) parsed with no category and got silently dropped, breaking Prowlarr's app-sync to Sonarr with a "no results in the configured categories" error

## [0.1.0] - 2026-08-11

### Added
- Initial release of Sonarr-Dropout, replacing the former Orionoid-based indexer/downloader with a TheTVDB + dropout.tv + yt-dlp pipeline
- Torznab indexer that resolves a Sonarr `tvdbid`/season/episode to the matching dropout.tv episode URL via TheTVDB v4 API `remoteIds` metadata (no scraping or slug-guessing)
- Fake SABnzbd download client (`/sabnzbd`) implementing enough of the SABnzbd HTTP API (`version`, `get_cats`, `fullstatus`, `addurl`, `queue`, `history`) for Sonarr to use this service as its download client
- Authenticated downloads via yt-dlp using a `.netrc` file (machine `dropout`)
- English subtitle download and embedding (falling back to auto-generated captions when no manual subtitles exist), with output remuxed to MKV via ffmpeg
- Passive `/health` endpoint that reports in-memory state without making live API calls, preventing Docker healthchecks from burning TVDB quota
- Sonarr/Prowlarr connection-test searches (no `tvdbid`/`q`) short-circuit to a synthetic result instead of hitting TheTVDB
- Season-only search (no `ep`) resolves and returns every episode in that season, since dropout.tv has no season-bundle equivalent
- In-memory per-episode caching of TheTVDB lookups (`cache_ttl`) to absorb Sonarr's repeated RSS sync queries
- `/{indexer_id}/api` path alias for Prowlarr's path-based indexer convention
- Optional API key authentication for indexer requests
- Docker containerization with ffmpeg baked in for stream muxing, multi-architecture builds (amd64, arm64, arm/v7)
- `docker-compose.yml` `.env` override support via `${VAR:-default}` interpolation, so the committed compose file can ship with safe placeholder values
- Test suite (pytest) covering the Torznab API, SABnzbd API, health endpoint, and XML builder
- CI workflow running pytest and ruff lint before Docker build; pre-commit hook for local linting
- Docker image published to GitHub Container Registry (GHCR) via the repo's own `GITHUB_TOKEN` -- no long-lived registry secrets

### Technical Details
- Built with FastAPI for async HTTP handling
- `tvdb_v4_official` (synchronous) wrapped in `asyncio.to_thread` + `asyncio.Lock` for safe async use
- yt-dlp Python API for authenticated downloads, subtitle embedding, and MKV remuxing (via ffmpeg)
- XML generation via lxml for Torznab responses
- Pydantic Settings for configuration and validation
- Production Docker setup with non-root user, pinned base image, and SHA-pinned GitHub Actions

### Configuration
- `TVDB_API_KEY` (required) and optional `TVDB_PIN` for TheTVDB v4 API access
- `PUBLIC_URL`, `NETRC_PATH`, `DOWNLOADS_DIR`, `SERVICE_PORT`/`SERVICE_HOST`, `PROWLARR_API_KEY`, `LOG_LEVEL`, `CACHE_TTL` via environment variables / `.env`

[0.1.6]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.6
[0.1.5]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.5
[0.1.4]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.4
[0.1.3]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.3
[0.1.2]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.2
[0.1.1]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.1
[0.1.0]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.0