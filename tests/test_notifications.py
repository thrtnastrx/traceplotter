from __future__ import annotations

from traceplotter.notifications import (
    EVENT_CRITICAL,
    EVENT_GOOD,
    EVENT_LOST,
    EVENT_WARNING,
    NotificationSettings,
    AlertPlayer,
    available_sounds,
    band_to_event,
    event_for_latency,
    sound_path,
)


def test_band_events_match_pingplotter_latency_bands() -> None:
    assert event_for_latency(50) == EVENT_GOOD
    assert event_for_latency(100) == EVENT_GOOD
    assert event_for_latency(101) == EVENT_WARNING
    assert event_for_latency(200) == EVENT_WARNING
    assert event_for_latency(201) == EVENT_CRITICAL
    assert event_for_latency(None) == EVENT_LOST
    assert band_to_event("green") == EVENT_GOOD


def test_bundled_pingplotter_alert_sounds_exist() -> None:
    sounds = available_sounds()
    assert "buzzer.mp3" in sounds
    assert "goblet-ping.mp3" in sounds
    assert sound_path("sonar.mp3") is not None


def test_observe_latency_plays_on_band_change_only() -> None:
    player = AlertPlayer()
    played: list[str] = []
    settings = NotificationSettings(enabled=True, on_band_change_only=True)

    def fake_play(event: str, _settings: NotificationSettings) -> bool:
        played.append(event)
        return True

    player.play_event = fake_play  # type: ignore[method-assign]
    assert player.observe_latency("1.1.1.1", 40.0, settings, has_sample=True) is None
    assert played == []
    assert player.observe_latency("1.1.1.1", 45.0, settings, has_sample=True) is None
    assert player.observe_latency("1.1.1.1", 150.0, settings, has_sample=True) == EVENT_WARNING
    assert played == [EVENT_WARNING]
    assert player.observe_latency("1.1.1.1", None, settings, has_sample=True) == EVENT_LOST
    assert played == [EVENT_WARNING, EVENT_LOST]
