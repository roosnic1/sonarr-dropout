import asyncio
import logging
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional

import yt_dlp
from yt_dlp.utils import filesize_from_tbr

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], None]


class DownloadError(Exception):
    """Raised when yt-dlp fails to download a video."""


@contextmanager
def _auth_opts(netrc_path: str, cookies_path: Optional[str]) -> Iterator[dict]:
    """yt-dlp auth options: .netrc, plus `cookies_path` if given.

    yt-dlp writes its cookie jar back to `cookiefile` in place when the
    YoutubeDL instance closes, which would fail on a read-only mount (after
    the download already succeeded) and race when a download and a size
    estimate run concurrently. So each call gets its own throwaway copy --
    the tradeoff is that cookies yt-dlp refreshes aren't persisted, so the
    file has to be re-exported from the browser once its session expires.
    """
    # dropout.tv's yt-dlp extractor keys its netrc lookup on machine "dropout"
    opts = {"usenetrc": True, "netrc_location": netrc_path}
    if not cookies_path:
        yield opts
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        cookiefile = Path(tmp_dir) / "cookies.txt"
        shutil.copyfile(cookies_path, cookiefile)
        yield {**opts, "cookiefile": str(cookiefile)}


async def download(
    url: str,
    dest_dir: Path,
    netrc_path: str,
    progress_callback: Optional[ProgressCallback] = None,
    cookies_path: Optional[str] = None,
) -> Path:
    """Download `url` via yt-dlp (authenticated through .netrc and/or
    `cookies_path`, see _auth_opts) into dest_dir.

    Returns dest_dir -- SABnzbd's "history" reports a completed-download
    folder rather than a filename, and Sonarr's importer scans that folder
    for media files, so callers don't need to know the resulting filename.

    If given, `progress_callback` is passed straight to yt-dlp's
    `progress_hooks` -- it's invoked synchronously from the worker thread
    this runs on (see asyncio.to_thread below), once per download tick, with
    yt-dlp's own progress dict (status/downloaded_bytes/total_bytes/speed/eta).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
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
        with _auth_opts(netrc_path, cookies_path) as auth_opts:
            with yt_dlp.YoutubeDL({**ydl_opts, **auth_opts}) as ydl:
                ydl.download([url])

    try:
        await asyncio.to_thread(_run)
    except yt_dlp.utils.DownloadError as e:
        logger.error("yt-dlp failed to download %s: %s", url, e)
        raise DownloadError(str(e)) from e

    return dest_dir


async def estimate_filesize(
    url: str, netrc_path: str, cookies_path: Optional[str] = None
) -> Optional[int]:
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
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mkv",
    }

    def _run() -> Optional[int]:
        with _auth_opts(netrc_path, cookies_path) as auth_opts:
            with yt_dlp.YoutubeDL({**ydl_opts, **auth_opts}) as ydl:
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
    # OSError: an unreadable/missing cookies file shouldn't break search
    except (yt_dlp.utils.DownloadError, OSError) as e:
        logger.warning("yt-dlp failed to estimate filesize for %s: %s", url, e)
        return None
