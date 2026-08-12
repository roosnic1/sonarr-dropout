import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from . import sabnzbd_api
from .__version__ import __version__
from .config import settings
from .torznab_builder import ReleaseItem, TorznabBuilder
from .tvdb_client import TVDBClient

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Global client instance and metrics
tvdb_client: Optional[TVDBClient] = None
startup_time: Optional[float] = None
last_successful_search: Optional[datetime] = None

# Passive API status -- updated by lifespan() and search_dropout()
api_status = {
    "healthy": False,
    "message": "Not yet checked",
    "last_checked": None,
}


def _update_api_status(healthy: bool, message: str):
    api_status["healthy"] = healthy
    api_status["message"] = message
    api_status["last_checked"] = datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global tvdb_client, startup_time
    tvdb_client = TVDBClient(
        settings.tvdb_api_key,
        settings.tvdb_pin,
        cache_ttl=settings.cache_ttl,
    )
    startup_time = time.time()
    logger.info("TVDB client initialized")

    try:
        await tvdb_client.__aenter__()
        await tvdb_client.verify_credentials()
        logger.info("Connected to TheTVDB API")
        _update_api_status(healthy=True, message="Connected to TheTVDB API")
    except Exception as e:
        logger.error("Failed to connect to TheTVDB: %s", e)
        _update_api_status(healthy=False, message=str(e))

    sabnzbd_api.init_job_manager(tvdb_client, settings.netrc_path, settings.downloads_dir)

    yield

    # Shutdown
    if tvdb_client:
        await tvdb_client.__aexit__(None, None, None)
    logger.info("TVDB client closed")


app = FastAPI(
    title="sonarr-dropout",
    description="A Torznab/Newznab compatible indexer bridging Sonarr to dropout.tv",
    version=__version__,
    lifespan=lifespan
)
app.include_router(sabnzbd_api.router, prefix="/sabnzbd")


def check_api_key(apikey: Optional[str] = None):
    """Check if API key is valid (if configured)"""
    if settings.prowlarr_api_key and apikey != settings.prowlarr_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "title": "sonarr-dropout",
        "version": __version__,
        "endpoints": {
            "capabilities": "/api?t=caps",
            "tv-search": "/api?t=tvsearch&tvdbid=12345&season=1&ep=1",
            "health": "/health",
            "sabnzbd_download_client": "/sabnzbd/api",
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint -- reads passive state, never calls the API."""
    # 503 only when the service is fundamentally broken
    if not tvdb_client:
        return JSONResponse(
            content={"status": "unhealthy", "message": "Client not initialized"},
            status_code=503,
        )

    # Determine overall status from passive tracking
    if api_status["healthy"]:
        overall_status = "healthy"
    elif api_status["last_checked"] is None:
        overall_status = "warning"
    else:
        overall_status = "degraded"

    search_status = "healthy" if last_successful_search else "idle"
    if last_successful_search:
        seconds = (
            datetime.now(timezone.utc) - last_successful_search
        ).total_seconds()
        if seconds > 300:
            search_status = "stale"

    uptime = int(time.time() - startup_time) if startup_time else 0

    jobs = sabnzbd_api.job_manager.jobs.values() if sabnzbd_api.job_manager else []
    active_jobs = sum(1 for j in jobs if j.status in sabnzbd_api.ACTIVE_STATUSES)
    failed_jobs = sum(1 for j in jobs if j.status == "failed")

    response = {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "uptime": uptime,
        "tvdb_api": {
            "healthy": api_status["healthy"],
            "message": api_status["message"],
            "lastChecked": api_status["last_checked"],
        },
        "search": {
            "status": search_status,
            "lastSuccess": (
                last_successful_search.isoformat()
                if last_successful_search
                else None
            ),
        },
        "downloads": {
            "active": active_jobs,
            "failed": failed_jobs,
        },
    }

    # Always 200 when service is running -- body conveys degraded state
    return JSONResponse(content=response, status_code=200)


@app.get("/api", response_class=PlainTextResponse)
async def api_endpoint(
    t: str = Query(..., description="API function type"),
    apikey: Optional[str] = Query(None, description="API key for authentication"),
    q: Optional[str] = Query(None, description="Series title (used for release naming only)"),
    tvdbid: Optional[int] = Query(None, description="TheTVDB series ID"),
    season: Optional[int] = Query(None, description="Season number"),
    ep: Optional[int] = Query(None, description="Episode number"),
):
    """Main API endpoint for Torznab/Newznab protocol"""

    logger.info(
        "API request: t=%s, q=%s, tvdbid=%s, season=%s, ep=%s",
        t, q, tvdbid, season, ep,
    )

    try:
        # Handle capabilities request (no auth required)
        if t == "caps":
            return Response(
                content=TorznabBuilder.build_capabilities(),
                media_type="application/xml"
            )

        # Check API key for other requests
        check_api_key(apikey)

        # Ensure we have a client
        if not tvdb_client:
            raise HTTPException(status_code=503, detail="TVDB client not initialized")

        if t in ("search", "tvsearch"):
            items = await search_dropout(tvdbid=tvdbid, season=season, episode=ep, query=q)
        else:
            return Response(
                content=TorznabBuilder.build_error(
                    201, f"Incorrect parameter: unknown function '{t}'"
                ),
                media_type="application/xml"
            )

        return Response(
            content=TorznabBuilder.build_search_results(items, t),
            media_type="application/xml"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return Response(
            content=TorznabBuilder.build_error(100, str(e)),
            media_type="application/xml"
        )


async def search_dropout(
    tvdbid: Optional[int],
    season: Optional[int],
    episode: Optional[int],
    query: Optional[str],
) -> List[ReleaseItem]:
    """Resolve a Sonarr search into a list of dropout.tv releases via TVDB.

    Each release's link encodes tvdbid/season/episode. Sonarr's usenet
    download client GETs it directly to fetch nzb bytes (see
    sabnzbd_api.get_nzb) before uploading them back to us via `addfile`,
    which parses the ids back out (sabnzbd_api.parse_nzb_content).
    """
    global last_successful_search

    # Empty search = Prowlarr/Sonarr connection test. Return a synthetic
    # result so the "Test" button passes without calling the TVDB API.
    if not any([tvdbid, query]):
        logger.info("Empty search (connection test) - returning synthetic result")
        return [
            ReleaseItem(
                title="Connection Test",
                guid="connection-test",
                link=f"{settings.public_url}/sabnzbd/nzb/0/1/1",
                season=1,
                episode=1,
            )
        ]

    if not tvdbid:
        logger.info("Search without tvdbid - nothing to resolve")
        return []

    if season is None:
        logger.info("tvsearch without season - dropout.tv releases are per-episode only")
        return []

    series_title = query or f"tvdb-{tvdbid}"

    try:
        episode_numbers = [episode] if episode is not None else (
            await tvdb_client.get_season_episode_numbers(tvdbid, season)
        )

        items: List[ReleaseItem] = []
        for ep_number in episode_numbers:
            source = await tvdb_client.resolve_episode(tvdbid, season, ep_number)
            if not source:
                continue

            # "1080p WEB-DL English" isn't describing a real encode -- it's
            # there so Sonarr's title parser (which drives its Quality/
            # Language columns and interactive-search tooltip, independent of
            # any newznab:attr) doesn't report them as Unknown. dropout.tv is
            # consistently HD and English-only, so the claim is accurate.
            title = (
                f"{series_title} S{season:02d}E{ep_number:02d} "
                f"{source['name']} 1080p WEB-DL English"
            ).strip()
            link = f"{settings.public_url}/sabnzbd/nzb/{tvdbid}/{season}/{ep_number}"
            items.append(
                ReleaseItem(
                    title=title,
                    guid=f"dropout-{tvdbid}-{season}-{ep_number}",
                    link=link,
                    season=season,
                    episode=ep_number,
                    tvdbid=tvdbid,
                )
            )
    except Exception as e:
        _update_api_status(healthy=False, message=str(e))
        raise

    logger.info("Resolved %d dropout.tv release(s)", len(items))
    last_successful_search = datetime.now(timezone.utc)
    _update_api_status(healthy=True, message="Last search succeeded")

    return items


# Additional Prowlarr-specific endpoints
@app.get("/{indexer_id}/api", response_class=PlainTextResponse)
async def api_endpoint_with_id(
    indexer_id: str,
    t: str = Query(...),
    apikey: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    tvdbid: Optional[int] = Query(None),
    season: Optional[int] = Query(None),
    ep: Optional[int] = Query(None),
):
    """Alternative API endpoint with indexer ID in path (Prowlarr compatibility)"""
    return await api_endpoint(t, apikey, q, tvdbid, season, ep)


if __name__ == "__main__":
    uvicorn.run(
        "sonarr_dropout.main:app",
        host=settings.service_host,
        port=settings.service_port,
        reload=False
    )
