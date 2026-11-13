from __future__ import annotations

from pathlib import Path

from traceplotter.paths import APP_NAME, LEGACY_APP_SUPPORT_NAME, default_app_support_dir


def test_app_support_migrates_legacy(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    support = home / "Library" / "Application Support"
    legacy = support / LEGACY_APP_SUPPORT_NAME
    legacy.mkdir(parents=True)
    (legacy / "traces").mkdir()
    (legacy / "traces" / "sample.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    migrated = default_app_support_dir()
    assert migrated == support / APP_NAME
    assert migrated.exists()
    assert not legacy.exists()
    assert (migrated / "traces" / "sample.json").exists()
