"""Version information for sonarr-dropout."""

__version__ = "0.1.4"
_release = __version__.split("-", 1)[0].split("+", 1)[0]
__version_info__ = tuple(int(part) for part in _release.split("."))
