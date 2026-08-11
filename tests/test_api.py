"""Tests for the /api Torznab endpoint."""

from lxml import etree

import main as main_module


def _parse_xml(text: str) -> etree._Element:
    return etree.fromstring(text.encode())


class TestCapabilities:
    async def test_returns_valid_xml_with_search_types(
        self, test_client, reset_globals
    ):
        resp = await test_client.get("/api?t=caps")
        assert resp.status_code == 200
        searching = _parse_xml(resp.text).find("searching")
        assert searching.find("search") is not None
        assert searching.find("tv-search") is not None
        assert searching.find("movie-search") is None


class TestSearch:
    async def test_single_episode_search(self, test_client, mock_search, reset_globals):
        resp = await test_client.get(
            "/api",
            params={
                "t": "tvsearch", "q": "Game Changer", "tvdbid": 369988,
                "season": 8, "ep": 2,
            },
        )
        assert resp.status_code == 200
        mock_search.resolve_episode.assert_called_once_with(369988, 8, 2)

        item = _parse_xml(resp.text).findall(".//item")[0]
        assert "Game Changer" in item.find("title").text
        assert "S08E02" in item.find("title").text
        assert "Rulette 2" in item.find("title").text
        assert "/sabnzbd/nzb/369988/8/2" in item.find("link").text

    async def test_season_pack_resolves_every_episode(
        self, test_client, mock_search, reset_globals
    ):
        resp = await test_client.get(
            "/api", params={"t": "tvsearch", "tvdbid": 369988, "season": 8}
        )
        assert resp.status_code == 200
        mock_search.get_season_episode_numbers.assert_called_once_with(369988, 8)
        assert mock_search.resolve_episode.call_count == 2
        assert len(_parse_xml(resp.text).findall(".//item")) == 2

    async def test_search_without_tvdbid_returns_no_results(
        self, test_client, mock_search, reset_globals
    ):
        resp = await test_client.get("/api", params={"t": "tvsearch", "q": "test"})
        assert resp.status_code == 200
        assert len(_parse_xml(resp.text).findall(".//item")) == 0
        mock_search.resolve_episode.assert_not_called()

    async def test_search_without_season_returns_no_results(
        self, test_client, mock_search, reset_globals
    ):
        resp = await test_client.get("/api", params={"t": "tvsearch", "tvdbid": 369988})
        assert resp.status_code == 200
        assert len(_parse_xml(resp.text).findall(".//item")) == 0
        mock_search.resolve_episode.assert_not_called()

    async def test_unresolvable_episode_is_skipped(
        self, test_client, mock_search, reset_globals
    ):
        mock_search.resolve_episode.return_value = None
        resp = await test_client.get(
            "/api", params={"t": "tvsearch", "tvdbid": 369988, "season": 8, "ep": 2}
        )
        assert resp.status_code == 200
        assert len(_parse_xml(resp.text).findall(".//item")) == 0

    async def test_unknown_function_returns_torznab_error(
        self, test_client, reset_globals
    ):
        resp = await test_client.get("/api", params={"t": "movie", "q": "test"})
        assert resp.status_code == 200
        root = _parse_xml(resp.text)
        assert root.tag == "error"
        assert root.get("code") == "201"


class TestConnectionTest:
    async def test_empty_search_returns_synthetic_result_without_api_call(
        self, test_client, reset_globals
    ):
        """Sonarr/Prowlarr connection test returns a synthetic item (no API call)."""
        resp = await test_client.get("/api?t=search")
        assert resp.status_code == 200
        root = _parse_xml(resp.text)
        assert root.tag == "rss"
        assert len(root.findall(".//item")) >= 1
        main_module.tvdb_client.resolve_episode.assert_not_called()


class TestSearchUpdatesApiStatus:
    async def test_success_sets_healthy(self, test_client, mock_search, reset_globals):
        main_module.api_status["healthy"] = False
        await test_client.get(
            "/api", params={"t": "tvsearch", "tvdbid": 369988, "season": 8, "ep": 2}
        )
        assert main_module.api_status["healthy"] is True

    async def test_failure_sets_unhealthy(self, test_client, mock_search, reset_globals):
        mock_search.resolve_episode.side_effect = Exception("tvdb unavailable")
        resp = await test_client.get(
            "/api", params={"t": "tvsearch", "tvdbid": 369988, "season": 8, "ep": 2}
        )
        # Errors surface as a Torznab <error> body, not an HTTP failure.
        assert resp.status_code == 200
        assert _parse_xml(resp.text).tag == "error"
        assert main_module.api_status["healthy"] is False
        assert "tvdb unavailable" in main_module.api_status["message"]
