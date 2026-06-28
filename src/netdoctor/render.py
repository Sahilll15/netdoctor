"""Rich rendering: a live "network vitals monitor".

The design metaphor is a clinical monitor for a host:
  * an animated ECG/pulse line in the header (scrolls live, freezes on verdict),
  * a vertical signal-path rail that fills in as the packet descends the stack
    (each rung tagged with its OSI layer, L7 -> L4 -> L3),
  * a latency micro-bar per rung,
  * a final "vitals" strip summarising the diagnosis.

Everything time-based (the heartbeat, the spinner) animates on Rich's refresh
loop, so the report feels alive while the checks run.
"""
from __future__ import annotations

import time

from rich.box import ROUNDED
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .model import Diagnosis, Rung, Status, Verdict

_ICON = {
    Status.OK:   ("✓", "bold green"),
    Status.WARN: ("⚠", "bold yellow"),
    Status.FAIL: ("✗", "bold red"),
    Status.SKIP: ("·", "dim"),
}
_NODE_STYLE = {
    Status.OK:   "green",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.SKIP: "grey37",
}
_DETAIL_STYLE = {
    Status.OK:   "white",
    Status.WARN: "yellow",
    Status.FAIL: "red",
    Status.SKIP: "dim",
}
_VERDICT = {
    Verdict.HEALTHY:   ("HEALTHY",   "bold green",  "green"),
    Verdict.DEGRADED:  ("DEGRADED",  "bold yellow", "yellow"),
    Verdict.UNHEALTHY: ("UNHEALTHY", "bold red",    "red"),
}
_VERDICT_PULSE = {
    Verdict.HEALTHY:   "bold green",
    Verdict.DEGRADED:  "bold yellow",
    Verdict.UNHEALTHY: "bold red",
}

# A flat trace punctuated by QRS-style spikes — tiled and scrolled for the ECG.
_PULSE = "⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯⎯⎯⎯╱╲⎯⎯⎯⎯⎯⎯"


class Heartbeat:
    """An ECG line. Scrolls left while live; freezes (coloured) once settled."""

    def __init__(self, width: int = 42, style: str = "bold red1", settled: bool = False):
        self.width = width
        self.style = style
        self.settled = settled

    def __rich_console__(self, console, options):
        tiled = _PULSE * 3
        if self.settled:
            yield Text(tiled[: self.width], style=self.style)
            return
        offset = int(time.monotonic() * 12) % len(_PULSE)
        yield Text(tiled[offset : offset + self.width], style=self.style)


def make_header(host: str, port: int, scheme: str, when: str,
                *, pulse_style: str = "bold red1", settled: bool = False) -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")

    wordmark = Text()
    wordmark.append("◉ ", style="bold cyan")
    wordmark.append("net", style="bold white")
    wordmark.append("doctor", style="bold cyan")
    wordmark.append("   network vitals monitor", style="dim italic")

    patient = Text()
    patient.append(f"{host}:{port}", style="bold cyan")
    patient.append(f"  {scheme}", style="dim")

    grid.add_row(wordmark, patient)
    grid.add_row(Heartbeat(width=42, style=pulse_style, settled=settled),
                 Text(when, style="dim", justify="right"))
    return Panel(grid, border_style="cyan", box=ROUNDED, padding=(0, 1))


def _latency(rung: Rung) -> Text:
    if rung.latency_ms is None:
        return Text("—", style="dim", justify="right")
    ms = rung.latency_ms
    text = f"{ms / 1000:.1f} s" if ms >= 10000 else f"{ms:.0f} ms"
    return Text(text, style="dim", justify="right")


def _bar(latency_ms, max_ms: float, width: int = 7) -> Text:
    if latency_ms is None:
        return Text("")
    ratio = 0.0 if max_ms <= 0 else min(1.0, latency_ms / max_ms)
    filled = max(1, int(round(ratio * width)))
    if latency_ms < 100:
        color = "green"
    elif latency_ms < 300:
        color = "cyan"
    elif latency_ms < 800:
        color = "yellow"
    else:
        color = "red"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("·" * (width - filled), style="grey23")
    return bar


def render_pipeline(plan, done_by_key, active_key) -> Panel:
    """The vertical signal-path rail. `plan` is an ordered list of (key, title, layer)."""
    lats = [r.latency_ms for r in done_by_key.values() if r.latency_ms]
    max_lat = max(lats) if lats else 1.0

    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=1)                      # rail node
    grid.add_column(width=2, justify="right")     # step number
    grid.add_column(width=1)                      # status icon
    grid.add_column(min_width=14, no_wrap=True)   # title
    grid.add_column(width=2, justify="right")     # OSI layer
    grid.add_column(ratio=1, overflow="fold")     # detail
    grid.add_column(width=7)                       # latency bar
    grid.add_column(width=8, justify="right")     # latency value

    empties = [Text("")] * 7
    total = len(plan)
    for i, (key, title, layer) in enumerate(plan):
        num = Text(str(i + 1), style="grey50")
        layer_tag = Text(layer, style="grey42")

        if key in done_by_key:
            r = done_by_key[key]
            node = Text("●", style=_NODE_STYLE[r.status])
            ic, ic_style = _ICON[r.status]
            icon = Text(ic, style=ic_style)
            title_style = "dim" if r.status is Status.SKIP else "bold white"
            title_text = Text(title, style=title_style)
            detail = Text(r.detail, style=_DETAIL_STYLE[r.status])
            bar = _bar(r.latency_ms, max_lat)
            lat = _latency(r)
            rail_style = _NODE_STYLE[r.status]
        elif key == active_key:
            node = Spinner("dots", style="bold cyan")
            icon = Text("")
            title_text = Text(title, style="bold cyan")
            detail = Text("checking…", style="cyan")
            bar = Text("")
            lat = Text("")
            rail_style = "cyan"
        else:
            node = Text("○", style="grey30")
            icon = Text("")
            title_text = Text(title, style="grey42")
            detail = Text("queued", style="grey30")
            bar = Text("")
            lat = Text("")
            rail_style = "grey30"

        grid.add_row(node, num, icon, title_text, layer_tag, detail, bar, lat)
        if i < total - 1:
            grid.add_row(Text("│", style=rail_style), *empties)

    return Panel(grid, title="[dim]signal path  ·  resolve → connect → respond[/]",
                 title_align="left", border_style="grey37", box=ROUNDED, padding=(1, 1))


def make_diagnosis(diag: Diagnosis, rungs, elapsed_ms: float) -> Panel:
    label, label_style, border = _VERDICT[diag.verdict]
    ok = sum(1 for r in rungs if r.status is Status.OK)
    warn = sum(1 for r in rungs if r.status is Status.WARN)
    fail = sum(1 for r in rungs if r.status is Status.FAIL)

    body = Text()
    body.append(f"●  {label}", style=label_style)
    body.append("     ")
    body.append(diag.headline, style="bold")

    body.append("\n\n")
    body.append("vitals   ", style="dim")
    for r in rungs:
        body.append("▰ ", style=_NODE_STYLE.get(r.status, "grey37"))
    body.append("   ")
    body.append(f"{ok} ok", style="green")
    if warn:
        body.append("  ·  ", style="dim")
        body.append(f"{warn} warn", style="yellow")
    if fail:
        body.append("  ·  ", style="dim")
        body.append(f"{fail} fail", style="red")
    body.append("  ·  ", style="dim")
    body.append(f"{elapsed_ms:.0f} ms total", style="dim")

    for note in diag.notes:
        body.append("\n\n")
        body.append("→ ", style=label_style)
        body.append(note, style="dim")

    return Panel(body, title="[bold]diagnosis[/]", title_align="left",
                 border_style=border, box=ROUNDED, padding=(1, 1))


def _hop_color(rtt) -> str:
    if rtt is None:
        return "dim"
    return "green" if rtt < 30 else "cyan" if rtt < 80 else "yellow" if rtt < 150 else "red"


def make_route(rung: "Rung | None") -> "Panel | None":
    from rich.console import Group

    data = rung.data if rung else {}
    hops = data.get("hops")
    if not hops:
        return None
    dest_ip = data.get("dest_ip")
    reached = data.get("reached")
    last_resp = max((h["hop"] for h in hops if h["responded"]), default=0)

    table = Table.grid(padding=(0, 1))
    table.add_column(width=1)                        # node
    table.add_column(width=3, justify="right")       # hop #
    table.add_column(min_width=20, overflow="fold")  # host
    table.add_column(width=16, no_wrap=True)         # ip
    table.add_column(width=8, justify="right")       # rtt
    table.add_column(ratio=1)                        # marker

    for h in hops:
        if h["responded"]:
            color = _hop_color(h["rtt_ms"])
            node = Text("●", style=color)
            host = Text(h["host"], style="white")
            ip = Text(h["ip"] or "", style="dim")
            rtt = Text(f"{h['rtt_ms']:.0f} ms" if h["rtt_ms"] is not None else "", style=color)
        else:
            node = Text("○", style="grey30")
            host = Text("* * *", style="grey30")
            ip = Text("", style="dim")
            rtt = Text("—", style="dim")
        marker = Text("◀ destination", style="bold green") if (dest_ip and h["ip"] == dest_ip) else Text("")
        table.add_row(node, Text(str(h["hop"]), style="grey50"), host, ip, rtt, marker)

    note = Text()
    if reached:
        note.append("✓ ", style="green")
        note.append("destination reached", style="dim")
    else:
        note.append("✗ ", style="yellow")
        note.append(f"path goes dark after hop {last_resp} — destination not reached", style="dim")

    title = f"[dim]route → {dest_ip}[/]" if dest_ip else "[dim]route[/]"
    return Panel(Group(table, Text(""), note), title=title, title_align="left",
                 border_style="grey37", box=ROUNDED, padding=(1, 1))


def _plain_header(title: str, when: str, *, pulse_style: str, settled: bool) -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    wm = Text()
    wm.append("◉ ", style="bold cyan")
    wm.append("net", style="bold white")
    wm.append("doctor", style="bold cyan")
    wm.append(f"   {title}", style="dim italic")
    grid.add_row(wm, Text(when, style="dim", justify="right"))
    grid.add_row(Heartbeat(width=42, style=pulse_style, settled=settled), Text(""))
    return Panel(grid, border_style="cyan", box=ROUNDED, padding=(0, 1))


def make_mtr(hopstate, order, host_label, when, run_no, remaining, interval, *, settled=False):
    """mtr-style live view: rolling per-hop loss% and latency across probe cycles."""
    from rich.console import Group

    pulse = "bold green" if settled else "bold red1"
    header = _plain_header(f"mtr · {host_label}", when, pulse_style=pulse, settled=settled)

    table = Table(box=ROUNDED, border_style="grey37", expand=True, padding=(0, 1), header_style="bold dim")
    table.add_column("HOP", justify="right", width=3)
    table.add_column("HOST", no_wrap=True)
    table.add_column("LOSS", justify="right")
    table.add_column("LAST", justify="right")
    table.add_column("AVG", justify="right")
    table.add_column("BEST", justify="right")
    table.add_column("WORST", justify="right")
    table.add_column("TREND", justify="left")

    def cell(value):
        return Text(f"{value:.0f}" if value is not None else "—", style=_hop_color(value))

    for hop in order:
        st = hopstate[hop]
        rtts = [r for r in st["rtts"] if r is not None]
        loss = 100.0 * (st["total"] - st["resp"]) / st["total"] if st["total"] else 0.0
        last = next((r for r in reversed(st["rtts"]) if r is not None), None)
        avg = sum(rtts) / len(rtts) if rtts else None
        best = min(rtts) if rtts else None
        worst = max(rtts) if rtts else None
        loss_style = "green" if loss == 0 else "yellow" if loss < 50 else "red"
        responded_ever = bool(rtts)
        host_label_cell = st["host"] if st["host"] and st["host"] != "*" else "* * *"
        table.add_row(
            Text(str(hop), style="grey50"),
            Text(host_label_cell, style="white" if responded_ever else "grey30"),
            Text(f"{loss:.0f}%", style=loss_style),
            cell(last), cell(avg), cell(best), cell(worst),
            sparkline(list(st["rtts"]), width=26),
        )

    if settled:
        foot = Text(f"■ stopped after {run_no} run(s)", style="dim")
    else:
        foot = Text()
        foot.append("⟳ ", style="cyan")
        foot.append(f"next probe in {max(0, remaining):.0f}s", style="dim")
        foot.append(f"   ·   run #{run_no}   ·   ", style="dim")
        foot.append("ctrl-c", style="bold dim")
        foot.append(" to stop", style="dim")
    return Group(header, table, foot)


def verdict_pulse(verdict: Verdict) -> str:
    return _VERDICT_PULSE[verdict]


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------
def _score_color(score: float) -> str:
    return "green" if score >= 85 else "cyan" if score >= 70 else "yellow" if score >= 50 else "red"


def grade_style(grade: str) -> str:
    head = grade[0]
    return {"A": "bold green", "B": "bold cyan", "C": "bold yellow"}.get(head, "bold red")


def _gauge(label: str, score, suffix: str = "", width: int = 22):
    cells = []
    cells.append(Text(label, style="dim"))
    if score is None:
        cells.append(Text("·" * width, style="grey23"))
        cells.append(Text("n/a", style="dim"))
    else:
        filled = int(round(score / 100.0 * width))
        color = _score_color(score)
        bar = Text()
        bar.append("█" * filled, style=color)
        bar.append("░" * (width - filled), style="grey23")
        cells.append(bar)
        cells.append(Text(f"{score:.0f}", style=color))
    cells.append(Text(suffix, style="dim"))
    return cells


def _ms(value) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.1f}s" if value >= 10000 else f"{value:.0f}"


def make_scorecard(sc, target_label: str) -> Panel:
    from rich.console import Group

    g_style = grade_style(sc.grade)
    head = Text()
    head.append(f" {sc.grade} ", style=g_style)
    head.append("   ")
    head.append(f"{sc.overall:.0f} / 100", style=g_style)
    head.append("        ")
    head.append(target_label, style="bold white")

    gauges = Table.grid(padding=(0, 2))
    gauges.add_column(width=13)              # label
    gauges.add_column(width=22)              # bar
    gauges.add_column(width=3, justify="right")  # number
    gauges.add_column(ratio=1)               # suffix
    gauges.add_row(*_gauge("reachability", sc.reachability, f"{sc.n_ok}/{sc.n_total} probes ok"))
    gauges.add_row(*_gauge("performance", sc.performance))
    gauges.add_row(*_gauge("stability", sc.stability,
                           f"±{_ms(sc.jitter_ms)} ms jitter" if sc.stability is not None else "needs --samples ≥ 2"))

    facts = Text()
    facts.append("\nlatency   ", style="dim")
    facts.append(f"min {_ms(sc.lat_min)}", style="white")
    facts.append("  ·  ", style="dim")
    facts.append(f"avg {_ms(sc.lat_avg)}", style="bold white")
    facts.append("  ·  ", style="dim")
    facts.append(f"p95 {_ms(sc.lat_p95)}", style="white")
    facts.append("  ·  ", style="dim")
    facts.append(f"max {_ms(sc.lat_max)} ms", style="white")

    facts.append("\nrate      ", style="dim")
    facts.append(f"{sc.success_rate:.0f}% reachable", style=_score_color(sc.reachability))
    if sc.throughput_rps:
        facts.append("   ·   ", style="dim")
        facts.append(f"≈ {sc.throughput_rps:g} req/s", style="white")
        facts.append(" (single connection)", style="dim")

    spark_vals = [v for v in sc.samples if v is not None]
    if len(spark_vals) >= 2:
        facts.append("\nsamples   ", style="dim")
        facts.append_text(sparkline(sc.samples, width=40))
        facts.append(f"  ({sc.n_total})", style="dim")

    return Panel(Group(head, Text(""), gauges, facts),
                 title="[bold]scorecard[/]", title_align="left",
                 border_style=g_style.split()[-1], box=ROUNDED, padding=(1, 1))


# ---------------------------------------------------------------------------
# Fleet / watch dashboard
# ---------------------------------------------------------------------------
_SPARK = " ▁▂▃▄▅▆▇█"
_VERDICT_DOT = {Verdict.HEALTHY: "green", Verdict.DEGRADED: "yellow", Verdict.UNHEALTHY: "red"}


def sparkline(values, width: int = 24) -> Text:
    """A coloured latency sparkline over recent samples (None = a failed run)."""
    pts = list(values)[-width:]
    nums = [v for v in pts if v is not None]
    if not nums:
        return Text("no data yet", style="dim")
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    out = Text()
    for v in pts:
        if v is None:
            out.append("×", style="red")
            continue
        idx = 1 + int((v - lo) / span * (len(_SPARK) - 2))
        idx = max(1, min(len(_SPARK) - 1, idx))
        color = "green" if v < 100 else "cyan" if v < 300 else "yellow" if v < 800 else "red"
        out.append(_SPARK[idx], style=color)
    return out


def _mini_cell(rung: "Rung | None") -> Text:
    if rung is None:
        return Text("·", style="dim", justify="right")
    ic, style = _ICON[rung.status]
    cell = Text(justify="right")
    cell.append(ic, style=style)
    if rung.latency_ms is not None:
        ms = rung.latency_ms
        cell.append(" ")
        cell.append(f"{ms / 1000:.1f}s" if ms >= 10000 else f"{ms:.0f}ms", style="dim")
    return cell


def _monitor_header(when: str, count: int, *, pulse_style: str, settled: bool) -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    wm = Text()
    wm.append("◉ ", style="bold cyan")
    wm.append("net", style="bold white")
    wm.append("doctor", style="bold cyan")
    plural = "target" if count == 1 else "targets"
    wm.append(f"   monitoring {count} {plural}", style="dim italic")
    grid.add_row(wm, Text(when, style="dim", justify="right"))
    grid.add_row(Heartbeat(width=42, style=pulse_style, settled=settled), Text(""))
    return Panel(grid, border_style="cyan", box=ROUNDED, padding=(0, 1))


def make_monitor(state, order, when, run_no, remaining, interval, *, watching=True, settled=False):
    """Render the fleet/watch dashboard from per-target state.

    `state[label]` = {"target", "spark": deque, "verdicts": deque, "latest": (rungs, diag, elapsed)}.
    """
    from rich.console import Group

    verdicts_now = [state[lbl]["latest"][1].verdict for lbl in order if state[lbl]["latest"]]
    worst = max(verdicts_now, key=lambda v: {Verdict.HEALTHY: 0, Verdict.DEGRADED: 1, Verdict.UNHEALTHY: 2}[v],
                default=Verdict.HEALTHY)
    pulse = verdict_pulse(worst) if settled else "bold red1"

    table = Table(box=ROUNDED, border_style="grey37", expand=True,
                  padding=(0, 1), header_style="bold dim")
    table.add_column(" ", width=1)
    table.add_column("HOST", style="bold", no_wrap=True)
    table.add_column("DNS", justify="right")
    table.add_column("PORT", justify="right")
    table.add_column("HTTP", justify="right")
    table.add_column("LATENCY TREND", justify="left")
    table.add_column("GRADE", justify="center")
    if watching:
        table.add_column("UP", justify="right")
        table.add_column("#", justify="right")
    table.add_column("STATUS", justify="left")

    from . import score as _score

    for lbl in order:
        st = state[lbl]
        latest = st["latest"]
        if latest is None:
            continue
        rungs, diag, _elapsed = latest
        by_key = {r.key: r for r in rungs}
        label, label_style, _ = _VERDICT[diag.verdict]

        dot = Text("●", style=_VERDICT_DOT[diag.verdict])
        host = Text(lbl, style="bold white")
        trend = sparkline(st["spark"])
        status = Text(label, style=label_style)
        card = _score.build_scorecard(rungs)
        grade = Text(card.grade, style=grade_style(card.grade))

        row = [dot, host, _mini_cell(by_key.get("dns")), _mini_cell(by_key.get("port")),
               _mini_cell(by_key.get("http")), trend, grade]
        if watching:
            verdicts = st["verdicts"]
            up = sum(1 for v in verdicts if v is not Verdict.UNHEALTHY)
            pct = 100.0 * up / len(verdicts) if verdicts else 0.0
            up_style = "green" if pct >= 99 else "yellow" if pct >= 90 else "red"
            row.append(Text(f"{pct:.0f}%", style=up_style))
            row.append(Text(str(len(verdicts)), style="dim"))
        row.append(status)
        table.add_row(*row)

    header = _monitor_header(when, len(order), pulse_style=pulse, settled=settled)
    if not watching:
        foot = Text(f"checked {len(order)} target(s) concurrently", style="dim")
    elif settled:
        foot = Text(justify="left")
        foot.append("■ ", style="bold dim")
        foot.append(f"stopped after {run_no} run(s)", style="dim")
    else:
        foot = Text(justify="left")
        foot.append("⟳ ", style="cyan")
        foot.append(f"next refresh in {max(0, remaining):.0f}s", style="dim")
        foot.append(f"   ·   every {interval:.0f}s   ·   run #{run_no}   ·   ", style="dim")
        foot.append("ctrl-c", style="bold dim")
        foot.append(" to stop", style="dim")
    return Group(header, table, foot)
