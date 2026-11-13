from __future__ import annotations

from traceplotter.engine import ProbeResult
from traceplotter.scans import LAST_SCAN_ID, ScanLibrary, probe_results_from_saved


def test_save_load_and_last_scan(tmp_path) -> None:
    library = ScanLibrary(tmp_path)
    results = {
        "10.1.0.2": ProbeResult("10.1.0.2", True, 12.5, "10.1.0.2", True),
        "10.1.0.1": ProbeResult("10.1.0.1", False, error="timeout"),
    }
    named = library.save(
        spec="10.1.0.0/24",
        results=results,
        dns_names={"10.1.0.2": "ptr-a.lab"},
        hostnames={"10.1.0.2": "edge-fw"},
        workers=32,
        timeout=0.5,
        name="lab edge",
    )
    last = library.save(
        spec="10.1.0.0/24",
        results=results,
        dns_names={"10.1.0.2": "ptr-a.lab"},
        hostnames={"10.1.0.2": "edge-fw"},
        as_last=True,
    )
    assert last.id == LAST_SCAN_ID
    assert named.name == "lab edge"

    listed = library.list_scans()
    assert {item.id for item in listed} == {named.id, LAST_SCAN_ID}

    loaded = library.load(named.id)
    probes, dns = probe_results_from_saved(loaded)
    assert probes["10.1.0.2"].alive is True
    assert probes["10.1.0.2"].rtt_ms == 12.5
    assert dns["10.1.0.2"] == "edge-fw"
    assert loaded.hostnames["10.1.0.2"] == "edge-fw"
    assert probes["10.1.0.1"].alive is False
