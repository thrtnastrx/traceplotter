from __future__ import annotations

import pytest

from traceplotter.engine import ProbeResult, SampleStore
from traceplotter.hostnames import HostnameBook


def test_hostname_book_persists(tmp_path) -> None:
    path = tmp_path / "hostnames.json"
    book = HostnameBook(path)
    book.set("10.1.2.3", "edge-fw.lab")
    reloaded = HostnameBook(path)
    assert reloaded.get("10.1.2.3") == "edge-fw.lab"
    assert reloaded.resolve("10.1.2.3", "ptr.example") == "edge-fw.lab"
    assert reloaded.resolve("10.9.9.9", "ptr.example") == "ptr.example"
    reloaded.clear("10.1.2.3")
    assert reloaded.get("10.1.2.3") is None


def test_manual_hostname_overrides_dns(tmp_path) -> None:
    book = HostnameBook(tmp_path / "names.json")
    book.set("203.0.113.8", "manual-hop")
    store = SampleStore(hostname_lookup=book.resolve)
    store.record("dest", 3, ProbeResult("dest", True, 12.0, "203.0.113.8"), dns="auto.example")
    hop = store.hops("dest")[0]
    assert hop.dns == "manual-hop"
    store.set_hop_hostname("dest", 3, "renamed-hop")
    assert store.hops("dest")[0].dns == "renamed-hop"


def test_hostname_book_rejects_star_ip(tmp_path) -> None:
    book = HostnameBook(tmp_path / "names.json")
    with pytest.raises(ValueError):
        book.set("*", "nowhere")


def test_hostname_book_snapshot_and_merge(tmp_path) -> None:
    book = HostnameBook(tmp_path / "names.json")
    book.set("10.0.0.1", "alpha")
    book.set("10.0.0.2", "beta")
    assert book.snapshot(["10.0.0.1", "10.0.0.9"]) == {"10.0.0.1": "alpha"}
    other = HostnameBook(tmp_path / "other.json")
    changed = other.merge({"10.0.0.1": "alpha", "10.0.0.3": "gamma"})
    assert changed == 2
    assert other.get("10.0.0.3") == "gamma"
