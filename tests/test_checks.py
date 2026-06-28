"""Deterministic checks: we drive DNS against reserved names and the TCP check
against a socket we open and close ourselves — no external network needed."""
import socket

from netdoctor.checks import (
    _cert_days_left,
    _dest_ip,
    _parse_hops,
    check_dns,
    check_port,
)
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


def test_parse_hops_extracts_host_ip_rtt_and_silence():
    output = (
        "traceroute to example.com (93.184.216.34), 30 hops max\n"
        " 1  router.local (192.168.1.1)  1.2 ms\n"
        " 2  * * *\n"
        " 3  93.184.216.34  10.4 ms\n"
    )
    hops = _parse_hops(output)
    assert [h["hop"] for h in hops] == [1, 2, 3]

    assert hops[0]["responded"] is True
    assert hops[0]["host"] == "router.local"
    assert hops[0]["ip"] == "192.168.1.1"
    assert hops[0]["rtt_ms"] == 1.2

    assert hops[1]["responded"] is False
    assert hops[1]["host"] == "*"
    assert hops[1]["rtt_ms"] is None

    assert hops[2]["responded"] is True
    assert hops[2]["rtt_ms"] == 10.4


def test_parse_hops_survives_malformed_rtt():
    # Real routers occasionally emit a stray dot or a non-numeric timing field.
    # A loose pattern would capture "." and crash on float(".") — the parser must
    # treat the hop as responded-but-untimed rather than blow up the whole run.
    output = (
        "traceroute to example.com (93.184.216.34), 30 hops max\n"
        " 1  weird.host (10.0.0.1)  . ms\n"
        " 2  93.184.216.34 (93.184.216.34)  10.4 ms\n"
    )
    hops = _parse_hops(output)
    assert hops[0]["responded"] is True
    assert hops[0]["rtt_ms"] is None  # malformed timing → no number, not a crash
    assert hops[1]["rtt_ms"] == 10.4


def test_dest_ip_reads_banner_from_either_stream():
    banner = "traceroute to github.com (20.207.73.82), 12 hops max, 40 byte packets"
    hops_only = " 1  192.168.1.1 (192.168.1.1)  3.0 ms\n 2  * * *\n"

    # Linux: banner on stdout. macOS: banner on stderr, stdout starts at hop 1 —
    # the destination must NOT be misread as the first hop's IP.
    assert _dest_ip(banner + "\n" + hops_only, "") == "20.207.73.82"
    assert _dest_ip(hops_only, banner) == "20.207.73.82"

    # Windows tracert uses brackets and a different verb.
    win = "Tracing route to github.com [20.207.73.82]\nover a maximum of 30 hops:\n"
    assert _dest_ip(win, "") == "20.207.73.82"

    # No banner anywhere → no false destination.
    assert _dest_ip(hops_only, "") is None
