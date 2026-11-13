"""Persist traceroute window sessions (targets, hops, timeline, hostnames)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

LAST_TRACE_ID = "last-trace"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class SavedTrace:
    id: str
    name: str
    saved_at: str
    interval: float
    timeout: float
    time_window_seconds: int
    show_unresolved: bool
    selected_target: str
    targets: list[str]
    state: dict[str, dict]
    hostnames: dict[str, str]
    path: Path

    @property
    def label(self) -> str:
        count = len(self.targets)
        noun = "target" if count == 1 else "targets"
        return f"{self.name}  ({count} {noun})"


def default_traces_dir() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "traces"


def _slug(name: str) -> str:
    cleaned = _SAFE_NAME.sub("-", name.strip())[:48].strip("-")
    return cleaned or "trace"


class TraceLibrary:
    """Named traceroute session JSON files plus last-trace auto-save."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_traces_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def last_path(self) -> Path:
        return self.root / f"{LAST_TRACE_ID}.json"

    def list_traces(self) -> list[SavedTrace]:
        traces: list[SavedTrace] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                traces.append(self._load_path(path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return traces

    def load(self, trace_id: str) -> SavedTrace:
        if trace_id == LAST_TRACE_ID:
            return self._load_path(self.last_path())
        matches = [path for path in self.root.glob("*.json") if path.stem == trace_id or path.name == trace_id]
        if not matches:
            raise FileNotFoundError(f"Trace not found: {trace_id}")
        return self._load_path(matches[0])

    def save(
        self,
        *,
        targets: list[str],
        state: dict[str, dict],
        hostnames: dict[str, str] | None = None,
        interval: float = 2.5,
        timeout: float = 1.0,
        time_window_seconds: int = 15 * 60,
        show_unresolved: bool = True,
        selected_target: str = "",
        name: str | None = None,
        as_last: bool = False,
    ) -> SavedTrace:
        if not targets and not state:
            raise ValueError("Nothing to save.")
        hostnames = {
            str(ip): str(label).strip()
            for ip, label in (hostnames or {}).items()
            if str(ip).strip() and str(ip) != "*" and str(label).strip()
        }
        stamp = datetime.now().astimezone()
        saved_at = stamp.isoformat(timespec="seconds")
        target_list = list(targets) or list(state)
        summary = target_list[0] if len(target_list) == 1 else f"{len(target_list)} targets"
        display = (name or summary).strip() or summary
        trace_id = (
            LAST_TRACE_ID
            if as_last
            else f"{stamp.strftime('%Y%m%d-%H%M%S')}-{_slug(display)}-{uuid.uuid4().hex[:6]}"
        )
        payload: dict[str, Any] = {
            "id": trace_id,
            "kind": "traceroute",
            "name": "Last trace" if as_last else display,
            "saved_at": saved_at,
            "interval": interval,
            "timeout": timeout,
            "time_window_seconds": time_window_seconds,
            "show_unresolved": show_unresolved,
            "selected_target": selected_target,
            "targets": target_list,
            "state": state,
            "hostnames": dict(sorted(hostnames.items())),
        }
        path = self.last_path() if as_last else self.root / f"{trace_id}.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self._load_path(path)

    def delete(self, trace_id: str) -> None:
        if trace_id == LAST_TRACE_ID:
            path = self.last_path()
            if path.exists():
                path.unlink()
            return
        for path in self.root.glob("*.json"):
            if path.stem == trace_id or path.name == trace_id:
                path.unlink()
                return
        raise FileNotFoundError(f"Trace not found: {trace_id}")

    def _load_path(self, path: Path) -> SavedTrace:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_hostnames = data.get("hostnames") or {}
        hostnames = {
            str(ip): str(name).strip()
            for ip, name in raw_hostnames.items()
            if str(ip).strip() and str(name).strip()
        }
        targets = [str(item) for item in (data.get("targets") or []) if str(item).strip()]
        state = data.get("state") or {}
        if not isinstance(state, dict):
            state = {}
        if not targets:
            targets = list(state)
        return SavedTrace(
            id=str(data.get("id") or path.stem),
            name=str(data.get("name") or path.stem),
            saved_at=str(data.get("saved_at") or ""),
            interval=float(data.get("interval") or 2.5),
            timeout=float(data.get("timeout") or 1.0),
            time_window_seconds=int(data.get("time_window_seconds") or 15 * 60),
            show_unresolved=bool(data.get("show_unresolved", True)),
            selected_target=str(data.get("selected_target") or ""),
            targets=targets,
            state={str(key): value for key, value in state.items() if isinstance(value, dict)},
            hostnames=hostnames,
            path=path,
        )
