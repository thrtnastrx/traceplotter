"""PingPlotter-style endpoint audio alerts (good / warning / critical / lost packet)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .engine import latency_band

# Same filenames shipped with PingPlotter.app Contents/Resources/Alert Audio.
ALERT_SOUNDS = (
    "buzzer.mp3",
    "dark-church-bell.mp3",
    "goblet-ping.mp3",
    "sonar.mp3",
    "tibetan-bell.mp3",
)

SOUND_LABELS = {
    "buzzer.mp3": "Buzzer",
    "dark-church-bell.mp3": "Dark church bell",
    "goblet-ping.mp3": "Goblet ping",
    "sonar.mp3": "Sonar",
    "tibetan-bell.mp3": "Tibetan bell",
}

# Defaults inspired by PingPlotter's PlayAudioAlerts file slots.
DEFAULT_SOUND_GOOD = "goblet-ping.mp3"
DEFAULT_SOUND_WARNING = "sonar.mp3"
DEFAULT_SOUND_CRITICAL = "dark-church-bell.mp3"
DEFAULT_SOUND_LOST = "buzzer.mp3"

EVENT_GOOD = "good"
EVENT_WARNING = "warning"
EVENT_CRITICAL = "critical"
EVENT_LOST = "lost_packet"


def alert_audio_dir() -> Path:
    """Return the directory that holds bundled PingPlotter alert MP3s."""
    here = Path(__file__).resolve().parent / "assets" / "alert_audio"
    if here.is_dir():
        return here
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "traceplotter" / "assets" / "alert_audio"
        if frozen.is_dir():
            return frozen
    return here


def available_sounds() -> list[str]:
    root = alert_audio_dir()
    found = [name for name in ALERT_SOUNDS if (root / name).is_file()]
    return found or list(ALERT_SOUNDS)


def sound_path(filename: str) -> Path | None:
    name = Path(filename).name
    path = alert_audio_dir() / name
    return path if path.is_file() else None


def band_to_event(band: str) -> str | None:
    if band == "green":
        return EVENT_GOOD
    if band == "yellow":
        return EVENT_WARNING
    if band == "red":
        return EVENT_CRITICAL
    if band == "none":
        return EVENT_LOST
    return None


def event_for_latency(ms: float | None) -> str:
    return band_to_event(latency_band(ms)) or EVENT_LOST


@dataclass
class NotificationSettings:
    enabled: bool = False
    on_band_change_only: bool = True
    sound_good: str = DEFAULT_SOUND_GOOD
    sound_warning: str = DEFAULT_SOUND_WARNING
    sound_critical: str = DEFAULT_SOUND_CRITICAL
    sound_lost_packet: str = DEFAULT_SOUND_LOST

    def sound_for_event(self, event: str) -> str:
        return {
            EVENT_GOOD: self.sound_good,
            EVENT_WARNING: self.sound_warning,
            EVENT_CRITICAL: self.sound_critical,
            EVENT_LOST: self.sound_lost_packet,
        }.get(event, self.sound_lost_packet)


class AlertPlayer:
    """Play PingPlotter alert MP3s via macOS ``afplay`` (no QtMultimedia dependency)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_event_by_target: dict[str, str] = {}
        self._proc: subprocess.Popen | None = None

    def reset_target(self, target: str | None = None) -> None:
        with self._lock:
            if target is None:
                self._last_event_by_target.clear()
            else:
                self._last_event_by_target.pop(target, None)

    def observe_latency(
        self,
        target: str,
        latency_ms: float | None,
        settings: NotificationSettings,
        *,
        has_sample: bool,
    ) -> str | None:
        """Evaluate endpoint latency and play when configured. Returns fired event or None."""
        if not settings.enabled or not has_sample:
            return None
        event = event_for_latency(latency_ms)
        with self._lock:
            previous = self._last_event_by_target.get(target)
            self._last_event_by_target[target] = event
        if settings.on_band_change_only and previous == event:
            return None
        if previous is None and settings.on_band_change_only:
            # First sample establishes baseline without an immediate sound.
            return None
        self.play_event(event, settings)
        return event

    def play_event(self, event: str, settings: NotificationSettings) -> bool:
        return self.play_file(settings.sound_for_event(event))

    def play_file(self, filename: str) -> bool:
        path = sound_path(filename)
        if path is None:
            return False
        afplay = shutil.which("afplay")
        if not afplay:
            return False
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
            try:
                self._proc = subprocess.Popen(
                    [afplay, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                self._proc = None
                return False
        return True
