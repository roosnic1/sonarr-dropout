# Sonarr-Dropout

[![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)](https://github.com/roosnic1/sonarr-dropout/releases)
[![CI Build](https://github.com/roosnic1/sonarr-dropout/actions/workflows/ci.yml/badge.svg)](https://github.com/roosnic1/sonarr-dropout/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/roosnic1/sonarr-dropout)](https://hub.docker.com/r/roosnic1/sonarr-dropout)
[![Docker Image Size](https://img.shields.io/docker/image-size/roosnic1/sonarr-dropout/latest)](https://hub.docker.com/r/roosnic1/sonarr-dropout)

A Torznab/Newznab compatible indexer service that allows [Prowlarr](https://prowlarr.com/) to use [Orionoid](https://orionoid.com/) as an indexer. This service translates between Prowlarr's indexer protocol and Orionoid's API.

## Features

- Full Torznab/Newznab protocol support
- Search by query, IMDb ID, TVDB ID, and TMDB ID
- Support for movies and TV shows
- Configurable search limits
- Docker containerization
- Passive health check endpoint (no API calls, reads in-memory state)
- Optional API key authentication
- Multi-architecture support (amd64, arm64, arm/v7)

## Quick Start

### Using Docker (Recommended)

```bash
docker run -d \
  --name sonarr-dropout \
  -p 8080:8080 \
  -e ORIONOID_USER_API_KEY=your_user_api_key \
  roosnic1/sonarr-dropout:latest
```

### Using Docker Compose

Create a `docker-compose.yml` file:

```yaml
services:
  sonarr-dropout:
    image: roosnic1/sonarr-dropout:latest
    container_name: sonarr-dropout
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - ORIONOID_USER_API_KEY=your_user_api_key
```

Then run:
```bash
docker-compose up -d
```

## Prerequisites

1. **Orionoid Account**: You need an active Orionoid account with API access
2. **Orionoid User API Key**: Get from your Orionoid account settings (this is unique to you)

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORIONOID_USER_API_KEY` | Yes | - | Your Orionoid user API key |
| `SERVICE_PORT` | No | 8080 | Port to run the service on |
| `SERVICE_HOST` | No | 0.0.0.0 | Host to bind the service to |
| `PROWLARR_API_KEY` | No | - | Optional API key for Prowlarr authentication |
| `DEFAULT_SEARCH_LIMIT` | No | 100 | Default number of results to return |
| `MAX_SEARCH_LIMIT` | No | 1000 | Maximum allowed search results |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Adding to Prowlarr

1. In Prowlarr, go to **Settings** → **Indexers**

2. Click the **+** button to add a new indexer

3. Select **Torznab** → **Custom Torznab**

4. Configure the indexer:
   - **Name**: Orionoid
   - **Enable RSS**: Yes (if desired)
   - **Enable Automatic Search**: Yes
   - **Enable Interactive Search**: Yes
   - **URL**: `http://localhost:8080` (or your Docker host IP)
   - **API Path**: `/api`
   - **API Key**: Leave blank unless you set `PROWLARR_API_KEY`
   - **Categories**: Select desired categories (Movies, TV, etc.)

5. Click **Test** to verify the connection

6. Save the indexer

## Supported Architectures

This image supports multiple architectures:
- `linux/amd64` - Standard x86-64
- `linux/arm64` - ARM 64-bit (Raspberry Pi 4, Apple Silicon)
- `linux/arm/v7` - ARM 32-bit (Raspberry Pi 2/3)

## API Endpoints

### Health Check
```
GET /health
```
Returns service status, uptime, and last-known Orionoid API state. Reads passive in-memory state -- never calls the Orionoid API. Returns 200 as long as the HTTP server is running; the response body conveys degraded/warning status.

### Capabilities
```
GET /api?t=caps
```
Returns the indexer capabilities (supported search types, categories, etc.)

### Search
```
GET /api?t=search&q=query
```
General search across all categories

### TV Search
```
GET /api?t=tvsearch&q=query&season=1&ep=1
GET /api?t=tvsearch&tvdbid=12345&season=1&ep=1
```
Search for TV shows with optional season/episode filtering

### Movie Search
```
GET /api?t=movie&q=query
GET /api?t=movie&imdbid=tt1234567
```
Search for movies

## Building from Source

### Using Docker

```bash
git clone https://github.com/roosnic1/sonarr-dropout.git
cd sonarr-dropout
docker build -t sonarr-dropout .
docker run -d \
  --name sonarr-dropout \
  -p 8080:8080 \
  -e ORIONOID_USER_API_KEY=your_user_api_key \
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
   ORIONOID_USER_API_KEY=your_user_api_key
   ```

5. Run the service:
   ```bash
   python main.py
   ```

## Troubleshooting

### Service won't start
- Check that your Orionoid API keys are correct
- Verify the port isn't already in use
- Check Docker logs: `docker logs sonarr-dropout`

### No results returned
- Verify your Orionoid account has API access
- Check that you haven't exceeded your daily API limits
- Try searching with different queries or IDs

### Prowlarr connection test fails
- Ensure the service is running and accessible
- Check the URL and port are correct
- Verify any API key is correctly configured

### Health check showing degraded
- The `/health` endpoint shows the last-known API state; check the `orionoid_api.message` field for details
- Perform a search to refresh the API status
- Verify Orionoid API keys are valid and quota is not exhausted

## Development

### Project Structure
```
sonarr-dropout/
├── main.py              # FastAPI application
├── orionoid_client.py   # Orionoid API client
├── torznab_builder.py   # Torznab XML response builder
├── config.py            # Configuration management
├── __version__.py       # Version information
├── pyproject.toml       # Project configuration and dependencies
├── Dockerfile          # Docker container definition
├── docker-compose.yml  # Docker Compose configuration
├── tests/              # Test suite (pytest)
├── CHANGELOG.md        # Version history
└── README.md          # This file
```

### Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Links

- [GitHub Repository](https://github.com/roosnic1/sonarr-dropout)
- [Docker Hub](https://hub.docker.com/r/roosnic1/sonarr-dropout)
- [Issues & Support](https://github.com/roosnic1/sonarr-dropout/issues)
- [Changelog](https://github.com/roosnic1/sonarr-dropout/blob/main/CHANGELOG.md)

## License

This project is provided as-is for educational and personal use. Please respect Orionoid's terms of service and API usage limits.
