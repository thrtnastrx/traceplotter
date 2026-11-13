from __future__ import annotations

from traceplotter.engine import ProbeResult, SampleStore
from traceplotter.traces import LAST_TRACE_ID, TraceLibrary


def test_trace_round_trip(tmp_path) -> None:
    store = SampleStore()
    store.record("10.0.0.8", 1, ProbeResult("10.0.0.8", True, 4.0, "10.0.0.1"), dns="gw")
    store.record_destination(
        "10.0.0.8",
        "10.0.0.8",
        ProbeResult("10.0.0.8", False, responder="10.0.0.8", error="timeout"),
    )
    store.record_timeline("10.0.0.8", None)
    library = TraceLibrary(tmp_path)
    saved = library.save(
        targets=["10.0.0.8"],
        state=store.export_state(["10.0.0.8"]),
        hostnames={"10.0.0.8": "core-sw"},
        interval=2.0,
        timeout=1.0,
        name="core path",
    )
    last = library.save(
        targets=["10.0.0.8"],
        state=store.export_state(["10.0.0.8"]),
        hostnames={"10.0.0.8": "core-sw"},
        as_last=True,
    )
    assert last.id == LAST_TRACE_ID
    loaded = library.load(saved.id)
    assert loaded.name == "core path"
    assert loaded.hostnames["10.0.0.8"] == "core-sw"
    restored = SampleStore()
    targets = restored.import_state(loaded.state)
    assert targets == ["10.0.0.8"]
    hops = restored.hops("10.0.0.8")
    assert hops[0].ip == "10.0.0.1"
    assert hops[-1].ip == "10.0.0.8"
    assert hops[-1].loss_percent == 100.0
    assert restored.endpoint_up("10.0.0.8") is False


def test_trace_delete(tmp_path) -> None:
    store = SampleStore()
    store.record_timeline("10.0.0.9", 12.0)
    library = TraceLibrary(tmp_path)
    saved = library.save(
        targets=["10.0.0.9"],
        state=store.export_state(["10.0.0.9"]),
        name="to-delete",
    )
    library.save(
        targets=["10.0.0.9"],
        state=store.export_state(["10.0.0.9"]),
        as_last=True,
    )
    assert any(trace.id == saved.id for trace in library.list_traces())
    library.delete(saved.id)
    library.delete(LAST_TRACE_ID)
    ids = {trace.id for trace in library.list_traces()}
    assert saved.id not in ids
    assert LAST_TRACE_ID not in ids
