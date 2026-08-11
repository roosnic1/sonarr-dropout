import asyncio
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

import dropout_downloader
from config import settings
from tvdb_client import TVDBClient

logger = logging.getLogger(__name__)

router = APIRouter()

SABNZBD_VERSION = "4.0.0"
ACTIVE_STATUSES = ("queued", "downloading")
FINISHED_STATUSES = ("completed", "failed")


@dataclass
class Job:
    nzo_id: str
    title: str
    tvdbid: int
    season: int
    episode: int
    category: str = "tv"
    status: str = "queued"  # queued | downloading | completed | failed
    added_at: float = field(default_factory=time.time)
    storage: Optional[str] = None
    fail_message: str = ""


class JobManager:
    """Tracks download jobs kicked off via the fake SABnzbd `addurl` API.

    In-memory only -- an in-flight job is lost on restart, same tradeoff as
    the module-level state already used for search status in main.py.
    """

    def __init__(self, tvdb_client: TVDBClient, netrc_path: str, downloads_dir: str):
        self.tvdb_client = tvdb_client
        self.netrc_path = netrc_path
        self.downloads_dir = Path(downloads_dir)
        self.jobs: Dict[str, Job] = {}
        self._background_tasks: set = set()

    def add_job(self, title: str, tvdbid: int, season: int, episode: int, category: str) -> Job:
        nzo_id = f"SABnzbd_nzo_{uuid.uuid4().hex[:10]}"
        job = Job(
            nzo_id=nzo_id, title=title, tvdbid=tvdbid, season=season,
            episode=episode, category=category,
        )
        self.jobs[nzo_id] = job

        task = asyncio.create_task(self._process(job))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return job

    async def _process(self, job: Job) -> None:
        job.status = "downloading"
        try:
            source = await self.tvdb_client.resolve_episode(job.tvdbid, job.season, job.episode)
            if not source:
                raise dropout_downloader.DownloadError(
                    f"No dropout.tv source found for tvdbid={job.tvdbid} "
                    f"S{job.season}E{job.episode}"
                )
            dest_dir = self.downloads_dir / job.nzo_id
            await dropout_downloader.download(source["url"], dest_dir, self.netrc_path)
            job.storage = str(dest_dir)
            job.status = "completed"
            logger.info("Job %s completed: %s", job.nzo_id, dest_dir)
        except Exception as e:
            logger.error("Job %s failed: %s", job.nzo_id, e)
            job.status = "failed"
            job.fail_message = str(e)

    def delete(self, nzo_id: str) -> None:
        self.jobs.pop(nzo_id, None)


# Module-level singleton, set by main.py's lifespan -- mirrors the
# orion_client global pattern this module replaces.
job_manager: Optional[JobManager] = None


def init_job_manager(tvdb_client: TVDBClient, netrc_path: str, downloads_dir: str) -> None:
    global job_manager
    job_manager = JobManager(tvdb_client, netrc_path, downloads_dir)


def parse_nzb_link(link: str) -> Dict[str, int]:
    """Extract tvdbid/season/episode from our own Torznab item link, built
    in main.py as `{public_url}/sabnzbd/nzb/{tvdbid}/{season}/{episode}`."""
    parts = [p for p in urlparse(link).path.split("/") if p]
    tvdbid, season, episode = parts[-3:]
    return {"tvdbid": int(tvdbid), "season": int(season), "episode": int(episode)}


def _check_api_key(params: Dict[str, str]) -> None:
    if settings.prowlarr_api_key and params.get("apikey") != settings.prowlarr_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


def _full_status() -> dict:
    downloads_dir = job_manager.downloads_dir if job_manager else Path(settings.downloads_dir)
    try:
        usage = shutil.disk_usage(downloads_dir)
        free_gb = f"{usage.free / (1024 ** 3):.2f}"
        total_gb = f"{usage.total / (1024 ** 3):.2f}"
    except OSError:
        free_gb = total_gb = "0"

    return {
        "status": {
            "status": "Idle",
            "diskspace1": free_gb,
            "diskspace2": free_gb,
            "diskspacetotal1": total_gb,
            "diskspacetotal2": total_gb,
            "speed": "0 K",
            "paused": False,
        }
    }


def _handle_addurl(params: Dict[str, str]) -> dict:
    link = params.get("name", "")
    try:
        info = parse_nzb_link(link)
    except (ValueError, IndexError):
        return {"status": False, "error": f"Could not parse release link: {link}"}

    title = params.get("nzbname") or link
    category = params.get("cat") or "tv"
    job = job_manager.add_job(title, info["tvdbid"], info["season"], info["episode"], category)
    return {"status": True, "nzo_ids": [job.nzo_id]}


def _build_queue(params: Dict[str, str]) -> dict:
    if params.get("name") == "delete":
        job_manager.delete(params.get("value", ""))
        return {"status": True}

    slots = [
        {
            "nzo_id": job.nzo_id,
            "filename": job.title,
            "cat": job.category,
            "mb": "0",
            "mbleft": "0",
            "percentage": "0" if job.status == "queued" else "50",
            "status": "Queued" if job.status == "queued" else "Downloading",
            "timeleft": "0:00:00",
            "priority": "Normal",
        }
        for job in job_manager.jobs.values()
        if job.status in ACTIVE_STATUSES
    ]

    return {
        "queue": {
            "status": "Downloading" if slots else "Idle",
            "speed": "0",
            "kbpersec": "0",
            "noofslots_total": len(slots),
            "noofslots": len(slots),
            "slots": slots,
        }
    }


def _build_history(params: Dict[str, str]) -> dict:
    if params.get("name") == "delete":
        job_manager.delete(params.get("value", ""))
        return {"status": True}

    slots = [
        {
            "nzo_id": job.nzo_id,
            "name": job.title,
            "category": job.category,
            "status": "Completed" if job.status == "completed" else "Failed",
            "storage": job.storage or "",
            "path": job.storage or "",
            "fail_message": job.fail_message,
            "completed": int(job.added_at),
        }
        for job in job_manager.jobs.values()
        if job.status in FINISHED_STATUSES
    ]

    return {"history": {"noofslots": len(slots), "slots": slots}}


@router.api_route("/api", methods=["GET", "POST"])
async def sabnzbd_api(request: Request):
    """Minimal SABnzbd-compatible API surface, just enough for Sonarr's
    SABnzbd download client integration to add/track/import jobs."""
    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update({k: str(v) for k, v in form.items()})

    _check_api_key(params)

    mode = params.get("mode", "")

    if mode == "version":
        return JSONResponse({"version": SABNZBD_VERSION})

    if mode == "get_cats":
        return JSONResponse({"categories": ["*", "tv"]})

    if mode == "fullstatus":
        return JSONResponse(_full_status())

    if job_manager is None:
        return JSONResponse(
            {"status": False, "error": "Service not initialized"}, status_code=503
        )

    if mode == "addurl":
        return JSONResponse(_handle_addurl(params))

    if mode == "queue":
        return JSONResponse(_build_queue(params))

    if mode == "history":
        return JSONResponse(_build_history(params))

    return JSONResponse({"status": False, "error": f"Unknown mode: {mode}"}, status_code=400)
