"""Persist remote subnet scan results for reload."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .engine import ProbeResult

LAST_SCAN_ID = "last-scan"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class SavedScan:
    id: str
    name: str
    spec: str
    saved_at: str
    workers: int
    timeout: float
    stopped: bool
    results: list[dict[str, Any]]
    hostnames: dict[str, str]
    path: Path

    @property
    def alive_count(self) -> int:
        return sum(1 for row in self.results if row.get("alive"))

    @property
    def label(self) -> str:
        when = self.saved_at.replace("T", " ")[:19]
        return f"{self.name}  ({self.alive_count}/{len(self.results)} up · {when})"


def default_scans_dir() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "scans"


def _slug(name: str) -> str:
    cleaned = _SAFE_NAME.sub("-", name.strip())[:48].strip("-")
    return cleaned or "scan"


class ScanLibrary:
    """Named scan JSON files plus a dedicated last-scan auto-save."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_scans_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def last_path(self) -> Path:
        return self.root / f"{LAST_SCAN_ID}.json"

    def list_scans(self) -> list[SavedScan]:
        scans: list[SavedScan] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                scans.append(self._load_path(path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return scans

    def load(self, scan_id: str) -> SavedScan:
        if scan_id == LAST_SCAN_ID:
            return self._load_path(self.last_path())
        matches = [path for path in self.root.glob("*.json") if path.stem == scan_id or path.name == scan_id]
        if not matches:
            raise FileNotFoundError(f"Scan not found: {scan_id}")
        return self._load_path(matches[0])

    def save(
        self,
        *,
        spec: str,
        results: dict[str, ProbeResult],
        dns_names: dict[str, str] | None = None,
        hostnames: dict[str, str] | None = None,
        workers: int = 64,
        timeout: float = 0.8,
        stopped: bool = False,
        name: str | None = None,
        as_last: bool = False,
    ) -> SavedScan:
        dns_names = dns_names or {}
        hostnames = {
            str(ip): str(label).strip()
            for ip, label in (hostnames or {}).items()
            if str(ip).strip() and str(ip) != "*" and str(label).strip()
        }
        stamp = datetime.now().astimezone()
        saved_at = stamp.isoformat(timespec="seconds")
        display = name or f"{spec} — {stamp.strftime('%Y-%m-%d %H:%M:%S')}"
        scan_id = LAST_SCAN_ID if as_last else f"{stamp.strftime('%Y%m%d-%H%M%S')}-{_slug(display)}-{uuid.uuid4().hex[:6]}"
        payload = {
            "id": scan_id,
            "name": "Last scan" if as_last else display,
            "spec": spec,
            "saved_at": saved_at,
            "workers": workers,
            "timeout": timeout,
            "stopped": stopped,
            "hostnames": dict(sorted(hostnames.items())),
            "results": [
                {
                    "host": host,
                    "alive": result.alive,
                    "rtt_ms": result.rtt_ms,
                    "responder": result.responder,
                    "reached_target": result.reached_target,
                    "error": result.error,
                    "dns": hostnames.get(host) or dns_names.get(host, ""),
                }
                for host, result in sorted(results.items(), key=lambda item: _host_sort_key(item[0]))
            ],
        }
        path = self.last_path() if as_last else self.root / f"{scan_id}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self._load_path(path)

    def delete(self, scan_id: str) -> None:
        if scan_id == LAST_SCAN_ID:
            path = self.last_path()
            if path.exists():
                path.unlink()
            return
        for path in self.root.glob("*.json"):
            if path.stem == scan_id:
                path.unlink()
                return
        raise FileNotFoundError(f"Scan not found: {scan_id}")

    def _load_path(self, path: Path) -> SavedScan:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_hostnames = data.get("hostnames") or {}
        hostnames = {
            str(ip): str(name).strip()
            for ip, name in raw_hostnames.items()
            if str(ip).strip() and str(name).strip()
        }
        # Older saves only stored dns on each result — treat non-empty dns as hostname.
        if not hostnames:
            for row in data.get("results") or []:
                host = str(row.get("host") or "").strip()
                dns = str(row.get("dns") or "").strip()
                if host and dns:
                    hostnames[host] = dns
        return SavedScan(
            id=str(data.get("id") or path.stem),
            name=str(data.get("name") or path.stem),
            spec=str(data.get("spec") or ""),
            saved_at=str(data.get("saved_at") or ""),
            workers=int(data.get("workers") or 64),
            timeout=float(data.get("timeout") or 0.8),
            stopped=bool(data.get("stopped")),
            results=list(data.get("results") or []),
            hostnames=hostnames,
            path=path,
        )


def probe_results_from_saved(scan: SavedScan) -> tuple[dict[str, ProbeResult], dict[str, str]]:
    results: dict[str, ProbeResult] = {}
    dns_names: dict[str, str] = {}
    for row in scan.results:
        host = str(row["host"])
        results[host] = ProbeResult(
            host=host,
            alive=bool(row.get("alive")),
            rtt_ms=row.get("rtt_ms"),
            responder=row.get("responder"),
            reached_target=bool(row.get("reached_target")),
            error=row.get("error"),
        )
        dns_names[host] = scan.hostnames.get(host) or str(row.get("dns") or "")
    return results, dns_names


def _host_sort_key(host: str) -> tuple:
    try:
        parts = [int(part) for part in host.split(".")]
        if len(parts) == 4:
            return (0, *parts)
    except ValueError:
        pass
    return (1, host)
