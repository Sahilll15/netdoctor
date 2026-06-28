"""Deterministic checks: we drive DNS against reserved names and the TCP check
against a socket we open and close ourselves — no external network needed."""
import socket

from netdoctor.checks import _cert_days_left, _parse_hops, check_dns, check_port
from netdoctor.model import Status


def test_dns_resolves_localhost():
    rung = check_dns("localhost", timeout=2)
    assert rung.status is Status.OK
    assert rung.data["primary"] in ("127.0.0.1", "::1")


def test_dns_fails_on_reserved_invalid_tld():
    # `.invalid` is reserved by RFC 2606 and must never resolve.
    rung = check_dns("nope.invalid", timeout=2)
    assert rung.status is Status.FAIL
    assert rung.hint  # a remediation hint is always offered on failure


def test_port_open_then_closed():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))  # ephemeral port we control
    srv.listen(1)
    port = srv.getsockname()[1]

    opened = check_port("127.0.0.1", port, timeout=2)
    assert opened.status is Status.OK
    assert opened.detail == "open"

    srv.close()
    closed = check_port("127.0.0.1", port, timeout=2)
    assert closed.status is Status.FAIL
    assert closed.hint


def test_cert_days_left_handles_missing_cert():
    assert _cert_days_left(None) == ("", None)
    assert _cert_days_left({}) == ("", None)


def test_parse_hops_marks_silent_hops():
    output = (
        "traceroute to example.com (93.184.216.34), 30 hops max\n"
        " 1  router.local (192.168.1.1)  1.2 ms\n"
        " 2  * * *\n"
        " 3  93.184.216.34  10.4 ms\n"
    )
    hops = _parse_hops(output)
    assert [h["hop"] for h in hops] == [1, 2, 3]
    assert hops[1]["responded"] is False
    assert hops[2]["responded"] is True
