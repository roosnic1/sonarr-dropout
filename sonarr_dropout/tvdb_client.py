import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from tvdb_v4_official import TVDB

logger = logging.getLogger(__name__)


class _TTLCache:
    """Minimal in-memory TTL cache -- avoids re-resolving the same
    (series, season, episode) on every Sonarr RSS sync poll."""

    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[Any, tuple] = {}

    def get(self, key: Any) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._store[key] = (value, time.time() + self.ttl_seconds)


class TVDBClient:
    """Async wrapper around the official (synchronous, urllib-based)
    tvdb_v4_official client.

    Calls are run in a thread and serialized behind a lock -- the underlying
    client keeps pagination "links" as shared per-instance state, so
    interleaving calls from concurrent requests would corrupt it. For a
    low-volume personal indexer this is a fine tradeoff for correctness.
    """

    def __init__(self, api_key: str, pin: Optional[str] = None, cache_ttl: int = 300):
        self.api_key = api_key
        self.pin = pin or ""
        self._client: Optional[TVDB] = None
        self._lock = asyncio.Lock()
        self._episode_id_cache = _TTLCache(cache_ttl)
        self._source_url_cache = _TTLCache(cache_ttl)
        self._series_name_cache = _TTLCache(cache_ttl)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass  # urllib-based client has no persistent connection to close

    async def _connect(self) -> TVDB:
        """(Re)authenticate and return a fresh client instance."""
        self._client = await asyncio.to_thread(TVDB, self.api_key, self.pin)
        return self._client

    async def verify_credentials(self) -> None:
        """Raise if the configured API key/pin can't authenticate."""
        async with self._lock:
            await self._connect()

    async def _list_episodes(self, series_id: int) -> List[Dict[str, Any]]:
        """Fetch every episode for a series (paginated)."""
        async with self._lock:
            client = self._client or await self._connect()
            try:
                return await self._paginate_episodes(client, series_id)
            except Exception as e:
                logger.info("TVDB request failed (%s), re-authenticating and retrying", e)
                client = await self._connect()
                return await self._paginate_episodes(client, series_id)

    @staticmethod
    async def _paginate_episodes(client: TVDB, series_id: int) -> List[Dict[str, Any]]:
        episodes: List[Dict[str, Any]] = []
        page = 0
        while True:
            info = await asyncio.to_thread(client.get_series_episodes, series_id, page=page)
            page_episodes = info.get("episodes") or []
            if not page_episodes:
                break
            episodes.extend(page_episodes)

            links = client.get_req_links() or {}
            if not links.get("next"):
                break
            page += 1

        return episodes

    async def find_episode_id(self, series_id: int, season: int, episode: int) -> Optional[int]:
        """Resolve the TVDB episode id for a season/episode number."""
        cache_key = (series_id, season, episode)
        cached = self._episode_id_cache.get(cache_key)
        if cached is not None:
            return cached

        episodes = await self._list_episodes(series_id)
        for ep in episodes:
            if ep.get("seasonNumber") == season and ep.get("number") == episode:
                episode_id = ep.get("id")
                self._episode_id_cache.set(cache_key, episode_id)
                return episode_id

        return None

    async def get_season_episode_numbers(self, series_id: int, season: int) -> List[int]:
        """List episode numbers for a season, for season-pack searches."""
        episodes = await self._list_episodes(series_id)
        return sorted(
            ep["number"]
            for ep in episodes
            if ep.get("seasonNumber") == season and ep.get("number") is not None
        )

    async def get_episode_source_url(self, episode_id: int) -> Optional[Dict[str, str]]:
        """Return {"url": ..., "name": ...} for an episode's dropout.tv page,
        or None if no dropout.tv remote id is present."""
        cached = self._source_url_cache.get(episode_id)
        if cached is not None:
            return cached

        async with self._lock:
            client = self._client or await self._connect()
            try:
                data = await asyncio.to_thread(
                    client.get_episode_extended, episode_id, meta="translations"
                )
            except Exception as e:
                logger.info("TVDB request failed (%s), re-authenticating and retrying", e)
                client = await self._connect()
                data = await asyncio.to_thread(
                    client.get_episode_extended, episode_id, meta="translations"
                )

        dropout_url = None
        for remote_id in data.get("remoteIds") or []:
            candidate = remote_id.get("id", "")
            if urlparse(candidate).hostname == "watch.dropout.tv":
                dropout_url = candidate
                break

        if not dropout_url:
            return None

        result = {"url": dropout_url, "name": data.get("name") or ""}
        self._source_url_cache.set(episode_id, result)
        return result

    async def get_series_name(self, series_id: int) -> Optional[str]:
        """Return the series' primary name, for release titles when Sonarr's
        search omits `q` (its normal tvdbid-only search path)."""
        cached = self._series_name_cache.get(series_id)
        if cached is not None:
            return cached

        async with self._lock:
            client = self._client or await self._connect()
            try:
                data = await asyncio.to_thread(client.get_series, series_id)
            except Exception as e:
                logger.info("TVDB request failed (%s), re-authenticating and retrying", e)
                client = await self._connect()
                data = await asyncio.to_thread(client.get_series, series_id)

        name = data.get("name")
        if name:
            self._series_name_cache.set(series_id, name)
        return name

    async def resolve_episode(
        self, series_id: int, season: int, episode: int
    ) -> Optional[Dict[str, Any]]:
        """Full resolution: (series, season, episode) -> {"url", "name", "episode_id"}."""
        episode_id = await self.find_episode_id(series_id, season, episode)
        if episode_id is None:
            return None
        source = await self.get_episode_source_url(episode_id)
        if source is None:
            return None
        return {**source, "episode_id": episode_id}
