"""Unprivileged macOS probing, route sampling, subnet expansion, and storage."""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

PING = "/sbin/ping"
TRACEROUTE = "/usr/sbin/traceroute"
FROM_IP_RE = re.compile(r"bytes from ([0-9.]+):", re.IGNORECASE)
RTT_RE = re.compile(r"time[=<]?\s*([0-9.]+)\s*ms", re.IGNORECASE)
TRACE_LINE_RE = re.compile(r"^\s*(\d+)\s+(.*?)$")


@dataclass(frozen=True)
class ProbeResult:
    host: str
    alive: bool
    rtt_ms: float | None = None
    responder: str | None = None
    reached_target: bool = False
    error: str | None = None


@dataclass
class HopStats:
    hop: int
    ip: str = "*"
    dns: str = ""
    sent: int = 0
    received: int = 0
    last_ms: float | None = None
    total_ms: float = 0.0
    min_ms: float | None = None
    max_ms: float | None = None

    @property
    def loss_percent(self) -> float:
        return loss_percent(self.sent, self.received)

    @property
    def avg_ms(self) -> float | None:
        return self.total_ms / self.received if self.received else None

    @property
    def resolved(self) -> bool:
        """True once this hop has returned a real IP (not `*`)."""
        return bool(self.ip) and self.ip != "*"

    def add(self, result: ProbeResult, dns: str = "") -> None:
        self.sent += 1
        if result.responder:
            self.ip = result.responder
        if dns:
            self.dns = dns
        if result.alive:
            self.received += 1
            self.last_ms = result.rtt_ms
            if result.rtt_ms is not None:
                self.total_ms += result.rtt_ms
                self.min_ms = result.rtt_ms if self.min_ms is None else min(self.min_ms, result.rtt_ms)
                self.max_ms = result.rtt_ms if self.max_ms is None else max(self.max_ms, result.rtt_ms)
        else:
            self.last_ms = None


@dataclass(frozen=True)
class TimelinePoint:
    timestamp: datetime
    latency_ms: float | None
    loss_percent: float


def loss_percent(sent: int, received: int) -> float:
    if sent <= 0:
        return 0.0
    received = min(max(received, 0), sent)
    return (sent - received) * 100.0 / sent


def latency_band(ms: float | None) -> str:
    """PingPlotter-style bands: green 0-100, yellow 101-200, red 201+."""
    if ms is None:
        return "none"
    if ms <= 100:
        return "green"
    if ms <= 200:
        return "yellow"
    return "red"


# Longest selectable graph window, plus a small buffer for clock skew.
TIMELINE_RETENTION_SECONDS = 3 * 3600 + 120

TIME_WINDOW_CHOICES: tuple[tuple[str, int], ...] = (
    ("3 hours", 3 * 3600),
    ("1 hour", 3600),
    ("30 min", 30 * 60),
    ("15 min", 15 * 60),
    ("5 min", 5 * 60),
    ("1 min", 60),
)


class SampleStore:
    """Thread-safe rolling statistics for all targets."""

    def __init__(
        self,
        timeline_retention_seconds: float = TIMELINE_RETENTION_SECONDS,
        hostname_lookup: Callable[[str, str], str] | None = None,
    ) -> None:
        self.timeline_retention_seconds = timeline_retention_seconds
        self.hostname_lookup = hostname_lookup
        self._hops: dict[str, dict[int, HopStats]] = {}
        self._timeline: dict[str, list[TimelinePoint]] = {}
        self._lock = threading.RLock()

    def record(self, target: str, hop: int, result: ProbeResult, dns: str = "") -> None:
        with self._lock:
            stats = self._hops.setdefault(target, {}).setdefault(hop, HopStats(hop))
            ip = result.responder or stats.ip
            label = self.hostname_lookup(ip, dns) if self.hostname_lookup else dns
            stats.add(result, label)

    def record_destination(
        self,
        target: str,
        target_ip: str,
        result: ProbeResult,
        dns: str = "",
    ) -> None:
        """Always keep a final hop row for the scanned destination IP."""
        with self._lock:
            hops = self._hops.setdefault(target, {})
            dest_ids = {target, target_ip}
            hop_num = next(
                (num for num, stats in hops.items() if stats.ip in dest_ids),
                None,
            )
            if hop_num is None:
                hop_num = max(hops, default=0) + 1
            responder = result.responder or target_ip
            labeled = ProbeResult(
                host=result.host,
                alive=result.alive,
                rtt_ms=result.rtt_ms,
                responder=responder,
                reached_target=result.reached_target or result.alive,
                error=result.error,
            )
            stats = hops.setdefault(hop_num, HopStats(hop_num))
            label = self.hostname_lookup(responder, dns) if self.hostname_lookup else dns
            stats.add(labeled, label)

    def set_hop_hostname(self, target: str, hop: int, hostname: str) -> str | None:
        """Set displayed hostname for a hop; returns the hop IP when updated."""
        with self._lock:
            stats = self._hops.get(target, {}).get(hop)
            if stats is None or not stats.resolved:
                return None
            stats.dns = hostname.strip()
            return stats.ip

    def record_timeline(self, target: str, latency_ms: float | None) -> None:
        with self._lock:
            # Endpoint sample: None latency means the target did not answer this round.
            loss = 100.0 if latency_ms is None else 0.0
            points = self._timeline.setdefault(target, [])
            points.append(TimelinePoint(datetime.now(), latency_ms, loss))
            cutoff = datetime.now() - timedelta(seconds=self.timeline_retention_seconds)
            while points and points[0].timestamp < cutoff:
                points.pop(0)

    def hops(self, target: str) -> list[HopStats]:
        with self._lock:
            return [HopStats(**vars(item)) for _, item in sorted(self._hops.get(target, {}).items())]

    def timeline(self, target: str, window_seconds: float | None = None) -> list[TimelinePoint]:
        with self._lock:
            points = list(self._timeline.get(target, ()))
        if not points or window_seconds is None:
            return points
        end = datetime.now()
        start = end - timedelta(seconds=window_seconds)
        return [point for point in points if point.timestamp >= start]

    def endpoint_up(self, target: str) -> bool | None:
        """Latest destination reachability: True/False, or None if no samples yet."""
        with self._lock:
            points = self._timeline.get(target) or []
            if not points:
                return None
            return points[-1].latency_ms is not None

    def reset(self, target: str | None = None) -> None:
        with self._lock:
            if target is None:
                self._hops.clear()
                self._timeline.clear()
            else:
                self._hops.pop(target, None)
                self._timeline.pop(target, None)

    def targets(self) -> list[str]:
        with self._lock:
            keys = set(self._hops) | set(self._timeline)
            return sorted(keys)

    def export_state(self, targets: Iterable[str] | None = None) -> dict[str, dict]:
        """Serialize hop + timeline state for selected targets (or all)."""
        with self._lock:
            wanted = list(targets) if targets is not None else sorted(set(self._hops) | set(self._timeline))
            payload: dict[str, dict] = {}
            for target in wanted:
                hops = [
                    {
                        "hop": stats.hop,
                        "ip": stats.ip,
                        "dns": stats.dns,
                        "sent": stats.sent,
                        "received": stats.received,
                        "last_ms": stats.last_ms,
                        "total_ms": stats.total_ms,
                        "min_ms": stats.min_ms,
                        "max_ms": stats.max_ms,
                    }
                    for _, stats in sorted(self._hops.get(target, {}).items())
                ]
                timeline = [
                    {
                        "timestamp": point.timestamp.isoformat(timespec="seconds"),
                        "latency_ms": point.latency_ms,
                        "loss_percent": point.loss_percent,
                    }
                    for point in self._timeline.get(target, ())
                ]
                payload[target] = {"hops": hops, "timeline": timeline}
            return payload

    def import_state(self, payload: dict[str, dict]) -> list[str]:
        """Replace store contents with a previously exported session."""
        with self._lock:
            self._hops.clear()
            self._timeline.clear()
            loaded: list[str] = []
            for target, body in payload.items():
                target = str(target).strip()
                if not target or not isinstance(body, dict):
                    continue
                hop_map: dict[int, HopStats] = {}
                for row in body.get("hops") or []:
                    hop = int(row.get("hop") or 0)
                    if hop <= 0:
                        continue
                    hop_map[hop] = HopStats(
                        hop=hop,
                        ip=str(row.get("ip") or "*"),
                        dns=str(row.get("dns") or ""),
                        sent=int(row.get("sent") or 0),
                        received=int(row.get("received") or 0),
                        last_ms=row.get("last_ms"),
                        total_ms=float(row.get("total_ms") or 0.0),
                        min_ms=row.get("min_ms"),
                        max_ms=row.get("max_ms"),
                    )
                points: list[TimelinePoint] = []
                for row in body.get("timeline") or []:
                    try:
                        stamp = datetime.fromisoformat(str(row.get("timestamp")))
                    except ValueError:
                        continue
                    points.append(
                        TimelinePoint(
                            stamp,
                            row.get("latency_ms"),
                            float(row.get("loss_percent") or 0.0),
                        )
                    )
                if hop_map or points:
                    self._hops[target] = hop_map
                    self._timeline[target] = points
                    loaded.append(target)
            return loaded


def parse_ping_output(
    host: str,
    output: str,
    returncode: int = 0,
    measured_rtt_ms: float | None = None,
) -> ProbeResult:
    from_match = FROM_IP_RE.search(output)
    responder = from_match.group(1) if from_match else None
    ttl_expired = "time to live exceeded" in output.lower() or "ttl expired" in output.lower()
    rtt_match = RTT_RE.search(output)
    rtt = float(rtt_match.group(1)) if rtt_match else measured_rtt_ms
    echo_ok = returncode == 0 and not ttl_expired and "bytes from" in output.lower()
    alive = bool(responder) and (ttl_expired or echo_ok or rtt is not None)
    if echo_ok and responder is None:
        responder = host
        alive = True
    return ProbeResult(
        host=host,
        alive=alive,
        rtt_ms=rtt if alive else None,
        responder=responder,
        reached_target=echo_ok,
        error=None if alive else "timeout",
    )


def ping_once(host: str, timeout: float = 1.0, ttl: int | None = None) -> ProbeResult:
    """Echo ping (subnet scan / final hop). Prefer traceroute_once for path hops.

    macOS `/sbin/ping -m TTL` reports TTL-exceeded hops, but waits ~1s+ after the
    reply, so wall-clock RTT is unusable for intermediate hops.
    """
    wait_ms = max(200, int(timeout * 1000))
    args = [PING, "-n", "-c", "1", "-W", str(wait_ms)]
    if ttl is not None:
        args.extend(["-m", str(ttl)])
    args.append(host)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout + 1.5,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ProbeResult(host, False, error=str(exc))
    measured = (time.monotonic() - started) * 1000.0
    return parse_ping_output(host, f"{proc.stdout}\n{proc.stderr}", proc.returncode, measured)


def parse_traceroute_output(host: str, output: str) -> list[tuple[int, ProbeResult]]:
    """Parse `traceroute -n` lines into (hop, ProbeResult) pairs."""
    rows: list[tuple[int, ProbeResult]] = []
    for raw in output.splitlines():
        match = TRACE_LINE_RE.match(raw)
        if not match:
            continue
        hop = int(match.group(1))
        rest = match.group(2).strip()
        if not rest or rest.startswith("*"):
            rows.append((hop, ProbeResult(host, False, error="timeout")))
            continue
        ip_match = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", rest)
        rtt_match = re.search(r"([0-9.]+)\s*ms", rest)
        if not ip_match or not rtt_match:
            rows.append((hop, ProbeResult(host, False, error="timeout")))
            continue
        ip = ip_match.group(1)
        rows.append(
            (
                hop,
                ProbeResult(
                    host=host,
                    alive=True,
                    rtt_ms=float(rtt_match.group(1)),
                    responder=ip,
                    reached_target=(ip == host),
                ),
            )
        )
    return rows


def traceroute_once(host: str, timeout: float = 1.0, max_hops: int = 30) -> list[ProbeResult]:
    """One unprivileged traceroute pass with real per-hop RTTs (macOS)."""
    wait_s = max(1, int(round(timeout)))
    args = [
        TRACEROUTE,
        "-n",
        "-q",
        "1",
        "-w",
        str(wait_s),
        "-m",
        str(max_hops),
        host,
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=max(8.0, timeout * max_hops + 2.0),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [ProbeResult(host, False, error=str(exc))]
    return [
        result
        for _, result in parse_traceroute_output(host, f"{proc.stdout}\n{proc.stderr}")
    ]


def reverse_dns(ip: str) -> str:
    if not ip or ip == "*":
        return ""
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror):
        return ""


def expand_ipv4_spec(spec: str, maximum: int = 1022) -> list[str]:
    """Expand an IPv4 CIDR, one address, or inclusive `start-end` range."""
    value = spec.strip()
    if not value:
        raise ValueError("Enter an IPv4 CIDR or range.")
    if "-" in value:
        start_text, end_text = (part.strip() for part in value.split("-", 1))
        start, end = ipaddress.IPv4Address(start_text), ipaddress.IPv4Address(end_text)
        count = int(end) - int(start) + 1
        if count <= 0:
            raise ValueError("Range end must not precede range start.")
        if count > maximum:
            raise ValueError(f"Range has {count} hosts; maximum is {maximum}.")
        return [str(ipaddress.IPv4Address(int(start) + offset)) for offset in range(count)]
    network = ipaddress.ip_network(value, strict=False)
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 scans are supported.")
    hosts = [str(item) for item in network.hosts()]
    if len(hosts) > maximum:
        raise ValueError(f"Network has {len(hosts)} hosts; maximum is {maximum}.")
    return hosts


def local_subnet_suggestion() -> str:
    try:
        address = subprocess.check_output(
            ["/usr/sbin/ipconfig", "getifaddr", "en0"], text=True, timeout=1
        ).strip()
        return str(ipaddress.ip_network(f"{address}/24", strict=False))
    except (OSError, subprocess.SubprocessError, ValueError):
        return "192.168.1.0/24"


class SubnetSweeper:
    def __init__(self, workers: int = 64, timeout: float = 0.8) -> None:
        self.workers = workers
        self.timeout = timeout

    def sweep(
        self,
        hosts: Iterable[str],
        callback: Callable[[ProbeResult], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[ProbeResult]:
        stop_event = stop_event or threading.Event()
        results: list[ProbeResult] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(ping_once, host, self.timeout): host for host in hosts}
            for future in as_completed(futures):
                if stop_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    break
                result = future.result()
                results.append(result)
                if callback:
                    callback(result)
        return sorted(results, key=lambda item: int(ipaddress.IPv4Address(item.host)))


def resolve_ipv4(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    if not infos:
        return None
    return infos[0][4][0]


class ContinuousTracer:
    """Continuous traceroute sampling toward the target (PingPlotter-style hops)."""

    def __init__(
        self,
        target: str,
        store: SampleStore,
        on_update: Callable[[str], None] | None = None,
        interval: float = 2.5,
        timeout: float = 1.0,
        max_hops: int = 30,
    ) -> None:
        self.target = target
        self.target_ip = resolve_ipv4(target) or target
        self.store = store
        self.on_update = on_update
        self.interval = interval
        self.timeout = timeout
        self.max_hops = max_hops
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"trace-{self.target}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _sample(self) -> float | None:
        wait_s = max(1, int(round(self.timeout)))
        args = [
            TRACEROUTE,
            "-n",
            "-q",
            "1",
            "-w",
            str(wait_s),
            "-m",
            str(self.max_hops),
            self.target,
        ]
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=max(8.0, self.timeout * self.max_hops + 2.0),
            )
            output = f"{proc.stdout}\n{proc.stderr}"
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.store.record_destination(
                self.target,
                self.target_ip,
                ProbeResult(
                    self.target,
                    False,
                    responder=self.target_ip,
                    error=str(exc),
                ),
                reverse_dns(self.target_ip),
            )
            return None

        endpoint: float | None = None
        rows = parse_traceroute_output(self.target, output)
        if not rows:
            echo = ping_once(self.target, self.timeout)
            dns = reverse_dns(echo.responder or self.target_ip)
            self.store.record_destination(self.target, self.target_ip, echo, dns)
            return echo.rtt_ms if echo.alive else None

        reached = False
        for hop, result in rows:
            is_dest = bool(result.responder) and result.responder in {self.target, self.target_ip}
            if is_dest:
                reached = True
                result = ProbeResult(
                    result.host, True, result.rtt_ms, result.responder, True, result.error
                )
            dns = reverse_dns(result.responder) if result.responder else ""
            if is_dest:
                self.store.record_destination(self.target, self.target_ip, result, dns)
            else:
                self.store.record(self.target, hop, result, dns)
            if result.reached_target and result.rtt_ms is not None:
                endpoint = result.rtt_ms
        if not reached:
            # Destination never answered — still keep it as the final hop row.
            miss = ProbeResult(
                self.target,
                False,
                responder=self.target_ip,
                error="timeout",
            )
            self.store.record_destination(
                self.target,
                self.target_ip,
                miss,
                reverse_dns(self.target_ip),
            )
        # Do not fall back to intermediate hops — missing destination = down.
        return endpoint

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            latency = self._sample()
            self.store.record_timeline(self.target, latency)
            if self.on_update:
                self.on_update(self.target)
            self._stop.wait(max(0.05, self.interval - (time.monotonic() - started)))
