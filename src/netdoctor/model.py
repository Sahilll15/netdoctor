"""Core data types: the rungs of the debugging ladder and the final verdict.

The model is deliberately free of any I/O or rendering so it can be unit-tested
in isolation — see tests/test_diagnose.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    """Result of a single check. Ordered loosely from best to worst."""

    OK = "ok"      # the check passed
    WARN = "warn"  # responded, but with a caveat (e.g. HTTP 5xx, ICMP blocked)
    FAIL = "fail"  # the check failed outright
    SKIP = "skip"  # the check did not run (e.g. DNS failed, so downstream is moot)


@dataclass
class Rung:
    """One rung of the ladder: a single diagnostic check and its outcome.

    `core` marks whether this rung counts toward the verdict. DNS, the TCP port,
    and the HTTP check are core; ping and traceroute are advisory (many healthy
    hosts block ICMP, so a ping failure must never be read as an outage).
    """

    key: str
    title: str
    status: Status = Status.SKIP
    detail: str = ""
    latency_ms: "float | None" = None
    hint: str = ""
    core: bool = True
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status.value,
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "hint": self.hint,
            "core": self.core,
            "data": self.data,
        }


class Verdict(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class Diagnosis:
    verdict: Verdict
    headline: str
    notes: "list[str]" = field(default_factory=list)
    broken_rung: "str | None" = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "headline": self.headline,
            "notes": self.notes,
            "broken_rung": self.broken_rung,
        }


_VERDICT_RANK = {Verdict.HEALTHY: 0, Verdict.DEGRADED: 1, Verdict.UNHEALTHY: 2}


def worse(a: str, b: str) -> str:
    """Return the worse of two verdict strings (for aggregating a fleet exit code)."""
    rank = {"healthy": 0, "degraded": 1, "unhealthy": 2}
    return a if rank[a] >= rank[b] else b


def worst_verdict(verdicts: "list[Verdict]") -> Verdict:
    """The worst verdict in a collection (defaults to HEALTHY when empty)."""
    return max(verdicts, key=lambda v: _VERDICT_RANK[v], default=Verdict.HEALTHY)


def _dedupe(items: "list[str]") -> "list[str]":
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def diagnose(rungs: "list[Rung]", target: str) -> Diagnosis:
    """Reduce a list of completed rungs to a single verdict.

    Rules:
      * any CORE rung that FAILed  -> UNHEALTHY (named by the first such rung)
      * else any CORE rung WARNing -> DEGRADED
      * else                       -> HEALTHY
    Advisory (non-core) warnings never change the verdict — they only add notes.
    """
    considered = [r for r in rungs if r.status is not Status.SKIP]
    core = [r for r in considered if r.core]

    advisory_notes = [r.hint for r in considered if r.status is Status.WARN]

    first_fail = next((r for r in core if r.status is Status.FAIL), None)
    if first_fail is not None:
        return Diagnosis(
            verdict=Verdict.UNHEALTHY,
            headline=f"{target} is not healthy — first failure at “{first_fail.title}”.",
            notes=_dedupe([first_fail.hint, *advisory_notes]),
            broken_rung=first_fail.key,
        )

    core_warn = next((r for r in core if r.status is Status.WARN), None)
    if core_warn is not None:
        return Diagnosis(
            verdict=Verdict.DEGRADED,
            headline=f"{target} is reachable but degraded — see “{core_warn.title}”.",
            notes=_dedupe(advisory_notes),
            broken_rung=core_warn.key,
        )

    return Diagnosis(
        verdict=Verdict.HEALTHY,
        headline=f"{target} is reachable and responding.",
        notes=_dedupe(advisory_notes),
        broken_rung=None,
    )
