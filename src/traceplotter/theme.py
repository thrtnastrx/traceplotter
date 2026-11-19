"""Light/dark theme palettes and app preferences."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor


def default_prefs_path() -> Path:
    from .paths import default_app_support_dir

    return default_app_support_dir() / "preferences.json"


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    window_bg: str
    panel_bg: str
    text: str
    muted: str
    border: str
    chip_bg: str
    chip_hover: str
    banner_bg: str
    table_bg: str
    table_alt: str
    header_bg: str
    grid: str
    up: str
    down: str
    panel: QColor
    text_color: QColor
    grid_color: QColor
    green_soft: QColor
    yellow_soft: QColor
    red_soft: QColor
    outage: QColor

    @property
    def stylesheet(self) -> str:
        return f"""
            QMainWindow, QDialog, QWidget {{
                background: {self.window_bg};
                color: {self.text};
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QPlainTextEdit {{
                background: {self.panel_bg};
                color: {self.text};
                border: 1px solid {self.border};
                selection-background-color: #3d6ea8;
            }}
            QPushButton, QToolButton {{
                background: {self.chip_bg};
                color: {self.text};
                border: 1px solid {self.border};
                padding: 4px 10px;
                border-radius: 4px;
            }}
            QPushButton:hover, QToolButton:hover {{
                border-color: {self.chip_hover};
            }}
            QHeaderView::section {{
                background: {self.header_bg};
                color: {self.text};
                padding: 4px;
                border: 1px solid {self.border};
            }}
            #hostTargets QHeaderView::section,
            #hostTargetsHeader::section {{
                padding: 2px 4px;
                margin: 0px;
                min-height: 20px;
                max-height: 24px;
                font-size: 11px;
                color: {self.muted};
                border-top: none;
                border-left: none;
                border-right: 1px solid {self.border};
                border-bottom: 1px solid {self.border};
            }}
            QTableWidget {{
                background: {self.table_bg};
                alternate-background-color: {self.table_alt};
                gridline-color: {self.grid};
                color: {self.text};
            }}
            QMenu {{
                background: {self.panel_bg};
                color: {self.text};
                border: 1px solid {self.border};
            }}
            QCheckBox {{ color: {self.text}; }}
            QStatusBar {{ color: {self.muted}; }}
            #toolbarChip {{
                background: {self.chip_bg};
                border: 1px solid {self.border};
                border-radius: 4px;
            }}
            #toolbarChip:hover {{ border-color: {self.chip_hover}; }}
            #toolbarChipFlat {{
                background: transparent;
                border: none;
            }}
            #bannerRow {{
                background: transparent;
                border: none;
            }}
            #bannerRowEdit {{
                background: {self.banner_bg};
                border: 1px dashed {self.border};
                border-radius: 4px;
            }}
            #latencyLegend {{
                background: {self.panel_bg};
                border: 1px solid {self.border};
            }}
            #toolbarGrip {{
                color: {self.muted};
            }}
            #paneHeader {{
                background: {self.banner_bg};
                border-bottom: 1px solid {self.border};
            }}
            #paneShell {{
                background: {self.panel_bg};
                border: 1px solid {self.border};
            }}
        """


LIGHT = Theme(
    key="light",
    label="Light",
    window_bg="#f4f6f8",
    panel_bg="#ffffff",
    text="#2b3642",
    muted="#7a8794",
    border="#d5dbe3",
    chip_bg="#ffffff",
    chip_hover="#9aa8b8",
    banner_bg="#eef2f6",
    table_bg="#ffffff",
    table_alt="#f7f9fb",
    header_bg="#eef2f6",
    grid="#e4e9ef",
    up="#18864b",
    down="#c62828",
    panel=QColor("#ffffff"),
    text_color=QColor("#2b3642"),
    grid_color=QColor("#d5dbe3"),
    green_soft=QColor(122, 201, 67, 70),
    yellow_soft=QColor(245, 197, 66, 55),
    red_soft=QColor(232, 93, 93, 45),
    outage=QColor(220, 50, 47, 200),
)

DARK = Theme(
    key="dark",
    label="Dark",
    window_bg="#1e2228",
    panel_bg="#2a3038",
    text="#e6ebf0",
    muted="#9aa5b1",
    border="#3d4654",
    chip_bg="#323a45",
    chip_hover="#6b7a8d",
    banner_bg="#252b33",
    table_bg="#2a3038",
    table_alt="#232830",
    header_bg="#323a45",
    grid="#3d4654",
    up="#5dce8a",
    down="#ff6b6b",
    panel=QColor("#2a3038"),
    text_color=QColor("#e6ebf0"),
    grid_color=QColor("#3d4654"),
    green_soft=QColor(122, 201, 67, 55),
    yellow_soft=QColor(245, 197, 66, 45),
    red_soft=QColor(232, 93, 93, 40),
    outage=QColor(200, 60, 55, 210),
)

THEMES = {LIGHT.key: LIGHT, DARK.key: DARK}

_current = LIGHT


def current_theme() -> Theme:
    return _current


def set_theme(key: str) -> Theme:
    global _current
    _current = THEMES.get(key, LIGHT)
    return _current


@dataclass
class Preferences:
    theme: str = "light"
    hide_unresponsive: bool = False
    target_sort: str = "ip"  # "ip" | "hostname" | "manual"
    show_unresolved: bool = True
    auto_save_trace: bool = True
    host_ip_width: int = 140
    host_hostname_width: int = 120
    host_ports_width: int = 100
    # Time-graph / alert latency bands (ms). Red is anything above yellow_max.
    band_green_max_ms: float = 100.0
    band_yellow_max_ms: float = 200.0
    # PingPlotter-style PlayAudioAlerts
    audio_alerts_enabled: bool = False
    audio_on_band_change_only: bool = True
    audio_event_good: bool = True
    audio_event_warning: bool = True
    audio_event_critical: bool = True
    audio_event_lost_packet: bool = True
    audio_file_good: str = "goblet-ping.mp3"
    audio_file_warning: str = "sonar.mp3"
    audio_file_critical: str = "dark-church-bell.mp3"
    audio_file_lost_packet: str = "buzzer.mp3"
    # None = all targets; [] = none; otherwise only listed keys.
    audio_alert_targets: list[str] | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> Preferences:
        path = path or default_prefs_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return cls()
        theme = str(data.get("theme") or "light")
        if theme not in THEMES:
            theme = "light"
        sort = str(data.get("target_sort") or "ip")
        if sort not in ("ip", "hostname", "manual"):
            sort = "ip"
        ip_width = int(data.get("host_ip_width") or 140)
        hostname_width = int(data.get("host_hostname_width") or 120)
        ports_width = int(data.get("host_ports_width") or 100)
        defaults = cls()
        green_max = float(data.get("band_green_max_ms", defaults.band_green_max_ms))
        yellow_max = float(data.get("band_yellow_max_ms", defaults.band_yellow_max_ms))
        if green_max < 1:
            green_max = defaults.band_green_max_ms
        if yellow_max <= green_max:
            yellow_max = green_max + max(1.0, defaults.band_yellow_max_ms - defaults.band_green_max_ms)
        # Missing key → all targets (legacy / master-only config).
        # Explicit null → all. Explicit list (including empty) → that selection.
        if "audio_alert_targets" not in data or data.get("audio_alert_targets") is None:
            audio_targets: list[str] | None = None
        elif isinstance(data.get("audio_alert_targets"), list):
            audio_targets = [
                str(item).strip()
                for item in data["audio_alert_targets"]
                if str(item).strip()
            ]
        else:
            audio_targets = None
        return cls(
            theme=theme,
            hide_unresponsive=bool(data.get("hide_unresponsive", False)),
            target_sort=sort,
            show_unresolved=bool(data.get("show_unresolved", True)),
            auto_save_trace=bool(data.get("auto_save_trace", True)),
            host_ip_width=max(60, ip_width),
            host_hostname_width=max(60, hostname_width),
            host_ports_width=max(60, ports_width),
            band_green_max_ms=green_max,
            band_yellow_max_ms=yellow_max,
            audio_alerts_enabled=bool(data.get("audio_alerts_enabled", False)),
            audio_on_band_change_only=bool(data.get("audio_on_band_change_only", True)),
            audio_event_good=bool(data.get("audio_event_good", True)),
            audio_event_warning=bool(data.get("audio_event_warning", True)),
            audio_event_critical=bool(data.get("audio_event_critical", True)),
            audio_event_lost_packet=bool(data.get("audio_event_lost_packet", True)),
            audio_file_good=str(data.get("audio_file_good") or defaults.audio_file_good),
            audio_file_warning=str(data.get("audio_file_warning") or defaults.audio_file_warning),
            audio_file_critical=str(data.get("audio_file_critical") or defaults.audio_file_critical),
            audio_file_lost_packet=str(
                data.get("audio_file_lost_packet") or defaults.audio_file_lost_packet
            ),
            audio_alert_targets=audio_targets,
        )

    def save(self, path: Path | None = None) -> None:
        path = path or default_prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        targets = self.audio_alert_targets
        path.write_text(
            json.dumps(
                {
                    "theme": self.theme,
                    "hide_unresponsive": self.hide_unresponsive,
                    "target_sort": self.target_sort,
                    "show_unresolved": self.show_unresolved,
                    "auto_save_trace": self.auto_save_trace,
                    "host_ip_width": self.host_ip_width,
                    "host_hostname_width": self.host_hostname_width,
                    "host_ports_width": self.host_ports_width,
                    "band_green_max_ms": self.band_green_max_ms,
                    "band_yellow_max_ms": self.band_yellow_max_ms,
                    "audio_alerts_enabled": self.audio_alerts_enabled,
                    "audio_on_band_change_only": self.audio_on_band_change_only,
                    "audio_event_good": self.audio_event_good,
                    "audio_event_warning": self.audio_event_warning,
                    "audio_event_critical": self.audio_event_critical,
                    "audio_event_lost_packet": self.audio_event_lost_packet,
                    "audio_file_good": self.audio_file_good,
                    "audio_file_warning": self.audio_file_warning,
                    "audio_file_critical": self.audio_file_critical,
                    "audio_file_lost_packet": self.audio_file_lost_packet,
                    "audio_alert_targets": (
                        None if targets is None else sorted(targets)
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def notification_settings(self):
        from .notifications import NotificationSettings

        targets = self.audio_alert_targets
        return NotificationSettings(
            enabled=self.audio_alerts_enabled,
            on_band_change_only=self.audio_on_band_change_only,
            event_good=self.audio_event_good,
            event_warning=self.audio_event_warning,
            event_critical=self.audio_event_critical,
            event_lost_packet=self.audio_event_lost_packet,
            sound_good=self.audio_file_good,
            sound_warning=self.audio_file_warning,
            sound_critical=self.audio_file_critical,
            sound_lost_packet=self.audio_file_lost_packet,
            armed_targets=None if targets is None else set(targets),
        )


