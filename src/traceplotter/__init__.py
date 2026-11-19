"""TracePlotter."""

from __future__ import annotations

__version__ = "0.2.2"


def app_version() -> str:
    """Installed package version, falling back to the module constant."""
    try:
        from importlib.metadata import version

        return version("traceplotter")
    except Exception:
        return __version__
