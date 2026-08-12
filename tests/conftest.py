import time
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import sonarr_dropout.main as main_module
import sonarr_dropout.sabnzbd_api as sabnzbd_api

# A representative TVDBClient.resolve_episode() result, shaped like the
# real /episodes/{id}/extended response's remoteIds-derived output.
SAMPLE_RESOLVED_EPISODE = {
    "url": "https://watch.dropout.tv/videos/rulette-2",
    "name": "Rulette 2",
    "episode_id": 11801657,
}


@pytest.fixture()
def reset_globals():
    """Reset main.py and sabnzbd_api.py module globals before each test."""
    original = {
        "tvdb_client": main_module.tvdb_client,
        "startup_time": main_module.startup_time,
        "last_successful_search": main_module.last_successful_search,
        "api_status": main_module.api_status.copy(),
        "job_manager": sabnzbd_api.job_manager,
    }
    yield
    main_module.tvdb_client = original["tvdb_client"]
    main_module.startup_time = original["startup_time"]
    main_module.last_successful_search = original["last_successful_search"]
    main_module.api_status.clear()
    main_module.api_status.update(original["api_status"])
    sabnzbd_api.job_manager = original["job_manager"]


@pytest.fixture()
def test_client(reset_globals, tmp_path, monkeypatch):
    """Create an httpx AsyncClient that talks to the app without lifespan.

    Injects a mock TVDBClient so the app thinks it started normally, and a
    real JobManager wired to that mock -- `dropout_downloader.download` is
    left un-mocked here, so tests that let a job reach "completed"/"failed"
    must patch it themselves (see test_sabnzbd_api.py).

    `dropout_downloader.estimate_filesize` is mocked here (rather than left
    for individual tests to patch) since every search calls it, not just
    download tests -- see test_search_result_includes_estimated_size for a
    test that overrides its return value.
    """
    mock_client = AsyncMock()
    main_module.tvdb_client = mock_client
    main_module.startup_time = time.time()
    main_module.api_status.update({
        "healthy": True,
        "message": "Connected to TheTVDB API",
        "last_checked": "2026-01-01T00:00:00+00:00",
    })
    monkeypatch.setattr(
        main_module.dropout_downloader,
        "estimate_filesize",
        AsyncMock(return_value=1_500_000_000),
    )

    sabnzbd_api.init_job_manager(
        mock_client, str(tmp_path / ".netrc"), str(tmp_path / "downloads")
    )

    transport = ASGITransport(app=main_module.app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture()
def mock_search(test_client):
    """Configure the mock TVDBClient's episode-resolution return values.

    Depends on test_client so the mock instance is already injected.
    """
    main_module.tvdb_client.resolve_episode.return_value = dict(SAMPLE_RESOLVED_EPISODE)
    main_module.tvdb_client.get_season_episode_numbers.return_value = [1, 2]
    main_module.tvdb_client.get_series_name.return_value = "Game Changer"
    return main_module.tvdb_client
