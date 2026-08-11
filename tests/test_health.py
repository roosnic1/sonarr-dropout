"""Tests for the /health endpoint and passive API status tracking."""

import main as main_module
import sabnzbd_api


class TestHealthEndpoint:
    async def test_healthy_response(self, test_client, reset_globals):
        resp = await test_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "uptime" in body
        assert body["downloads"] == {"active": 0, "failed": 0}

    async def test_503_when_client_missing(self, test_client, reset_globals):
        main_module.tvdb_client = None
        assert (await test_client.get("/health")).status_code == 503

    async def test_degraded_when_api_unhealthy(self, test_client, reset_globals):
        main_module.api_status.update(
            healthy=False, last_checked="2026-01-01T00:00:00+00:00",
            message="tvdb unavailable",
        )
        resp = await test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    async def test_no_api_calls_made(self, test_client, reset_globals):
        """The whole point: /health must NOT call the TVDB API."""
        mock = main_module.tvdb_client
        for _ in range(3):
            await test_client.get("/health")
        mock.resolve_episode.assert_not_called()
        mock.get_season_episode_numbers.assert_not_called()

    async def test_reports_active_and_failed_job_counts(self, test_client, reset_globals):
        sabnzbd_api.job_manager.jobs["a"] = sabnzbd_api.Job(
            nzo_id="a", title="t", tvdbid=1, season=1, episode=1, status="downloading",
        )
        sabnzbd_api.job_manager.jobs["b"] = sabnzbd_api.Job(
            nzo_id="b", title="t", tvdbid=1, season=1, episode=2, status="queued",
        )
        sabnzbd_api.job_manager.jobs["c"] = sabnzbd_api.Job(
            nzo_id="c", title="t", tvdbid=1, season=1, episode=3, status="failed",
        )
        sabnzbd_api.job_manager.jobs["d"] = sabnzbd_api.Job(
            nzo_id="d", title="t", tvdbid=1, season=1, episode=4, status="completed",
        )
        resp = await test_client.get("/health")
        assert resp.json()["downloads"] == {"active": 2, "failed": 1}


class TestUpdateApiStatus:
    def test_updates_status_fields(self, reset_globals):
        main_module._update_api_status(healthy=True, message="ok")
        assert main_module.api_status["healthy"] is True
        assert main_module.api_status["message"] == "ok"
        assert main_module.api_status["last_checked"] is not None

    def test_reflects_unhealthy_state(self, reset_globals):
        main_module._update_api_status(healthy=False, message="boom")
        assert main_module.api_status["healthy"] is False
        assert main_module.api_status["message"] == "boom"
