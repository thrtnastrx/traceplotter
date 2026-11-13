# TracePlotter

Original lab code inspired by the continuous traceroute workflow of PingPlotter. This is
a clean-room PySide6 application, not copied or decompiled PingPlotter or Angry IP Scanner
source.

## Features

- Multiple continuously sampled traceroute targets
- Live hop table with sent, loss, and latency statistics
- Rolling latency timeline
- Remote IPv4 CIDR/range scan with responder, all-host, and selected-host actions
- Unprivileged `/sbin/ping` probes on macOS (no `sudo` by default)
- `/24` default scan safety cap; `/23` and `/22` require confirmation

## Run on Apple Silicon

Install an arm64 Python 3.12+ (Homebrew or python.org), then:

```bash
./scripts/run-traceplotter.sh
```

The script creates `.venv`, installs the project, verifies the Python architecture is
`arm64`, and starts the app. To skip dependency installation after the first run:

```bash
TRACEPLOTTER_SKIP_INSTALL=1 ./scripts/run-traceplotter.sh
```

Tests:

```bash
.venv/bin/python -m pytest
```

Saved data lives under `~/Library/Application Support/TracePlotter/` (migrated
automatically from `LabPingPlot` on first launch).

Remote scans can target any reachable IPv4 subnet; they are not restricted to the local
LAN. Scanning a subnet does not imply that firewalls will permit ICMP replies.
