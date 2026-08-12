from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # TheTVDB v4 API credentials
    tvdb_api_key: str
    tvdb_pin: Optional[str] = None

    # Service configuration
    service_port: int = 8080
    service_host: str = "0.0.0.0"

    # Base URL this service is reachable at, used to build absolute Torznab
    # links (never dereferenced externally -- parsed back out by our own
    # SABnzbd-emulation addurl handler)
    public_url: str = "http://localhost:8080"

    # yt-dlp download configuration
    netrc_path: str = "/config/.netrc"
    downloads_dir: str = "/downloads"

    # Torznab/Newznab configuration
    indexer_name: str = "Dropout"
    indexer_description: str = "dropout.tv Torznab Indexer"

    # API key for Prowlarr/Sonarr authentication (optional)
    # If set, callers must provide this key as 'apikey' parameter
    prowlarr_api_key: Optional[str] = None

    # Logging
    log_level: str = "INFO"

    # Cache settings (in seconds) -- used for TVDB episode lookup caching
    cache_ttl: int = 300  # 5 minutes

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
