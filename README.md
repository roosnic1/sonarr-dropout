# Sonarr-Dropout

[![Version](https://img.shields.io/badge/version-0.1.6-blue.svg)](https://github.com/roosnic1/sonarr-dropout/releases)
[![CI Build](https://github.com/roosnic1/sonarr-dropout/actions/workflows/ci.yml/badge.svg)](https://github.com/roosnic1/sonarr-dropout/actions/workflows/ci.yml)
[![Docker Image](https://img.shields.io/badge/ghcr.io-sonarr--dropout-blue.svg)](https://github.com/roosnic1/sonarr-dropout/pkgs/container/sonarr-dropout)

A bridge that lets [Sonarr](https://sonarr.tv/) treat [dropout.tv](https://www.dropout.tv/) like a regular indexer/download client pair. It has two halves:

- A **Torznab indexer**: given a `tvdbid`/season/episode, it looks up the episode in [TheTVDB v4 API](https://thetvdb.com/) and returns a release pointing at that dropout.tv video.
- A **fake SABnzbd download client**: when Sonarr "grabs" that release, this service resolves the dropout.tv URL again and downloads it with [yt-dlp](https://github.com/yt-dlp/yt-dlp) (authenticated via a `.netrc` file), reporting progress through SABnzbd's queue/history API so Sonarr imports the finished file normally.

## Features

- Full Torznab protocol support (TV search by `tvdbid`/season/episode)
- Resolves dropout.tv URLs from TheTVDB episode metadata -- no scraping or slug-guessing
- Downloads via yt-dlp with `.netrc` authentication
- Emulates enough of the SABnzbd API for Sonarr to use as a download client
- Docker containerization
- Passive health check endpoint (no API calls, reads in-memory state)
- Optional API key authentication

## Quick Start

### Using Docker Compose (Recommended)

```yaml
services:
  sonarr-dropout:
    image: ghcr.io/roosnic1/sonarr-dropout:latest
    container_name: sonarr-dropout
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TVDB_API_KEY=your_tvdb_api_key
      - PUBLIC_URL=http://sonarr-dropout:8080
    volumes:
      - ./netrc:/config/.netrc:ro
      - ./downloads:/downloads
```

Then run:
```bash
docker-compose up -d
```

See [`docker-compose.yml`](./docker-compose.yml) in this repo for the full set of options.

## Prerequisites

1. **A dropout.tv subscription** with valid login credentials
2. **A TheTVDB v4 API key** -- get one from your [TVDB dashboard](https://thetvdb.com/dashboard/account/apikey) (a subscriber PIN may also be required depending on your account)
3. **A `.netrc` file** with your dropout.tv credentials:
   ```
   machine dropout
     login you@example.com
     password yourpassword
   ```
   yt-dlp's dropout.tv extractor looks up credentials under the `dropout` netrc machine name specifically -- don't rename it.
4. **A downloads directory shared with Sonarr** -- both containers must mount the *same host path*, since this service reports that path back to Sonarr for import.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TVDB_API_KEY` | Yes | - | Your TheTVDB v4 API key |
| `TVDB_PIN` | No | - | TVDB subscriber PIN, if your account needs one |
| `PUBLIC_URL` | No | `http://localhost:8080` | Base URL this service is reachable at from Sonarr; baked into the release links it returns |
| `NETRC_PATH` | No | `/config/.netrc` | Path (inside the container) to the `.netrc` file yt-dlp uses for dropout.tv auth |
| `DOWNLOADS_DIR` | No | `/downloads` | Path (inside the container) where finished downloads are written |
| `SERVICE_PORT` | No | 8080 | Port to run the service on |
| `SERVICE_HOST` | No | 0.0.0.0 | Host to bind the service to |
| `PROWLARR_API_KEY` | No | - | Optional API key required on both the Torznab and SABnzbd endpoints |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `CACHE_TTL` | No | 300 | Seconds to cache TVDB episode lookups |

## Setting up Sonarr

This service must be registered in Sonarr **twice** -- once as an indexer, once as a download client.

### 1. Add as a Torznab indexer

1. **Settings** → **Indexers** → **+** → **Torznab** → **Custom**
2. **URL**: `http://sonarr-dropout:8080` (or your Docker host IP)
3. **API Path**: `/api`
4. **API Key**: leave blank unless you set `PROWLARR_API_KEY`
5. **Categories**: TV (5000/5040)
6. Click **Test**, then **Save**

### 2. Add as a SABnzbd download client

1. **Settings** → **Download Clients** → **+** → **Usenet** → **SABnzbd**
2. **Host**: `sonarr-dropout` (or your Docker host IP)
3. **Port**: `8080`
4. **URL Base**: `/sabnzbd`
5. **API Key**: leave blank unless you set `PROWLARR_API_KEY`
6. **Category**: `tv`
7. Click **Test**, then **Save**

Once both are configured, an episode search → grab → import goes: Sonarr searches the indexer → gets a release resolved from TVDB → grabs it via the fake SABnzbd client → this service downloads it with yt-dlp into the shared folder → Sonarr imports it once `history` reports it complete.

## API Endpoints

### Health Check
```
GET /health
```
Returns service status, uptime, last-known TVDB API state, and active/failed download job counts. Reads passive in-memory state -- never calls the TVDB API. Returns 200 as long as the HTTP server is running; the response body conveys degraded/warning status.

### Capabilities
```
GET /api?t=caps
```
Returns the indexer capabilities (supported search types, categories, etc.)

### TV Search
```
GET /api?t=tvsearch&tvdbid=12345&season=1&ep=1
GET /api?t=tvsearch&tvdbid=12345&season=1
```
Resolves a single episode, or every episode in a season if `ep` is omitted. A search without `tvdbid` returns no results -- there's no metadata to resolve a dropout.tv URL from.

### SABnzbd-compatible download client
```
GET/POST /sabnzbd/api?mode=addurl|queue|history|version|get_cats|get_config|fullstatus
```
Implements the subset of the SABnzbd API Sonarr's download client integration needs. Not meant to be used directly.

## Building from Source

### Using Docker

```bash
git clone https://github.com/roosnic1/sonarr-dropout.git
cd sonarr-dropout
docker build -t sonarr-dropout .
docker run -d \
  --name sonarr-dropout \
  -p 8080:8080 \
  -e TVDB_API_KEY=your_tvdb_api_key \
  -v ./netrc:/config/.netrc:ro \
  -v ./downloads:/downloads \
  sonarr-dropout
```

### Running Locally

1. Install Python 3.11 or higher

2. Clone the repository:
   ```bash
   git clone https://github.com/roosnic1/sonarr-dropout.git
   cd sonarr-dropout
   ```

3. Install dependencies:
   ```bash
   pip install .
   ```

4. Create a `.env` file:
   ```env
   TVDB_API_KEY=your_tvdb_api_key
   NETRC_PATH=/path/to/your/.netrc
   DOWNLOADS_DIR=/path/to/downloads
   ```

5. Run the service:
   ```bash
   python -m sonarr_dropout.main
   ```

## Troubleshooting

### Service won't start
- Check that `TVDB_API_KEY` (and `TVDB_PIN`, if needed) are correct
- Verify the port isn't already in use
- Check Docker logs: `docker logs sonarr-dropout`

### No results returned
- The episode must exist on TheTVDB with a `remoteIds` entry pointing at `watch.dropout.tv` -- not every episode has one
- Make sure the search includes a `tvdbid` and `season`

### Downloads fail
- Check `docker logs sonarr-dropout` for the yt-dlp error
- Verify `.netrc` has a `machine dropout` entry with valid credentials
- Confirm your dropout.tv subscription is active

### Sonarr can't import a completed download
- Confirm Sonarr's download client "Category" folder and this service's `DOWNLOADS_DIR` resolve to the **same host directory**

### Health check showing degraded
- The `/health` endpoint shows the last-known TVDB API state; check the `tvdb_api.message` field for details
- Perform a search to refresh the API status
- Verify the TVDB API key/PIN are valid

## Development

### Project Structure
```
sonarr-dropout/
├── sonarr_dropout/
│   ├── main.py                # FastAPI application (Torznab endpoints)
│   ├── tvdb_client.py          # TheTVDB v4 API client
│   ├── dropout_downloader.py   # yt-dlp download wrapper
│   ├── sabnzbd_api.py           # Fake SABnzbd download client API
│   ├── torznab_builder.py      # Torznab XML response builder
│   ├── config.py               # Configuration management
│   └── __version__.py          # Version information
├── pyproject.toml          # Project configuration and dependencies
├── Dockerfile               # Docker container definition
├── docker-compose.yml       # Docker Compose configuration
├── tests/                   # Test suite (pytest)
├── CHANGELOG.md             # Version history
└── README.md                # This file
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Links

- [GitHub Repository](https://github.com/roosnic1/sonarr-dropout)
- [Docker Image (GHCR)](https://github.com/roosnic1/sonarr-dropout/pkgs/container/sonarr-dropout)
- [Issues & Support](https://github.com/roosnic1/sonarr-dropout/issues)
- [Changelog](https://github.com/roosnic1/sonarr-dropout/blob/main/CHANGELOG.md)

## Acknowledgments

This project started as a fork of [jamtur01/prowlarr-orionoid](https://github.com/jamtur01/prowlarr-orionoid), which provided the original Torznab/SABnzbd scaffolding this service is built on. Thank you to [@jamtur01](https://github.com/jamtur01) for that foundation.

## License

This project is provided as-is for educational and personal use. Please respect dropout.tv's and TheTVDB's terms of service.