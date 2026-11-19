from __future__ import annotations

from traceplotter.engine import set_band_thresholds
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
    set_band_thresholds(100, 200)
    assert event_for_latency(50) == EVENT_GOOD
    assert event_for_latency(100) == EVENT_GOOD
    assert event_for_latency(101) == EVENT_WARNING
    assert event_for_latency(200) == EVENT_WARNING
    assert event_for_latency(201) == EVENT_CRITICAL
    assert event_for_latency(None) == EVENT_LOST
    assert band_to_event("green") == EVENT_GOOD


def test_band_events_follow_custom_thresholds() -> None:
    set_band_thresholds(50, 80)
    assert event_for_latency(50) == EVENT_GOOD
    assert event_for_latency(51) == EVENT_WARNING
    assert event_for_latency(80) == EVENT_WARNING
    assert event_for_latency(81) == EVENT_CRITICAL
    set_band_thresholds(100, 200)


def test_bundled_pingplotter_alert_sounds_exist() -> None:
    sounds = available_sounds()
    assert "buzzer.mp3" in sounds
    assert "goblet-ping.mp3" in sounds
    assert sound_path("sonar.mp3") is not None


def test_observe_latency_plays_on_band_change_only() -> None:
    player = AlertPlayer()
    played: list[str] = []
    # None = all targets armed.
    settings = NotificationSettings(enabled=True, on_band_change_only=True, armed_targets=None)

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


def test_observe_latency_requires_armed_target_when_selective() -> None:
    player = AlertPlayer()
    played: list[str] = []
    settings = NotificationSettings(enabled=True, armed_targets=set())

    def fake_play(event: str, _settings: NotificationSettings) -> bool:
        played.append(event)
        return True

    player.play_event = fake_play  # type: ignore[method-assign]
    player.observe_latency("8.8.8.8", 40.0, settings, has_sample=True)
    player.observe_latency("8.8.8.8", 150.0, settings, has_sample=True)
    assert played == []


def test_lost_packet_alerts_on_first_sample() -> None:
    player = AlertPlayer()
    played: list[str] = []
    settings = NotificationSettings(enabled=True, on_band_change_only=True, armed_targets=None)

    def fake_play(event: str, _settings: NotificationSettings) -> bool:
        played.append(event)
        return True

    player.play_event = fake_play  # type: ignore[method-assign]
    assert player.observe_latency("1.1.1.1", None, settings, has_sample=True) == EVENT_LOST
    assert played == [EVENT_LOST]


def test_observe_latency_respects_per_event_toggles() -> None:
    player = AlertPlayer()
    played: list[str] = []
    settings = NotificationSettings(
        enabled=True,
        on_band_change_only=True,
        event_warning=False,
        event_lost_packet=True,
        armed_targets={"1.1.1.1"},
    )

    def fake_play(event: str, _settings: NotificationSettings) -> bool:
        played.append(event)
        return True

    player.play_event = fake_play  # type: ignore[method-assign]
    player.observe_latency("1.1.1.1", 40.0, settings, has_sample=True)
    assert player.observe_latency("1.1.1.1", 150.0, settings, has_sample=True) is None
    assert played == []
    assert player.observe_latency("1.1.1.1", None, settings, has_sample=True) == EVENT_LOST
    assert played == [EVENT_LOST]
