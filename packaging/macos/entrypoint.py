"""PyInstaller entrypoint (absolute import; no relative package context)."""

from __future__ import annotations

from traceplotter.app import main

if __name__ == "__main__":
    raise SystemExit(main())
