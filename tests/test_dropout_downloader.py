"""Tests for dropout_downloader's yt-dlp auth option handling."""

from pathlib import Path

from sonarr_dropout import dropout_downloader


class TestAuthOpts:
    def test_netrc_only_without_cookies(self):
        with dropout_downloader._auth_opts("/config/.netrc", None) as opts:
            assert opts == {"usenetrc": True, "netrc_location": "/config/.netrc"}

    def test_cookies_are_copied_to_a_throwaway_file(self, tmp_path):
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")

        with dropout_downloader._auth_opts("/config/.netrc", str(cookies)) as opts:
            cookiefile = Path(opts["cookiefile"])
            assert opts["usenetrc"] is True
            assert cookiefile != cookies
            assert cookiefile.read_text() == cookies.read_text()
            # yt-dlp saving its jar back must not touch the original
            cookiefile.write_text("overwritten")

        assert not cookiefile.exists()
        assert cookies.read_text() == "# Netscape HTTP Cookie File\n"


class TestEstimateFilesize:
    async def test_missing_cookies_file_returns_none(self, tmp_path):
        size = await dropout_downloader.estimate_filesize(
            "https://watch.dropout.tv/videos/x",
            str(tmp_path / ".netrc"),
            str(tmp_path / "missing-cookies.txt"),
        )
        assert size is None
