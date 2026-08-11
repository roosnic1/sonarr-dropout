# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The package was renamed from `prowlarr-orionoid` to `sonarr-dropout` in `pyproject.toml` (name and description now say "indexer bridge for dropout.tv"), but no other code has been updated yet — `main.py`, `config.py`, `orionoid_client.py`, `torznab_builder.py`, the README, Dockerfile, docker-compose.yml, and CI workflows are all still 100% Orionoid-specific (API endpoints, env var names, image name `jamtur01/prowlarr-orionoid`, GitHub repo URLs). Treat this as a fork-in-progress toward a dropout.tv-backed indexer rather than a completed rename.

## What this service does

A FastAPI app that exposes a Torznab/Newznab-compatible indexer API (as consumed by Prowlarr/Sonarr/Radarr) and translates requests into calls against a backing content API — currently Orionoid (`https://api.orionoid.com`).

## Commands

```bash
pip install ".[dev]"          # install runtime + dev deps (pytest, ruff)
ruff check .                  # lint (CI runs this)
pytest -q                     # run full test suite
pytest tests/test_api.py -q   # run a single test file
pytest tests/test_api.py::TestSearch -q          # run a single class
pytest tests/test_api.py::TestSearch::test_x -q  # run a single test

python main.py                # run the service locally (needs ORIONOID_USER_API_KEY, e.g. via .env)
docker build -t sonarr-dropout .
docker-compose up -d
```

CI (`.github/workflows/ci.yml`) requires `ORIONOID_USER_API_KEY` to be set (a dummy value is fine) since `config.Settings` fails to construct without it — same requirement applies when running tests locally without a `.env` file.

## Architecture

Four modules, wired together in `main.py`:

- **`config.py`** — `pydantic-settings` `Settings`, loaded once at import time as the module-level `settings` singleton, sourced from env vars / `.env`. `orionoid_user_api_key` is required (no default); everything else has a default.
- **`orionoid_client.py`** — `OrionoidClient`, a thin async wrapper (httpx) around the Orionoid HTTP API. All requests funnel through `_make_request`, which appends `keyapp`/`keyuser` and POSTs form-encoded params. Async context manager (`__aenter__`/`__aexit__`) owns the underlying `httpx.AsyncClient`.
- **`torznab_builder.py`** — `TorznabBuilder`, stateless static methods that turn Orionoid's JSON stream results into Torznab-flavored XML (`lxml`) for `caps`, search results, and error responses. `_determine_category` maps quality/media-type onto Torznab category IDs (2000s = movies, 5000s = TV).
- **`main.py`** — FastAPI app and all HTTP routes. Key things to know before touching it:
  - `orion_client`, `startup_time`, `last_successful_search`, and `api_status` are **module-level globals**, initialized in the `lifespan` context manager and mutated by request handlers. Tests reset them via the `reset_globals` fixture in `tests/conftest.py` — any new global state needs the same treatment.
  - `/health` is intentionally passive: it never calls the Orionoid API, it only reports the in-memory `api_status` dict (last updated by `lifespan` on startup and by `search_orionoid` after each real search). This was a deliberate fix to stop health checks from burning API quota — don't reintroduce an API call here.
  - `search_orionoid()` treats an empty search (no query/imdb/tvdb/tmdb) as a Prowlarr connection test and returns a synthetic single-result response without calling the backing API — also a quota-preservation measure.
  - The `t=search` handler with no `cat` param fans out to both movie and TV search concurrently (`asyncio.gather`) and merges results, tagging each stream with `_media_type` so `TorznabBuilder` can categorize correctly downstream.
  - `/{indexer_id}/api` is an alias of `/api` for Prowlarr's path-based indexer convention; keep both in sync if the query signature changes.

## Testing conventions

`tests/conftest.py` provides the shared fixtures: `test_client` builds an ASGI `AsyncClient` against `main.app` with a mocked `OrionoidClient` injected (no real network calls, lifespan is bypassed), and `mock_search` layers a canned `search_streams` response on top. Reuse these rather than hand-rolling app instances — `reset_globals` (an implicit dependency of `test_client`) is what keeps `main`'s module-level state from leaking between tests.