"""The verdict engine is pure logic — these tests need no network at all."""
from netdoctor.model import Rung, Status, Verdict, diagnose


def _rung(key, status, core=True, hint=""):
    return Rung(key=key, title=key.upper(), status=status, core=core, hint=hint)


def test_all_core_ok_is_healthy():
    rungs = [
        _rung("dns", Status.OK),
        _rung("ping", Status.OK, core=False),
        _rung("port", Status.OK),
        _rung("http", Status.OK),
    ]
    diag = diagnose(rungs, "example.com")
    assert diag.verdict is Verdict.HEALTHY
    assert diag.broken_rung is None


def test_blocked_ping_does_not_downgrade_a_healthy_host():
    # The whole point of the tool: ICMP blocked != down.
    rungs = [
        _rung("dns", Status.OK),
        _rung("ping", Status.WARN, core=False, hint="icmp blocked"),
        _rung("port", Status.OK),
        _rung("http", Status.OK),
    ]
    diag = diagnose(rungs, "example.com")
    assert diag.verdict is Verdict.HEALTHY
    assert "icmp blocked" in diag.notes  # advisory note still surfaced


def test_core_warning_is_degraded():
    rungs = [
        _rung("dns", Status.OK),
        _rung("port", Status.OK),
        _rung("http", Status.WARN, hint="503"),
    ]
    diag = diagnose(rungs, "example.com")
    assert diag.verdict is Verdict.DEGRADED
    assert diag.broken_rung == "http"


def test_core_failure_is_unhealthy_and_named():
    rungs = [
        _rung("dns", Status.OK),
        _rung("port", Status.FAIL, hint="closed"),
        _rung("http", Status.SKIP),
    ]
    diag = diagnose(rungs, "example.com")
    assert diag.verdict is Verdict.UNHEALTHY
    assert diag.broken_rung == "port"
    assert "closed" in diag.notes


def test_first_failure_wins():
    rungs = [
        _rung("dns", Status.FAIL, hint="no such host"),
        _rung("port", Status.SKIP),
        _rung("http", Status.SKIP),
    ]
    diag = diagnose(rungs, "example.com")
    assert diag.verdict is Verdict.UNHEALTHY
    assert diag.broken_rung == "dns"
