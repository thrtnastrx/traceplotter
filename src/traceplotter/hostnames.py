"""Persistent manual hostname overrides for hop IPs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def default_hostnames_path() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "hostnames.json"


class HostnameBook:
    """IP → hostname map; manual entries win over reverse DNS."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_hostnames_path()
        self._names: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._names = {}
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            self._names = {}
            return
        if not isinstance(data, dict):
            self._names = {}
            return
        self._names = {
            str(ip): str(name).strip()
            for ip, name in data.items()
            if str(ip).strip() and str(name).strip() and str(ip) != "*"
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._names, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def get(self, ip: str) -> str | None:
        if not ip or ip == "*":
            return None
        value = self._names.get(ip)
        return value or None

    def set(self, ip: str, hostname: str) -> None:
        ip = ip.strip()
        hostname = hostname.strip()
        if not ip or ip == "*" or not hostname:
            raise ValueError("Need a resolved IP and a non-empty hostname.")
        self._names[ip] = hostname
        self.save()

    def clear(self, ip: str) -> None:
        if ip in self._names:
            del self._names[ip]
            self.save()

    def resolve(self, ip: str, discovered: str = "") -> str:
        """Prefer a manual override, otherwise the discovered reverse-DNS name."""
        manual = self.get(ip)
        if manual:
            return manual
        return discovered.strip() if discovered else ""

    def snapshot(self, ips: Iterable[str] | None = None) -> dict[str, str]:
        if ips is None:
            return dict(self._names)
        wanted = {ip.strip() for ip in ips if ip and ip != "*"}
        return {ip: name for ip, name in self._names.items() if ip in wanted}

    def merge(self, names: dict[str, str]) -> int:
        """Import hostnames; returns how many entries were written."""
        changed = 0
        for ip, hostname in names.items():
            ip = str(ip).strip()
            hostname = str(hostname).strip()
            if not ip or ip == "*" or not hostname:
                continue
            if self._names.get(ip) != hostname:
                self._names[ip] = hostname
                changed += 1
        if changed:
            self.save()
        return changed
