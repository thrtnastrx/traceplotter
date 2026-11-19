from __future__ import annotations

from traceplotter.theme import Preferences, current_theme, set_theme


def test_theme_switch_and_prefs(tmp_path) -> None:
    path = tmp_path / "preferences.json"
    prefs = Preferences(
        theme="dark",
        hide_unresponsive=True,
        target_sort="hostname",
        show_unresolved=False,
        auto_save_trace=False,
        host_ip_width=160,
        host_hostname_width=180,
        audio_alerts_enabled=True,
        audio_event_lost_packet=True,
        audio_event_good=False,
        audio_alert_targets=["1.1.1.1", "8.8.8.8"],
        band_green_max_ms=60,
        band_yellow_max_ms=120,
    )
    prefs.save(path)
    loaded = Preferences.load(path)
    assert loaded.theme == "dark"
    assert loaded.hide_unresponsive is True
    assert loaded.target_sort == "hostname"
    assert loaded.show_unresolved is False
    assert loaded.auto_save_trace is False
    assert loaded.host_ip_width == 160
    assert loaded.host_hostname_width == 180
    assert loaded.audio_alerts_enabled is True
    assert loaded.audio_event_good is False
    assert loaded.audio_event_lost_packet is True
    assert loaded.audio_alert_targets == ["1.1.1.1", "8.8.8.8"]
    assert loaded.band_green_max_ms == 60
    assert loaded.band_yellow_max_ms == 120
    settings = loaded.notification_settings()
    assert settings.armed_targets == {"1.1.1.1", "8.8.8.8"}
    assert settings.event_good is False
    # Legacy prefs without audio_alert_targets → all targets armed.
    legacy = path.with_name("legacy.json")
    legacy.write_text(
        '{"theme":"light","audio_alerts_enabled":true}\n',
        encoding="utf-8",
    )
    legacy_prefs = Preferences.load(legacy)
    assert legacy_prefs.audio_alert_targets is None
    assert legacy_prefs.notification_settings().target_armed("9.9.9.9") is True
    theme = set_theme("dark")
    assert theme.key == "dark"
    assert current_theme().panel_bg == "#2a3038"
    set_theme("light")
    assert current_theme().key == "light"
