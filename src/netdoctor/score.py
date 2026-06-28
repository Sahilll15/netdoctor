"""Scoring: turn raw checks/probes into a quality scorecard.

Pure logic, no I/O — so the whole grading model is unit-tested in isolation
(see tests/test_score.py). A "sample" is a (succeeded, latency_ms) tuple from
one probe of the application.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Status

# Latency (ms) -> performance score breakpoints, linearly interpolated.
_PERF_POINTS = [
    (0, 100.0), (50, 99.0), (100, 95.0), (200, 88.0), (400, 78.0),
    (800, 62.0), (1500, 45.0), (3000, 25.0), (6000, 8.0),
]
_GRADES = [
    (97, "A+"), (93, "A"), (90, "A-"), (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"), (60, "D"), (0, "F"),
]


def perf_score(avg_ms: "float | None") -> float:
    """Map an average latency to a 0–100 performance score."""
    if avg_ms is None:
        return 0.0
    if avg_ms <= 0:
        return 100.0
    if avg_ms >= _PERF_POINTS[-1][0]:
        return 3.0
    for (x0, y0), (x1, y1) in zip(_PERF_POINTS, _PERF_POINTS[1:]):
        if avg_ms <= x1:
            t = (avg_ms - x0) / (x1 - x0)
            return round(y0 + t * (y1 - y0), 1)
    return 3.0


def stability_score(jitter_ms: float, avg_ms: float) -> float:
    """Score consistency from jitter (lower relative jitter = steadier = higher)."""
    if avg_ms <= 0:
        return 100.0
    ratio = jitter_ms / avg_ms
    for threshold, sc in [(0.10, 100.0), (0.25, 88.0), (0.50, 70.0), (1.0, 48.0), (2.0, 28.0)]:
        if ratio <= threshold:
            return sc
    return 15.0


def grade_for(score: float) -> str:
    for threshold, grade in _GRADES:
        if score >= threshold:
            return grade
    return "F"


def _percentile(sorted_vals: "list[float]", pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = max(1, math.ceil(pct / 100.0 * len(sorted_vals)))
    return sorted_vals[min(k, len(sorted_vals)) - 1]


@dataclass
class Scorecard:
    grade: str
    overall: float
    reachability: float
    performance: float
    stability: "float | None"
    success_rate: float
    n_ok: int
    n_total: int
    throughput_rps: "float | None"
    lat_min: "float | None" = None
    lat_avg: "float | None" = None
    lat_p50: "float | None" = None
    lat_p95: "float | None" = None
    lat_max: "float | None" = None
    jitter_ms: "float | None" = None
    samples: "list" = field(default_factory=list)

    def to_dict(self) -> dict:
        def r(x):
            return round(x, 1) if isinstance(x, float) else x
        return {
            "grade": self.grade,
            "overall": r(self.overall),
            "reachability": r(self.reachability),
            "performance": r(self.performance),
            "stability": r(self.stability) if self.stability is not None else None,
            "success_rate": r(self.success_rate),
            "probes": {"ok": self.n_ok, "total": self.n_total},
            "throughput_rps": self.throughput_rps,
            "latency_ms": {
                "min": r(self.lat_min), "avg": r(self.lat_avg), "p50": r(self.lat_p50),
                "p95": r(self.lat_p95), "max": r(self.lat_max), "jitter": r(self.jitter_ms),
            },
        }


def implicit_sample(rungs) -> "tuple[bool, float | None]":
    """Derive a single probe-equivalent from a completed ladder walk."""
    by_key = {r.key: r for r in rungs}
    http = by_key.get("http")
    if http is not None and http.status in (Status.OK, Status.WARN):
        return True, http.latency_ms
    port = by_key.get("port")
    if port is not None and port.status is Status.OK:
        return True, port.latency_ms
    return False, None


def build_scorecard(rungs, samples=None) -> Scorecard:
    """Build a scorecard from probe samples (or a single implicit sample from `rungs`)."""
    if not samples:
        samples = [implicit_sample(rungs)]
    n_total = len(samples)
    ok_lats = [lat for ok, lat in samples if ok and lat is not None]
    n_ok = sum(1 for ok, _ in samples if ok)
    success = 100.0 * n_ok / n_total if n_total else 0.0

    lat_min = lat_avg = lat_p50 = lat_p95 = lat_max = jitter = None
    stability = throughput = None
    if ok_lats:
        s = sorted(ok_lats)
        lat_min, lat_max = s[0], s[-1]
        lat_avg = sum(s) / len(s)
        lat_p50 = _percentile(s, 50)
        lat_p95 = _percentile(s, 95)
        jitter = math.sqrt(sum((x - lat_avg) ** 2 for x in s) / len(s))
        performance = perf_score(lat_avg)
        if len(s) >= 2:
            stability = stability_score(jitter, lat_avg)
        if lat_avg > 0:
            throughput = round(1000.0 / lat_avg, 1)
    else:
        performance = 0.0

    reachability = success
    if stability is not None:
        overall = 0.50 * reachability + 0.35 * performance + 0.15 * stability
    else:
        overall = 0.55 * reachability + 0.45 * performance

    return Scorecard(
        grade=grade_for(overall),
        overall=overall,
        reachability=reachability,
        performance=performance,
        stability=stability,
        success_rate=success,
        n_ok=n_ok,
        n_total=n_total,
        throughput_rps=throughput,
        lat_min=lat_min, lat_avg=lat_avg, lat_p50=lat_p50,
        lat_p95=lat_p95, lat_max=lat_max, jitter_ms=jitter,
        samples=[lat for _ok, lat in samples],
    )
