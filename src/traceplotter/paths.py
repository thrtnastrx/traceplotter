"""Application support paths and one-time rename migration."""

from __future__ import annotations

import shutil
from pathlib import Path

APP_NAME = "TracePlotter"
LEGACY_APP_SUPPORT_NAME = "LabPingPlot"


def default_app_support_dir() -> Path:
    """Return TracePlotter support dir, migrating LabPingPlot once if needed."""
    root = Path.home() / "Library" / "Application Support"
    current = root / APP_NAME
    legacy = root / LEGACY_APP_SUPPORT_NAME
    if not current.exists() and legacy.exists():
        try:
            legacy.rename(current)
        except OSError:
            try:
                shutil.copytree(legacy, current)
            except OSError:
                current.mkdir(parents=True, exist_ok=True)
    else:
        current.mkdir(parents=True, exist_ok=True)
    return current
