from __future__ import annotations

from traceplotter.ui import ipv4_sort_key, target_sort_key


def test_ipv4_sort_is_numeric_not_lexical() -> None:
    ips = [
        "100.104.163.10",
        "100.104.163.1",
        "100.104.163.9",
        "100.104.163.2",
        "host.example",
    ]
    ordered = sorted(ips, key=ipv4_sort_key)
    assert ordered == [
        "100.104.163.1",
        "100.104.163.2",
        "100.104.163.9",
        "100.104.163.10",
        "host.example",
    ]


def test_hostname_sort_puts_named_first() -> None:
    rows = [
        ("100.104.163.2", ""),
        ("100.104.163.10", "zeta"),
        ("100.104.163.1", "alpha"),
    ]
    ordered = sorted(rows, key=lambda row: target_sort_key(row[0], row[1], "hostname"))
    assert [row[0] for row in ordered] == [
        "100.104.163.1",
        "100.104.163.10",
        "100.104.163.2",
    ]
