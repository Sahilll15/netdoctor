# netdoctor

> Point it at a host. It walks the network debugging ladder rung by rung and tells you **exactly which one broke** — and what to do about it.

`netdoctor` automates the sequence every engineer runs by hand when "the service is down": resolve the name, ping it, check the port, hit the app. Instead of five commands and five mental models, you get one live report, a plain-English diagnosis, and a **quality scorecard** that grades the host on reachability, performance, and latency.

```
netdoctor github.com
```

```text
╭──────────────────────────────────────────────────────────────────────────╮
│ ◉ netdoctor   network vitals monitor                  api.example.com:443  │
│ ⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯⎯       2026-06-28 12:54:32  │
╰──────────────────────────────────────────────────────────────────────────╯
╭─ signal path  ·  resolve → connect → respond ──────────────────────────────╮
│                                                                            │
│ ●  1 ✓ DNS resolution L7 api.example.com → 93.184.216.34  █······    12 ms │
│ │                                                                          │
│ ●  2 ⚠ Ping (ICMP)    L3 no reply (ICMP likely blocked)        —           │
│ │                                                                          │
│ ●  3 ✓ TCP port 443   L4 open                             █······    41 ms │
│ │                                                                          │
│ ●  4 ✓ HTTPS /        L7 200 OK · TLSv1.3 · cert 67d left ███████   136 ms │
│                                                                            │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ diagnosis ────────────────────────────────────────────────────────────────╮
│                                                                            │
│ ●  HEALTHY     api.example.com is reachable and responding.                │
│                                                                            │
│ vitals   ▰ ▰ ▰ ▰    4 ok  ·  189 ms total                                  │
│                                                                            │
│ → No ICMP reply — many hosts and firewalls block ping, so this alone does  │
│   NOT mean the host is down. The TCP port and HTTP checks are authoritative.│
│                                                                            │
╰────────────────────────────────────────────────────────────────────────────╯
```

> The header is a **live ECG line** that scrolls while checks run and freezes in
> the verdict colour when done. The **signal-path rail** fills in rung by rung as
> the packet descends the stack (each step tagged with its OSI layer). And note
> the diagnosis: the host **ignores ping** (normal for production hosts), yet it's
> still **healthy** — because the port and HTTP checks, the ones that actually
> matter, both passed. That judgement is the whole reason the tool exists.

---

## Why this exists

When a service is unreachable, the fix is almost always finding **which layer** is broken. The classic move is to walk a ladder, top to bottom, until something fails:

| Question | The manual command | netdoctor's rung |
|---|---|---|
| Does the name resolve to an IP? | `dig` / `nslookup` | **DNS resolution** |
| Is the host reachable at all? | `ping` | **Ping (ICMP)** — *advisory* |
| Is the specific port open? | `nc -zv host 443` | **TCP port** |
| Does the app actually respond? | `curl -v https://host` | **HTTP / TLS** |
| Where does the path break? | `traceroute` | **Traceroute** (`--trace`) |

netdoctor runs the whole ladder for you, stops reasoning about ICMP the way a human does (a blocked ping is **not** an outage), and points at the first rung that genuinely failed.

---

## Install

```bash
git clone https://github.com/Sahilll15/netdoctor.git
cd netdoctor
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Now `netdoctor` is on your PATH. (Prefer not to use the console script? `python -m netdoctor github.com` works the same way.)

---

## Usage

```bash
netdoctor github.com                       # full picture: ladder + traceroute + scorecard
netdoctor github.com --quick               # fast: skip traceroute & extra probes
netdoctor db.internal:5432                 # is the Postgres port reachable?
netdoctor github.com 1.1.1.1 db:5432       # a whole fleet at once (concurrent)
netdoctor github.com --watch               # live vitals dashboard (ctrl-c to stop)
netdoctor github.com --mtr                 # live mtr-style path monitor
netdoctor github.com --json                # machine-readable output for CI / cron
```

The target accepts a **bare host**, **host:port**, or a **full URL** — the scheme, port, and path are parsed out automatically. Explicit flags (`--port`, `--scheme`, `--path`) always win. Pass **several targets** to check them concurrently as a fleet.

> **Full by default.** A single-host run does the whole picture — the ladder, a traceroute, and a latency scorecard — with no flags to remember. Use `--quick` (or `--no-trace`) when you just want a fast up/down answer.

### Traceroute (default) & `--mtr`

Every single-host run includes a **traceroute** that shows the path hop by hop, with per-hop latency, reverse-DNS names, and a marker for **exactly where the path goes dark**:

```text
╭─ route → 140.82.112.3 ───────────────────────────────────────────────╮
│ ●   1  router.local        192.168.1.1       1 ms                    │
│ ●   2  isp-gateway.net      10.20.0.1         6 ms                    │
│ ○   3  * * *                                  —                       │
│ ●   4  140.82.112.3         140.82.112.3     11 ms   ◀ destination    │
│                                                                       │
│ ✓ destination reached                                                 │
╰───────────────────────────────────────────────────────────────────────╯
```

`--mtr` turns that into a live, **mtr-style** monitor that re-probes on an interval and tracks rolling **loss %**, last/avg/best/worst latency, and a sparkline **per hop**:

```text
╭─────┬─────────────────┬──────┬──────┬─────┬──────┬───────┬────────────╮
│ HOP │ HOST            │ LOSS │ LAST │ AVG │ BEST │ WORST │ TREND      │
├─────┼─────────────────┼──────┼──────┼─────┼──────┼───────┼────────────┤
│   1 │ router.local    │   0% │    1 │   1 │    1 │     2 │ ▁▂▁▁▂▁     │
│   2 │ isp-gateway.net │   0% │    6 │   7 │    5 │    12 │ ▂▃▂▅▂▃     │
│   3 │ * * *           │ 100% │    — │   — │    — │     — │ ××××××     │
╰─────┴─────────────────┴──────┴──────┴─────┴──────┴───────┴────────────╯
⟳ next probe in 3s   ·   run #6   ·   ctrl-c to stop
```

### Live monitor (`--watch`)

```bash
netdoctor github.com api.internal:8080 --watch --interval 10
```

Turns netdoctor into a persistent dashboard that re-checks on an interval and keeps a **latency-trend sparkline** and a rolling **uptime %** per host:

```text
╭────┬──────────────────┬────────┬─────────┬──────────┬───────────────┬──────┬───┬──────────╮
│    │ HOST             │    DNS │    PORT │     HTTP │ LATENCY TREND │   UP │ # │ STATUS   │
├────┼──────────────────┼────────┼─────────┼──────────┼───────────────┼──────┼───┼──────────┤
│ ●  │ github.com:443   │  ✓ 2ms │ ✓ 41ms  │ ✓ 151ms  │ ▁▂▂▁▃▂▁▂      │ 100% │ 8 │ HEALTHY  │
│ ●  │ api.internal:8080│  ✓ 1ms │ ✗ 0ms   │ · skip   │ ▅▆█▅▄▅██      │  62% │ 8 │ UNHEALTHY│
╰────┴──────────────────┴────────┴─────────┴──────────┴───────────────┴──────┴───┴──────────╯
⟳ next refresh in 7s   ·   every 10s   ·   run #8   ·   ctrl-c to stop
```

### Scorecard — *how good, how fast, how reliable*

Every run ends in a **scorecard** that grades the host **A+ → F**. It probes the
app a few times by default (`--samples 5`) for a real latency distribution, jitter,
and an estimated request rate — bump `--samples` higher for a fuller picture:

```bash
netdoctor api.example.com --samples 30
```

```text
╭─ scorecard ────────────────────────────────────────────────────────────────╮
│                                                                            │
│  A-    92 / 100        api.example.com:443                                 │
│                                                                            │
│ reachability  ██████████████████████  100  30/30 probes ok                 │
│ performance   ██████████████████░░░░   83                                  │
│ stability     ███████████████████░░░   88  ±50 ms jitter                   │
│                                                                            │
│ latency   min 38  ·  avg 112  ·  p95 240  ·  max 410 ms                     │
│ rate      100% reachable   ·   ≈ 8.9 req/s (single connection)             │
│ samples   ▄▃▄▁▆█▁▃▁▂▅▁▃▂▄▁▂▅▃▁▂▄▆▃▁▂▄▁▃▂  (30)                            │
│                                                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

| Metric | What it measures |
|---|---|
| **Reachability** | % of probes that succeeded |
| **Performance** | 0–100 score derived from average latency |
| **Stability** | consistency — high when jitter is low (needs `--samples ≥ 2`) |
| **Latency** | min / avg / p95 / max, plus jitter (std-dev) |
| **Rate** | success rate + estimated throughput (`≈ req/s`, single connection) |
| **Grade** | a weighted A+→F summary of all of the above |

In fleet and `--watch` views, the grade shows as a compact **GRADE** column per host.

### Options

| Flag | Purpose |
|---|---|
| `-p, --port` | TCP port to test (default: 443 for https, 80 for http) |
| `--scheme {http,https}` | Force the scheme for the app check |
| `--path` | HTTP path to request (default: `/`) |
| `-t, --timeout SECONDS` | Per-check timeout (default: 4.0) |
| `-w, --watch` | Live vitals dashboard, re-checking on an interval |
| `--mtr` | Live mtr-style path monitor (single host) |
| `-n, --interval SECONDS` | `--watch` / `--mtr` refresh interval (default: 5.0) |
| `--max-runs N` | With `--watch` / `--mtr`, stop after N refreshes (0 = until ctrl-c) |
| `-s, --samples N` | App probes for the latency scorecard (default: 5) |
| `--no-trace` | Skip the traceroute step (faster) |
| `--quick` | Fastest run: skip traceroute and extra probes |
| `--json` | Emit JSON instead of the live report |
| `--no-color` | Disable colour / styling |

### Exit codes

`netdoctor` is built to drop into scripts, cron jobs, and CI:

| Code | Verdict | Meaning |
|---|---|---|
| `0` | healthy | all core checks passed |
| `1` | degraded | reachable, but a check returned a warning (e.g. HTTP 5xx, cert expiring) |
| `2` | unhealthy | a core check failed (the diagnosis names which rung) |
| `64` | — | usage error |

```bash
netdoctor api.example.com/health || echo "page someone!"
```

### JSON output

```bash
netdoctor github.com --json
```

```json
{
  "target": "github.com",
  "port": 443,
  "scheme": "https",
  "elapsed_ms": 191.4,
  "diagnosis": { "verdict": "healthy", "broken_rung": null, "...": "..." },
  "scorecard": {
    "grade": "A-", "overall": 92.0, "reachability": 100.0, "performance": 83.0,
    "stability": 88.0, "throughput_rps": 8.9,
    "latency_ms": { "min": 38, "avg": 112, "p95": 240, "max": 410, "jitter": 50 }
  },
  "rungs": [
    { "key": "dns",  "status": "ok",   "detail": "github.com → 140.82.112.3", "latency_ms": 11.4 },
    { "key": "ping", "status": "warn", "detail": "no reply (ICMP likely blocked)", "core": false },
    { "key": "port", "status": "ok",   "detail": "open", "latency_ms": 41.0 },
    { "key": "http", "status": "ok",   "detail": "200 OK · TLSv1.3 · cert 67d left",
      "data": { "tls": "TLSv1.3", "cert_days_left": 67,
                "timing": { "connect_ms": 38.0, "ttfb_ms": 97.2 }, "status_code": 200 } }
  ]
}
```

Pass several targets and you get a JSON **array** instead — ideal for piping into `jq`, dashboards, or a cron alert.

---

## How it works

A clean separation of concerns — the whole point is that the logic is testable without touching the network:

```
src/netdoctor/
├── model.py    # Rung / Status / Verdict + diagnose() — pure logic, no I/O
├── checks.py   # one function per rung; returns a completed Rung, never prints
├── score.py    # the grading model (reachability/performance/latency) — pure logic
├── render.py   # all the Rich presentation (ECG header, signal rail, dashboard)
└── cli.py      # arg parsing, run loop, watch/fleet orchestration, JSON, exit codes
```

The **diagnosis engine** (`diagnose()`) is deliberately I/O-free, so the decision rules are unit-tested in isolation:

- any **core** rung that fails → **unhealthy** (named by the first failure)
- else any core rung warning → **degraded**
- else → **healthy**
- advisory rungs (ping, traceroute) never change the verdict — a blocked ping just adds a note.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests are deterministic and need no internet: the verdict engine is pure, target
parsing is table-driven, and the TCP check runs against a socket the test opens
and closes itself. CI runs them on Python 3.9 / 3.11 / 3.13 via GitHub Actions.

---

## Roadmap

- [x] `--watch` — live monitoring dashboard with latency-trend sparklines
- [x] Multiple targets in one run (concurrent fleet view)
- [x] HTTP timing breakdown (connect / TTFB)
- [x] Quality scorecard — reachability / performance / latency / grade (`--samples`)
- [x] Hop-by-hop traceroute with break detection + an `mtr`-style live monitor (`--mtr`)
- [ ] Read targets from a file / stdin
- [ ] Ship as a single-file binary (PyInstaller) and a container image

---

## License

MIT © Sahil Chalke
