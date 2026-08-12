import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

import yt_dlp
from yt_dlp.utils import filesize_from_tbr

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], None]


class DownloadError(Exception):
    """Raised when yt-dlp fails to download a video."""


async def download(
    url: str,
    dest_dir: Path,
    netrc_path: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> Path:
    """Download `url` via yt-dlp (authenticated through .netrc) into dest_dir.

    Returns dest_dir -- SABnzbd's "history" reports a completed-download
    folder rather than a filename, and Sonarr's importer scans that folder
    for media files, so callers don't need to know the resulting filename.

    If given, `progress_callback` is passed straight to yt-dlp's
    `progress_hooks` -- it's invoked synchronously from the worker thread
    this runs on (see asyncio.to_thread below), once per download tick, with
    yt-dlp's own progress dict (status/downloaded_bytes/total_bytes/speed/eta).
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
        "progress_hooks": [progress_callback] if progress_callback else [],
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "merge_output_format": "mkv",
        "postprocessors": [{"key": "FFmpegEmbedSubtitle"}],
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


async def estimate_filesize(url: str, netrc_path: str) -> Optional[int]:
    """Best-effort byte size for `url`, without downloading it.

    dropout.tv's HLS formats all carry a `manifest_url`, and yt-dlp
    deliberately skips auto-filling `filesize_approx` for those (a
    fragmented format's `tbr` is often its peak bitrate, not its average --
    see YoutubeDL.py's process_video_result), so it comes back None even
    though a size is derivable. `yt-dlp -F` shows a `~` estimate anyway
    because its format table computes the same `tbr * duration` fallback at
    print time rather than trusting the field -- this does the same, for
    whichever formats `download()` would actually select.
    """
    ydl_opts = {
        "usenetrc": True,
        "netrc_location": netrc_path,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mkv",
    }

    def _run() -> Optional[int]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = info.get("duration")
        formats = info.get("requested_formats") or [info]
        # dropout.tv's audio-only formats have no tbr either (manifest_url
        # hides it the same way), so their contribution is just unknowable
        # here -- sum whatever components we can size rather than giving up
        # entirely, since video dwarfs audio anyway.
        sizes = [
            f.get("filesize") or f.get("filesize_approx")
            or filesize_from_tbr(f.get("tbr"), duration)
            for f in formats
        ]
        known_sizes = [size for size in sizes if size is not None]
        if not known_sizes:
            return None
        return sum(known_sizes)

    try:
        return await asyncio.to_thread(_run)
    except yt_dlp.utils.DownloadError as e:
        logger.warning("yt-dlp failed to estimate filesize for %s: %s", url, e)
        return None
