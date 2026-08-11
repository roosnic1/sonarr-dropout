import asyncio
import logging
from pathlib import Path

import yt_dlp

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Raised when yt-dlp fails to download a video."""


async def download(url: str, dest_dir: Path, netrc_path: str) -> Path:
    """Download `url` via yt-dlp (authenticated through .netrc) into dest_dir.

    Returns dest_dir -- SABnzbd's "history" reports a completed-download
    folder rather than a filename, and Sonarr's importer scans that folder
    for media files, so callers don't need to know the resulting filename.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # dropout.tv's yt-dlp extractor keys its netrc lookup on machine "dropout"
    ydl_opts = {
        "usenetrc": True,
        "netrc_location": netrc_path,
        "outtmpl": str(dest_dir / "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    def _run():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    try:
        await asyncio.to_thread(_run)
    except yt_dlp.utils.DownloadError as e:
        logger.error("yt-dlp failed to download %s: %s", url, e)
        raise DownloadError(str(e)) from e

    return dest_dir
