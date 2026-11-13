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
    theme = set_theme("dark")
    assert theme.key == "dark"
    assert current_theme().panel_bg == "#2a3038"
    set_theme("light")
    assert current_theme().key == "light"
