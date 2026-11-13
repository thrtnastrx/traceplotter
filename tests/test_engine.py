from __future__ import annotations

import threading

import pytest

import traceplotter.engine as engine
from datetime import datetime, timedelta

from traceplotter.engine import (
    ProbeResult,
    SampleStore,
    SubnetSweeper,
    TimelinePoint,
    expand_ipv4_spec,
    loss_percent,
    parse_ping_output,
    parse_traceroute_output,
)


def test_expand_cidr_omits_network_and_broadcast() -> None:
    hosts = expand_ipv4_spec("10.50.0.42/24")
    assert len(hosts) == 254
    assert hosts[0] == "10.50.0.1"
    assert hosts[-1] == "10.50.0.254"


def test_expand_range_is_inclusive() -> None:
    assert expand_ipv4_spec("192.0.2.5-192.0.2.7") == [
        "192.0.2.5",
        "192.0.2.6",
        "192.0.2.7",
    ]


def test_scan_cap_allows_22_and_rejects_larger() -> None:
    assert len(expand_ipv4_spec("10.0.0.0/22")) == 1022
    with pytest.raises(ValueError, match="maximum"):
        expand_ipv4_spec("10.0.0.0/21")


@pytest.mark.parametrize(
    ("sent", "received", "expected"),
    [(0, 0, 0.0), (10, 10, 0.0), (10, 7, 30.0), (4, 0, 100.0), (3, 5, 0.0)],
)
def test_loss_math(sent: int, received: int, expected: float) -> None:
    assert loss_percent(sent, received) == expected


def test_parse_successful_ping() -> None:
    output = "64 bytes from 192.0.2.4: icmp_seq=0 ttl=61 time=12.345 ms"
    result = parse_ping_output("192.0.2.4", output, 0)
    assert result.alive
    assert result.reached_target
    assert result.rtt_ms == 12.345
    assert result.responder == "192.0.2.4"


def test_parse_ttl_expiry() -> None:
    # macOS dumps Src/Dst after the hop IP — parser must use "bytes from".
    output = (
        "PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
        "72 bytes from 10.57.18.1: Time to live exceeded\n"
        "Vr HL TOS  Len   ID Flg  off TTL Pro  cks      Src      Dst\n"
        " 4  5  00 5400 b033   0 0000  01  01 ebfd 10.57.3.48  8.8.8.8\n"
    )
    result = parse_ping_output("8.8.8.8", output, 2, measured_rtt_ms=18.4)
    assert result.alive
    assert not result.reached_target
    assert result.responder == "10.57.18.1"
    assert result.rtt_ms == 18.4


def test_parse_traceroute_hops() -> None:
    output = (
        "traceroute to 8.8.8.8 (8.8.8.8), 12 hops max, 40 byte packets\n"
        " 1  10.57.18.1  14.819 ms\n"
        " 2  242.2.18.67  18.690 ms\n"
        " 3  *\n"
        " 4  8.8.8.8  21.540 ms\n"
    )
    rows = parse_traceroute_output("8.8.8.8", output)
    assert [hop for hop, _ in rows] == [1, 2, 3, 4]
    assert rows[0][1].responder == "10.57.18.1"
    assert rows[0][1].rtt_ms == 14.819
    assert not rows[2][1].alive
    assert rows[3][1].reached_target


def test_parse_traceroute_hostname_dest_uses_resolved_ips() -> None:
    output = (
        "traceroute to github.com (140.82.113.4), 12 hops max, 40 byte packets\n"
        " 1  10.0.0.1  1.0 ms\n"
        " 2  140.82.113.4  20.0 ms\n"
    )
    rows = parse_traceroute_output("github.com", output, dest_ips={"140.82.113.4"})
    assert rows[1][1].reached_target
    assert rows[1][1].responder == "140.82.113.4"


def test_sample_store_accumulates_statistics() -> None:
    store = SampleStore()
    store.record("example.test", 1, ProbeResult("example.test", True, 10.0, "10.0.0.1"))
    store.record("example.test", 1, ProbeResult("example.test", False, responder="10.0.0.1"))
    hop = store.hops("example.test")[0]
    assert hop.sent == 2
    assert hop.received == 1
    assert hop.avg_ms == 10.0
    assert hop.loss_percent == 50.0
    assert hop.resolved is True


def test_unresolved_hop_has_star_ip() -> None:
    store = SampleStore()
    store.record("dest", 2, ProbeResult("dest", False, error="timeout"))
    hop = store.hops("dest")[0]
    assert hop.ip == "*"
    assert hop.resolved is False


def test_timeline_marks_outage_and_recovery() -> None:
    store = SampleStore()
    store.record_timeline("10.0.0.5", 20.0)
    store.record_timeline("10.0.0.5", None)
    store.record_timeline("10.0.0.5", 22.0)
    points = store.timeline("10.0.0.5")
    assert points[0].latency_ms == 20.0 and points[0].loss_percent == 0.0
    assert points[1].latency_ms is None and points[1].loss_percent == 100.0
    assert points[2].latency_ms == 22.0
    assert store.endpoint_up("10.0.0.5") is True
    store.record_timeline("10.0.0.5", None)
    assert store.endpoint_up("10.0.0.5") is False


def test_destination_hop_recorded_when_unreachable() -> None:
    store = SampleStore()
    store.record("10.0.0.50", 1, ProbeResult("10.0.0.50", True, 5.0, "10.0.0.1"))
    store.record("10.0.0.50", 2, ProbeResult("10.0.0.50", True, 8.0, "10.0.0.2"))
    store.record_destination(
        "10.0.0.50",
        "10.0.0.50",
        ProbeResult("10.0.0.50", False, responder="10.0.0.50", error="timeout"),
    )
    hops = store.hops("10.0.0.50")
    assert [hop.ip for hop in hops] == ["10.0.0.1", "10.0.0.2", "10.0.0.50"]
    dest = hops[-1]
    assert dest.resolved is True
    assert dest.received == 0
    assert dest.loss_percent == 100.0
    # Stable hop identity across later misses.
    store.record_destination(
        "10.0.0.50",
        "10.0.0.50",
        ProbeResult("10.0.0.50", False, responder="10.0.0.50", error="timeout"),
    )
    assert len(store.hops("10.0.0.50")) == 3
    assert store.hops("10.0.0.50")[-1].sent == 2


def test_timeline_window_filters_old_samples() -> None:
    store = SampleStore()
    now = datetime.now()
    store._timeline["host"] = [
        TimelinePoint(now - timedelta(minutes=20), 10.0, 0.0),
        TimelinePoint(now - timedelta(minutes=2), 12.0, 0.0),
        TimelinePoint(now - timedelta(seconds=5), None, 100.0),
    ]
    recent = store.timeline("host", window_seconds=5 * 60)
    assert len(recent) == 2
    assert recent[0].latency_ms == 12.0
    assert recent[1].latency_ms is None


def test_endpoint_falls_back_to_ping_when_traceroute_misses_dest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SampleStore()
    tracer = engine.ContinuousTracer("9.9.9.9", store, interval=60.0, timeout=0.5)

    def fake_trace() -> list[tuple[int, engine.ProbeResult]]:
        return [
            (1, ProbeResult("9.9.9.9", True, 5.0, "10.0.0.1")),
            (2, ProbeResult("9.9.9.9", True, 8.0, "10.0.0.2")),
            (3, ProbeResult("9.9.9.9", False, error="timeout")),
        ]

    def fake_ping(host: str, timeout: float) -> ProbeResult:
        del timeout
        assert host == "9.9.9.9"
        return ProbeResult(host, True, 16.0, host, reached_target=True)

    monkeypatch.setattr(tracer, "_run_traceroute", fake_trace)
    monkeypatch.setattr(engine, "ping_once", fake_ping)
    latency = tracer._sample()
    assert latency == 16.0
    dest = store.hops("9.9.9.9")[-1]
    assert dest.ip == "9.9.9.9"
    assert dest.received >= 1
    assert dest.last_ms == 16.0


def test_sweeper_returns_sorted_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_ping(host: str, timeout: float) -> ProbeResult:
        del timeout
        return ProbeResult(host, host.endswith(".2"), 2.0 if host.endswith(".2") else None, host)

    monkeypatch.setattr(engine, "ping_once", fake_ping)
    seen: list[str] = []
    results = SubnetSweeper(workers=2).sweep(
        ["192.0.2.2", "192.0.2.1"], lambda result: seen.append(result.host), threading.Event()
    )
    assert [item.host for item in results] == ["192.0.2.1", "192.0.2.2"]
    assert set(seen) == {"192.0.2.1", "192.0.2.2"}
