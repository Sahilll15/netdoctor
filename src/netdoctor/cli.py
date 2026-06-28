"""Command-line entry point: parse targets, walk the ladder, render the diagnosis.

Modes:
  * one target               -> the animated single-host vitals monitor
  * many targets             -> a concurrent fleet table
  * --watch (any # targets)  -> a live dashboard with latency-trend sparklines
  * --json                   -> machine-readable output (dependency-free)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from . import __version__, checks, score
from .model import Rung, Status, diagnose, worse

DEFAULT_TIMEOUT = 4.0
DEFAULT_INTERVAL = 5.0
DEFAULT_SAMPLES = 5
EXIT_CODE = {"healthy": 0, "degraded": 1, "unhealthy": 2}
EX_USAGE = 64

EPILOG = """\
By default a single-host run does the full picture: the ladder + traceroute +
a latency scorecard. Use --quick (or --no-trace) when you just want it fast.

examples:
  netdoctor github.com                       full check + traceroute + scorecard
  netdoctor github.com --quick               fast: skip traceroute & extra probes
  netdoctor db.internal:5432                 is the Postgres port reachable?
  netdoctor github.com 1.1.1.1 db:5432       check a fleet of hosts at once
  netdoctor github.com --watch               live vitals dashboard (ctrl-c to stop)
  netdoctor github.com --mtr                 live mtr-style path monitor
  netdoctor github.com --json                machine-readable output for CI / cron

exit codes:
  0  healthy     all core checks passed
  1  degraded    reachable, but a check returned a warning
  2  unhealthy   a core check failed (the diagnosis names which rung)
 64  usage error
"""


@dataclass
class Target:
    host: str
    port: int
    scheme: str
    path: str

    def label(self) -> str:
        return f"{self.host}:{self.port}"


def parse_target(raw: str, port_opt, scheme_opt, path_opt) -> Target:
    """Accept a bare host, host:port, or a full URL and normalise it.
    Explicit flags (--port/--scheme/--path) always win over the target string."""
    text = raw.strip()
    to_parse = text if "://" in text else "//" + text
    host = parsed_port = None
    parsed_scheme = parsed_path = ""
    try:
        parsed = urlparse(to_parse)
        host = parsed.hostname
        parsed_port = parsed.port
        parsed_scheme = parsed.scheme
        parsed_path = parsed.path
    except ValueError:
        pass
    if not host:
        host = text.split("/")[0].split(":")[0] or text

    scheme = scheme_opt or (parsed_scheme if parsed_scheme in ("http", "https") else None)
    port = port_opt or parsed_port
    if scheme is None:
        scheme = "https" if (port in (443, 8443) or port is None) else "http"
    if port is None:
        port = 443 if scheme == "https" else 80
    path = path_opt or parsed_path or "/"
    return Target(host=host, port=port, scheme=scheme, path=path)


def build_plan(t: Target, timeout: float, do_trace: bool):
    """Ordered list of (key, title, layer, thunk) — the rungs to walk, top to bottom."""
    http_title = ("HTTPS" if t.scheme == "https" else "HTTP") + f" {t.path}"
    plan = [
        ("dns", "DNS resolution", "L7", lambda: checks.check_dns(t.host, timeout)),
        ("ping", "Ping (ICMP)", "L3", lambda: checks.check_ping(t.host, timeout)),
        ("port", f"TCP port {t.port}", "L4", lambda: checks.check_port(t.host, t.port, timeout)),
        ("http", http_title, "L7", lambda: checks.check_http(t.host, t.port, t.scheme, t.path, timeout)),
    ]
    if do_trace:
        plan.append(("trace", "Traceroute", "L3", lambda: checks.check_trace(t.host, timeout)))
    return plan


def run_plan(plan, on_update=None) -> "list[Rung]":
    """Walk each rung in order. If DNS fails, downstream rungs are skipped.
    `on_update(rungs_so_far, active_key)` drives the live UI (active_key=None between steps)."""
    rungs: "list[Rung]" = []
    aborted = False
    for key, title, _layer, thunk in plan:
        if aborted:
            rungs.append(Rung(
                key=key, title=title, status=Status.SKIP,
                detail="skipped — DNS did not resolve", core=key in ("port", "http"),
            ))
            if on_update:
                on_update(rungs, None)
            continue
        if on_update:
            on_update(rungs, key)
        rung = thunk()
        rungs.append(rung)
        if key == "dns" and rung.status is Status.FAIL:
            aborted = True
        if on_update:
            on_update(rungs, None)
    return rungs


def diagnose_once(t: Target, timeout: float, do_trace: bool):
    start = time.perf_counter()
    rungs = run_plan(build_plan(t, timeout, do_trace))
    elapsed = (time.perf_counter() - start) * 1000.0
    return rungs, diagnose(rungs, t.host), elapsed


def _probe_method(rungs) -> "str | None":
    """Pick how to benchmark the app, based on what the ladder reached."""
    if any(r.key == "http" and r.status in (Status.OK, Status.WARN) for r in rungs):
        return "http"
    if any(r.key == "port" and r.status is Status.OK for r in rungs):
        return "tcp"
    return None


def build_scorecard_for(t: Target, rungs, samples: int, timeout: float, on_probe=None):
    """A scorecard from `samples` probes (or a single implicit sample when samples<=1)."""
    if samples <= 1:
        return score.build_scorecard(rungs)
    method = _probe_method(rungs)
    if method is None:
        return score.build_scorecard(rungs)
    results = []
    for i in range(samples):
        results.append(checks.measure(t.host, t.port, t.scheme, t.path, method, timeout))
        if on_probe:
            on_probe(i + 1, samples)
    return score.build_scorecard(rungs, results)


def _now() -> "tuple[str, str]":
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S"), now.astimezone().isoformat(timespec="seconds")


def _core_latency(rungs) -> "float | None":
    http = next((r.latency_ms for r in rungs if r.key == "http"), None)
    if http is not None:
        return http
    return next((r.latency_ms for r in rungs if r.latency_ms), None)


def _empty_state(targets):
    state = {
        t.label(): {"target": t, "spark": deque(maxlen=48), "verdicts": deque(maxlen=1000), "latest": None}
        for t in targets
    }
    return state, list(state.keys())


# ---------------------------------------------------------------------------
# Renderers / runners
# ---------------------------------------------------------------------------
def _console(no_color: bool):
    try:
        from rich.console import Console
    except ImportError:
        print(
            "netdoctor needs the 'rich' library for its report.\n"
            "  pip install rich      (or run with --json for dependency-free output)",
            file=sys.stderr,
        )
        return None
    return Console(no_color=no_color or None, highlight=False)


def run_single(t: Target, timeout: float, do_trace: bool, samples: int, console) -> int:
    from rich.console import Group
    from rich.live import Live

    from . import render

    when, _ = _now()
    plan = build_plan(t, timeout, do_trace)
    plan_titles = [(k, title, layer) for k, title, layer, _ in plan]
    done: dict = {}
    start = time.perf_counter()

    def frame(active_key, settled=False, pulse="bold red1"):
        return Group(
            render.make_header(t.host, t.port, t.scheme, when, pulse_style=pulse, settled=settled),
            render.render_pipeline(plan_titles, done, active_key),
        )

    with Live(console=console, refresh_per_second=15) as live:
        def on_update(rungs, active_key):
            done.clear()
            done.update({r.key: r for r in rungs})
            live.update(frame(active_key))

        live.update(frame(None))
        rungs = run_plan(plan, on_update=on_update)
        diag = diagnose(rungs, t.host)
        done.clear()
        done.update({r.key: r for r in rungs})
        live.update(frame(None, settled=True, pulse=render.verdict_pulse(diag.verdict)))

    elapsed = (time.perf_counter() - start) * 1000.0
    console.print()
    console.print(render.make_diagnosis(diag, rungs, elapsed))

    if samples > 1 and _probe_method(rungs) is not None:
        with console.status(f"[cyan]benchmarking · {samples} probes…", spinner="dots"):
            card = build_scorecard_for(t, rungs, samples, timeout)
    else:
        card = build_scorecard_for(t, rungs, samples, timeout)
    console.print()
    console.print(render.make_scorecard(card, t.label()))

    if do_trace:
        route = render.make_route(next((r for r in rungs if r.key == "trace"), None))
        if route is not None:
            console.print(route)
    return EXIT_CODE[diag.verdict.value]


def _run_fleet_pass(targets, timeout, do_trace, state):
    """Run every target concurrently and fold the results into `state`. Returns worst verdict."""
    worst = "healthy"
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = {t.label(): pool.submit(diagnose_once, t, timeout, do_trace) for t in targets}
        results = {label: fut.result() for label, fut in futures.items()}
    for label, (rungs, diag, elapsed) in results.items():
        st = state[label]
        st["latest"] = (rungs, diag, elapsed)
        st["spark"].append(_core_latency(rungs))
        st["verdicts"].append(diag.verdict)
        worst = worse(worst, diag.verdict.value)
    return worst


def run_fleet(targets, timeout: float, console) -> int:
    from . import render

    state, order = _empty_state(targets)
    # Traceroute is a single-host deep-dive; the fleet table doesn't show it.
    worst = _run_fleet_pass(targets, timeout, False, state)
    when, _ = _now()
    console.print(render.make_monitor(state, order, when, 1, 0, 0, watching=False, settled=True))
    return EXIT_CODE[worst]


def run_watch(targets, timeout: float, interval: float, max_runs: int, console) -> int:
    from rich.live import Live

    from . import render

    state, order = _empty_state(targets)
    worst = "healthy"
    run_no = 0
    try:
        with Live(console=console, refresh_per_second=12) as live:
            while True:
                run_no += 1
                worst = worse(worst, _run_fleet_pass(targets, timeout, False, state))
                when, _ = _now()
                final = bool(max_runs) and run_no >= max_runs
                deadline = time.monotonic() + (0 if final else interval)
                # Animate the heartbeat + countdown until the next refresh.
                while True:
                    remaining = deadline - time.monotonic()
                    live.update(render.make_monitor(
                        state, order, when, run_no, remaining, interval,
                        watching=True, settled=final,
                    ))
                    if remaining <= 0:
                        break
                    time.sleep(0.12)
                if final:
                    break
    except KeyboardInterrupt:
        pass
    return EXIT_CODE[worst]


def run_mtr(t: Target, timeout: float, interval: float, max_runs: int, console) -> int:
    """mtr-style live path monitor: traceroute every cycle, rolling per-hop stats."""
    from rich.live import Live

    from . import render

    hopstate: dict = {}
    order: list = []
    run_no = 0
    try:
        with Live(console=console, refresh_per_second=12) as live:
            while True:
                run_no += 1
                rung = checks.check_trace(t.host, timeout)
                for h in rung.data.get("hops", []):
                    n = h["hop"]
                    st = hopstate.get(n)
                    if st is None:
                        st = {"host": h["host"], "ip": h.get("ip"),
                              "rtts": deque(maxlen=60), "resp": 0, "total": 0}
                        hopstate[n] = st
                        order.append(n)
                    if h["host"] and h["host"] != "*":
                        st["host"] = h["host"]
                        st["ip"] = h.get("ip") or st["ip"]
                    st["total"] += 1
                    if h["responded"] and h["rtt_ms"] is not None:
                        st["resp"] += 1
                        st["rtts"].append(h["rtt_ms"])
                    else:
                        st["rtts"].append(None)
                order.sort()
                when, _ = _now()
                final = bool(max_runs) and run_no >= max_runs
                deadline = time.monotonic() + (0 if final else interval)
                while True:
                    remaining = deadline - time.monotonic()
                    live.update(render.make_mtr(hopstate, order, t.label(), when,
                                                run_no, remaining, interval, settled=final))
                    if remaining <= 0:
                        break
                    time.sleep(0.12)
                if final:
                    break
    except KeyboardInterrupt:
        pass
    return 0


def run_json(targets, timeout: float, do_trace: bool, samples: int) -> int:
    out = []
    worst = "healthy"
    for t in targets:
        rungs, diag, elapsed = diagnose_once(t, timeout, do_trace)
        worst = worse(worst, diag.verdict.value)
        card = build_scorecard_for(t, rungs, samples, timeout)
        _, ts = _now()
        out.append({
            "target": t.host,
            "port": t.port,
            "scheme": t.scheme,
            "path": t.path,
            "timestamp": ts,
            "elapsed_ms": round(elapsed, 1),
            "diagnosis": diag.to_dict(),
            "scorecard": card.to_dict(),
            "rungs": [r.to_dict() for r in rungs],
        })
    print(json.dumps(out[0] if len(out) == 1 else out, indent=2, ensure_ascii=False))
    return EXIT_CODE[worst]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="netdoctor",
        description="Walk the network debugging ladder against one or more hosts and diagnose what's broken.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("target", nargs="+", help="one or more hosts, host:port, or URLs")
    p.add_argument("-p", "--port", type=int, help="TCP port to test (default: 443 https / 80 http)")
    p.add_argument("--scheme", choices=("http", "https"), help="force http or https for the app check")
    p.add_argument("--path", help="HTTP path to request (default: /)")
    p.add_argument("-t", "--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SECONDS",
                   help=f"per-check timeout in seconds (default: {DEFAULT_TIMEOUT})")
    p.add_argument("-w", "--watch", action="store_true", help="live vitals dashboard, re-checking on an interval")
    p.add_argument("--mtr", action="store_true", help="live mtr-style path monitor (single host)")
    p.add_argument("-n", "--interval", type=float, default=DEFAULT_INTERVAL, metavar="SECONDS",
                   help=f"--watch / --mtr refresh interval (default: {DEFAULT_INTERVAL})")
    p.add_argument("--max-runs", type=int, default=0, metavar="N",
                   help="with --watch / --mtr, stop after N refreshes (0 = until ctrl-c)")
    p.add_argument("-s", "--samples", type=int, default=DEFAULT_SAMPLES, metavar="N",
                   help=f"app probes for the latency/throughput scorecard (default: {DEFAULT_SAMPLES})")
    p.add_argument("--no-trace", action="store_false", dest="trace", help="skip the traceroute step (faster)")
    p.add_argument("--quick", action="store_true", help="fastest run: skip traceroute and extra probes")
    p.add_argument("--json", action="store_true", help="emit JSON instead of the live report")
    p.add_argument("--no-color", action="store_true", help="disable colour / styling")
    p.add_argument("-V", "--version", action="version", version=f"netdoctor {__version__}")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return EX_USAGE
    if args.interval <= 0:
        print("error: --interval must be positive", file=sys.stderr)
        return EX_USAGE
    if args.port is not None and not (0 < args.port < 65536):
        print("error: --port must be between 1 and 65535", file=sys.stderr)
        return EX_USAGE
    if not (1 <= args.samples <= 1000):
        print("error: --samples must be between 1 and 1000", file=sys.stderr)
        return EX_USAGE

    targets = [parse_target(raw, args.port, args.scheme, args.path) for raw in args.target]
    if any(not t.host for t in targets):
        print("error: could not parse a host from one of the targets", file=sys.stderr)
        return EX_USAGE

    # --quick is the fast escape hatch from the full-by-default behaviour.
    do_trace = args.trace and not args.quick
    samples = 1 if args.quick else args.samples

    try:
        if args.json:
            return run_json(targets, args.timeout, do_trace, samples)

        console = _console(args.no_color)
        if console is None:
            return EX_USAGE
        if args.mtr:
            if len(targets) != 1:
                print("error: --mtr works with a single target", file=sys.stderr)
                return EX_USAGE
            return run_mtr(targets[0], args.timeout, args.interval, args.max_runs, console)
        if args.watch:
            return run_watch(targets, args.timeout, args.interval, args.max_runs, console)
        if len(targets) == 1:
            return run_single(targets[0], args.timeout, do_trace, samples, console)
        return run_fleet(targets, args.timeout, console)
    except KeyboardInterrupt:
        print("\naborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
