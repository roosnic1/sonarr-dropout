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
from fastapi.responses import JSONResponse, Response
from lxml import etree
from starlette.datastructures import UploadFile

import dropout_downloader
from config import settings
from tvdb_client import TVDBClient

logger = logging.getLogger(__name__)

router = APIRouter()

SABNZBD_VERSION = "4.0.0"
ACTIVE_STATUSES = ("queued", "downloading")
FINISHED_STATUSES = ("completed", "failed")

NZB_NS = "http://www.newzbin.com/DTD/2003/nzb"


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


def build_nzb(tvdbid: int, season: int, episode: int) -> bytes:
    """Build the placeholder nzb Sonarr fetches from the Torznab release
    link before uploading it back to us via `mode=addfile` -- see the GET
    handler below. tvdbid/season/episode round-trip through `<meta>` tags
    since nothing else in this payload is ever read."""
    root = etree.Element("nzb", nsmap={None: NZB_NS})
    head = etree.SubElement(root, "head")
    for meta_type, value in (("tvdbid", tvdbid), ("season", season), ("episode", episode)):
        meta = etree.SubElement(head, "meta")
        meta.set("type", meta_type)
        meta.text = str(value)

    file_elem = etree.SubElement(root, "file")
    file_elem.set("poster", "sonarr-dropout")
    file_elem.set("date", str(int(time.time())))
    file_elem.set("subject", f"tvdb-{tvdbid} S{season:02d}E{episode:02d} (1/1)")
    groups = etree.SubElement(file_elem, "groups")
    etree.SubElement(groups, "group").text = "alt.binaries.misc"
    segments = etree.SubElement(file_elem, "segments")
    segment = etree.SubElement(segments, "segment")
    segment.set("bytes", "1")
    segment.set("number", "1")
    segment.text = "placeholder"

    return etree.tostring(
        root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
        doctype='<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" '
                '"http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">',
    )


def parse_nzb_content(content: bytes) -> Dict[str, int]:
    """Read tvdbid/season/episode back out of an nzb built by `build_nzb`,
    once Sonarr posts it back to us via `mode=addfile`."""
    root = etree.fromstring(content)
    values = {
        meta.get("type"): meta.text
        for meta in root.findall(f"{{{NZB_NS}}}head/{{{NZB_NS}}}meta")
    }
    return {
        "tvdbid": int(values["tvdbid"]),
        "season": int(values["season"]),
        "episode": int(values["episode"]),
    }


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


def _get_config() -> dict:
    # Sonarr's SABnzbd client calls get_config on Test/add to read the
    # complete_dir (must be absolute or it falls back to fullstatus) and to
    # confirm the configured category exists with job folders enabled (a
    # category "dir" ending in "*" would trigger a warning in Sonarr).
    downloads_dir = str(job_manager.downloads_dir if job_manager else Path(settings.downloads_dir))
    return {
        "config": {
            "misc": {
                "complete_dir": downloads_dir,
                "tv_categories": [],
                "enable_tv_sorting": False,
                "movie_categories": [],
                "enable_movie_sorting": False,
                "date_categories": [],
                "enable_date_sorting": False,
                "pre_check": False,
                "history_retention": "0",
                "history_retention_option": "all",
                "history_retention_number": 0,
            },
            "categories": [
                {"name": "tv", "dir": "", "priority": 0, "pp": "", "script": "None"}
            ],
            "servers": [],
            "sorters": [],
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


async def _handle_addfile(upload: Optional[UploadFile], params: Dict[str, str]) -> dict:
    if upload is None:
        return {"status": False, "error": "No nzb file uploaded"}

    content = await upload.read()
    try:
        info = parse_nzb_content(content)
    except (etree.XMLSyntaxError, KeyError, ValueError, TypeError):
        return {"status": False, "error": "Could not parse uploaded nzb file"}

    title = params.get("nzbname") or upload.filename or "unknown"
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


@router.get("/nzb/{tvdbid}/{season}/{episode}")
async def get_nzb(tvdbid: int, season: int, episode: int):
    """Serves the Torznab release link itself. Sonarr's usenet download
    client GETs this directly (enclosure type=application/x-nzb) before
    ever calling the SABnzbd API, then uploads the bytes back to us via
    `mode=addfile` -- see build_nzb()/parse_nzb_content()."""
    content = build_nzb(tvdbid, season, episode)
    filename = f"tvdb-{tvdbid}-S{season:02d}E{episode:02d}.nzb"
    return Response(
        content=content,
        media_type="application/x-nzb",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.api_route("/api", methods=["GET", "POST"])
async def sabnzbd_api(request: Request):
    """Minimal SABnzbd-compatible API surface, just enough for Sonarr's
    SABnzbd download client integration to add/track/import jobs."""
    params = dict(request.query_params)
    upload: Optional[UploadFile] = None
    if request.method == "POST":
        form = await request.form()
        for key, value in form.items():
            if isinstance(value, UploadFile):
                upload = value
            else:
                params[key] = str(value)

    _check_api_key(params)

    mode = params.get("mode", "")

    if mode == "version":
        return JSONResponse({"version": SABNZBD_VERSION})

    if mode == "get_cats":
        return JSONResponse({"categories": ["*", "tv"]})

    if mode == "fullstatus":
        return JSONResponse(_full_status())

    if mode == "get_config":
        return JSONResponse(_get_config())

    if job_manager is None:
        return JSONResponse(
            {"status": False, "error": "Service not initialized"}, status_code=503
        )

    if mode == "addurl":
        return JSONResponse(_handle_addurl(params))

    if mode == "addfile":
        return JSONResponse(await _handle_addfile(upload, params))

    if mode == "queue":
        return JSONResponse(_build_queue(params))

    if mode == "history":
        return JSONResponse(_build_history(params))

    return JSONResponse({"status": False, "error": f"Unknown mode: {mode}"}, status_code=400)
