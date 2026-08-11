"""Tests for the fake SABnzbd API Sonarr uses as its download client."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import sabnzbd_api

NZB_LINK = "http://localhost:8080/sabnzbd/nzb/369988/8/2"


async def _wait_for_terminal_status(job, timeout: float = 1.0):
    elapsed = 0.0
    while job.status not in ("completed", "failed") and elapsed < timeout:
        await asyncio.sleep(0.01)
        elapsed += 0.01
    return job.status


class TestParseNzbLink:
    def test_extracts_tvdbid_season_episode(self):
        assert sabnzbd_api.parse_nzb_link(NZB_LINK) == {
            "tvdbid": 369988, "season": 8, "episode": 2,
        }

    def test_raises_on_malformed_link(self):
        with pytest.raises((ValueError, IndexError)):
            sabnzbd_api.parse_nzb_link("not-a-valid-link")


class TestVersionAndCats:
    async def test_version(self, test_client, reset_globals):
        resp = await test_client.get("/sabnzbd/api", params={"mode": "version"})
        assert resp.status_code == 200
        assert resp.json() == {"version": sabnzbd_api.SABNZBD_VERSION}

    async def test_get_cats(self, test_client, reset_globals):
        resp = await test_client.get("/sabnzbd/api", params={"mode": "get_cats"})
        assert resp.json() == {"categories": ["*", "tv"]}

    async def test_fullstatus_reports_diskspace(self, test_client, reset_globals):
        resp = await test_client.get("/sabnzbd/api", params={"mode": "fullstatus"})
        assert "diskspace1" in resp.json()["status"]

    async def test_get_config_reports_category_and_complete_dir(
        self, test_client, reset_globals
    ):
        resp = await test_client.get("/sabnzbd/api", params={"mode": "get_config"})
        config = resp.json()["config"]
        assert config["misc"]["complete_dir"]
        assert any(cat["name"] == "tv" for cat in config["categories"])


class TestAddUrl:
    async def test_addurl_queues_a_job(self, test_client, mock_search, reset_globals):
        resp = await test_client.get(
            "/sabnzbd/api", params={"mode": "addurl", "name": NZB_LINK, "cat": "tv"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] is True
        nzo_id = body["nzo_ids"][0]
        assert nzo_id in sabnzbd_api.job_manager.jobs

    async def test_addurl_with_unparseable_link_returns_error(
        self, test_client, mock_search, reset_globals
    ):
        resp = await test_client.get(
            "/sabnzbd/api", params={"mode": "addurl", "name": "not-a-valid-link"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] is False


class TestJobLifecycle:
    async def test_completed_job_appears_in_history_not_queue(
        self, test_client, mock_search, reset_globals
    ):
        with patch("dropout_downloader.download", AsyncMock(return_value="/downloads/job")):
            resp = await test_client.get(
                "/sabnzbd/api", params={"mode": "addurl", "name": NZB_LINK, "cat": "tv"}
            )
            nzo_id = resp.json()["nzo_ids"][0]
            job = sabnzbd_api.job_manager.jobs[nzo_id]
            assert await _wait_for_terminal_status(job) == "completed"

        history = (await test_client.get("/sabnzbd/api", params={"mode": "history"})).json()
        slot = next(s for s in history["history"]["slots"] if s["nzo_id"] == nzo_id)
        assert slot["status"] == "Completed"
        assert slot["storage"] == str(sabnzbd_api.job_manager.downloads_dir / nzo_id)

        queue = (await test_client.get("/sabnzbd/api", params={"mode": "queue"})).json()
        assert all(s["nzo_id"] != nzo_id for s in queue["queue"]["slots"])

    async def test_download_failure_reported_in_history(
        self, test_client, mock_search, reset_globals
    ):
        with patch(
            "dropout_downloader.download",
            AsyncMock(side_effect=sabnzbd_api.dropout_downloader.DownloadError("boom")),
        ):
            resp = await test_client.get(
                "/sabnzbd/api", params={"mode": "addurl", "name": NZB_LINK}
            )
            nzo_id = resp.json()["nzo_ids"][0]
            job = sabnzbd_api.job_manager.jobs[nzo_id]
            assert await _wait_for_terminal_status(job) == "failed"

        history = (await test_client.get("/sabnzbd/api", params={"mode": "history"})).json()
        slot = next(s for s in history["history"]["slots"] if s["nzo_id"] == nzo_id)
        assert slot["status"] == "Failed"
        assert "boom" in slot["fail_message"]

    async def test_unresolvable_episode_fails_the_job(
        self, test_client, mock_search, reset_globals
    ):
        mock_search.resolve_episode.return_value = None
        resp = await test_client.get(
            "/sabnzbd/api", params={"mode": "addurl", "name": NZB_LINK}
        )
        nzo_id = resp.json()["nzo_ids"][0]
        job = sabnzbd_api.job_manager.jobs[nzo_id]
        assert await _wait_for_terminal_status(job) == "failed"


class TestDeleteJob:
    async def test_delete_from_queue(self, test_client, reset_globals):
        sabnzbd_api.job_manager.jobs["x"] = sabnzbd_api.Job(
            nzo_id="x", title="t", tvdbid=1, season=1, episode=1, status="queued",
        )
        resp = await test_client.get(
            "/sabnzbd/api", params={"mode": "queue", "name": "delete", "value": "x"}
        )
        assert resp.json() == {"status": True}
        assert "x" not in sabnzbd_api.job_manager.jobs

    async def test_delete_from_history(self, test_client, reset_globals):
        sabnzbd_api.job_manager.jobs["y"] = sabnzbd_api.Job(
            nzo_id="y", title="t", tvdbid=1, season=1, episode=1, status="completed",
        )
        resp = await test_client.get(
            "/sabnzbd/api", params={"mode": "history", "name": "delete", "value": "y"}
        )
        assert resp.json() == {"status": True}
        assert "y" not in sabnzbd_api.job_manager.jobs
