from __future__ import annotations

from datetime import datetime, timedelta

from traceplotter.ui import clamp_timeline_view_end


def test_clamp_cannot_go_past_now() -> None:
    now = datetime(2026, 11, 12, 15, 0, 0)
    earliest = now - timedelta(hours=2)
    end = clamp_timeline_view_end(
        now + timedelta(minutes=5),
        now=now,
        window_seconds=15 * 60,
        earliest=earliest,
    )
    assert end == now


def test_clamp_stops_at_oldest_window() -> None:
    now = datetime(2026, 11, 12, 15, 0, 0)
    earliest = now - timedelta(hours=2)
    window = 15 * 60
    end = clamp_timeline_view_end(
        earliest,
        now=now,
        window_seconds=window,
        earliest=earliest,
    )
    assert end == earliest + timedelta(seconds=window)


def test_clamp_stays_live_when_history_shorter_than_window() -> None:
    now = datetime(2026, 11, 12, 15, 0, 0)
    earliest = now - timedelta(minutes=2)
    end = clamp_timeline_view_end(
        earliest,
        now=now,
        window_seconds=15 * 60,
        earliest=earliest,
    )
    assert end == now
