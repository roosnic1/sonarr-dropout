# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.1]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.1
[0.1.0]: https://github.com/roosnic1/sonarr-dropout/releases/tag/v0.1.0