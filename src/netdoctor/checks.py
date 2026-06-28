"""The diagnostic checks. Each returns a completed Rung; none of them print.

This is a faithful, automated walk of the DevOps "debugging ladder":
    DNS resolve -> ping -> TCP port -> HTTP/TLS  (+ optional traceroute)
"""
from __future__ import annotations

import http.client
import platform
import re
import socket
import ssl
import subprocess
import time

from .model import Rung, Status

_PING_TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms")
_HOP_RE = re.compile(r"^\s*(\d+)\s+(.*)$")

ICMP_HINT = (
    "No ICMP reply — many hosts and firewalls block ping, so this alone does NOT "
    "mean the host is down. The TCP port and HTTP checks below are authoritative."
)


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


# ---------------------------------------------------------------------------
# Rung 1 — DNS: does the name resolve to an IP?
# ---------------------------------------------------------------------------
def check_dns(host: str, timeout: float) -> Rung:
    rung = Rung(key="dns", title="DNS resolution", core=True)
    start = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = f"could not resolve ({exc.strerror or exc})"
        rung.hint = (
            f"Name does not resolve. Check the spelling, try another resolver "
            f"(`dig @1.1.1.1 {host}`), or verify the domain's nameservers."
        )
        return rung

    rung.latency_ms = _elapsed_ms(start)
    ips: "list[str]" = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)

    primary = ips[0]
    extra = f"  (+{len(ips) - 1} more)" if len(ips) > 1 else ""
    rung.status = Status.OK
    rung.detail = f"{host} → {primary}{extra}"
    rung.data = {"ips": ips, "primary": primary}
    return rung


# ---------------------------------------------------------------------------
# Rung 2 — Ping: is the host reachable at all? (advisory only)
# ---------------------------------------------------------------------------
def check_ping(host: str, timeout: float) -> Rung:
    rung = Rung(key="ping", title="Ping (ICMP)", core=False)
    system = platform.system().lower()
    timeout_s = max(1, int(round(timeout)))
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    elif system == "darwin":
        cmd = ["ping", "-c", "1", "-t", str(timeout_s), host]
    else:  # linux and friends
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), host]

    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
    except FileNotFoundError:
        rung.status = Status.SKIP
        rung.detail = "ping not available on this system"
        return rung
    except subprocess.TimeoutExpired:
        rung.status = Status.WARN
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "no reply (timed out)"
        rung.hint = ICMP_HINT
        return rung

    if proc.returncode == 0:
        match = _PING_TIME_RE.search(proc.stdout)
        rung.status = Status.OK
        rung.latency_ms = float(match.group(1)) if match else _elapsed_ms(start)
        rung.detail = "host replied"
    else:
        rung.status = Status.WARN
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "no reply (ICMP likely blocked)"
        rung.hint = ICMP_HINT
    return rung


# ---------------------------------------------------------------------------
# Rung 3 — TCP port: is the specific port open?
# ---------------------------------------------------------------------------
def check_port(host: str, port: int, timeout: float) -> Rung:
    rung = Rung(key="port", title=f"TCP port {port}", core=True)
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except ConnectionRefusedError:
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "connection refused (port closed)"
        rung.hint = (
            f"Port {port} actively refused the connection — the host is up but nothing "
            f"is listening there. Check the service is running and bound to {port}."
        )
        return rung
    except (socket.timeout, TimeoutError):
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "timed out (filtered?)"
        rung.hint = (
            f"Port {port} did not answer before the timeout — typically a firewall / "
            f"security group silently dropping packets. Check inbound rules allow {port}."
        )
        return rung
    except OSError as exc:
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = f"unreachable ({exc.strerror or exc})"
        rung.hint = f"Could not open a socket to {host}:{port} — {exc.strerror or exc}."
        return rung

    rung.status = Status.OK
    rung.latency_ms = _elapsed_ms(start)
    rung.detail = "open"
    return rung


# ---------------------------------------------------------------------------
# Rung 4 — HTTP/TLS: does the application actually respond?
# ---------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    """A verifying TLS context that also trusts certifi's up-to-date CA bundle.

    Python's ssl uses OpenSSL's default store, which is often stale (and basically
    empty on a frozen PyInstaller binary) — so newer roots like Let's Encrypt's
    ISRG chain fail with "unable to get local issuer certificate" even though every
    browser trusts them. Loading certifi on top fixes those false negatives without
    weakening verification.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass  # fall back to the system default store
    return ctx


def _cert_days_left(cert: "dict | None") -> "tuple[str, int | None]":
    if not cert or "notAfter" not in cert:
        return "", None
    try:
        expires = ssl.cert_time_to_seconds(cert["notAfter"])
        days = int((expires - time.time()) // 86400)
        return f"cert {days}d left", days
    except (ValueError, OverflowError):
        return "", None


def check_http(host: str, port: int, scheme: str, path: str, timeout: float) -> Rung:
    title = "HTTPS" if scheme == "https" else "HTTP"
    path = path or "/"
    rung = Rung(key="http", title=f"{title} {path}", core=True)
    start = time.perf_counter()
    tls_bits = ""
    try:
        if scheme == "https":
            ctx = _ssl_context()
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)

        # Time the request in phases: connect (+TLS) then time-to-first-byte.
        t_connect = time.perf_counter()
        conn.connect()
        connect_ms = (time.perf_counter() - t_connect) * 1000.0
        if scheme == "https" and conn.sock is not None:
            tls_version = conn.sock.version()
            cert_note, cert_days = _cert_days_left(conn.sock.getpeercert())
            rung.data["tls"] = tls_version
            if cert_days is not None:
                rung.data["cert_days_left"] = cert_days
            tls_bits = f" · {tls_version}" + (f" · {cert_note}" if cert_note else "")

        t_req = time.perf_counter()
        conn.request(
            "GET", path,
            headers={"User-Agent": "netdoctor/0.1", "Accept": "*/*", "Connection": "close"},
        )
        resp = conn.getresponse()
        ttfb_ms = (time.perf_counter() - t_req) * 1000.0
        status_code, reason = resp.status, resp.reason
        rung.data["timing"] = {"connect_ms": round(connect_ms, 1), "ttfb_ms": round(ttfb_ms, 1)}
        conn.close()
    except ssl.SSLCertVerificationError as exc:
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "TLS certificate did not verify"
        rung.hint = (
            f"TLS verification failed ({getattr(exc, 'verify_message', None) or exc}). "
            f"The cert may be expired, self-signed, or issued for a different hostname."
        )
        return rung
    except (socket.timeout, TimeoutError):
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = "no HTTP response (timed out)"
        rung.hint = (
            "TCP connected but the server never returned an HTTP response — the app may "
            "be hung or overloaded. Check application logs and upstream health."
        )
        return rung
    except (ConnectionError, OSError) as exc:
        rung.status = Status.FAIL
        rung.latency_ms = _elapsed_ms(start)
        rung.detail = f"no HTTP response ({getattr(exc, 'strerror', None) or exc})"
        rung.hint = (
            "Could not complete an HTTP request. Confirm the scheme (http vs https) and "
            "that a web server is actually listening on this port."
        )
        return rung

    rung.latency_ms = _elapsed_ms(start)
    rung.data["status_code"] = status_code
    label = f"{status_code} {reason}".strip()

    if status_code < 400:
        rung.status = Status.OK
        rung.detail = f"{label}{tls_bits}"
    elif status_code < 500:
        rung.status = Status.WARN
        rung.detail = f"{label}{tls_bits}"
        rung.hint = (
            f"Server responded {status_code} — it is up, but returned a client error for "
            f"{path}. Often expected (auth required, wrong path)."
        )
    else:
        rung.status = Status.WARN
        rung.detail = f"{label}{tls_bits}"
        rung.hint = (
            f"Server responded {status_code} — reachable but erroring. "
            f"Check application logs / upstream dependencies."
        )

    cert_days = rung.data.get("cert_days_left")
    if cert_days is not None and cert_days < 14 and rung.status is Status.OK:
        rung.status = Status.WARN
        rung.hint = f"TLS certificate expires in {cert_days} day(s) — renew it before it lapses."
    return rung


# ---------------------------------------------------------------------------
# Optional rung — traceroute: what path do packets take? (advisory)
# ---------------------------------------------------------------------------
def _dest_ip(*streams: str) -> "str | None":
    """Pull the target IP from traceroute's banner, wherever the OS prints it.

    macOS sends the "traceroute to host (ip)" banner to stderr, Linux to stdout,
    and Windows tracert prints "Tracing route to host [ip]". We scan every stream
    for that banner instead of assuming it leads stdout — otherwise the first
    hop's IP gets mistaken for the destination (and a dark route reads as reached).
    """
    for stream in streams:
        for line in stream.splitlines():
            low = line.lstrip().lower()
            if low.startswith("traceroute to") or low.startswith("tracing route"):
                m = re.search(r"[\(\[]([0-9a-fA-F:.]+)[\)\]]", line)
                return m.group(1) if m else None
    return None


def _parse_hops(output: str) -> "list[dict]":
    hops = []
    for line in output.splitlines():
        match = _HOP_RE.match(line)
        if not match:
            continue
        rest = match.group(2).strip()
        responded = rest.replace("*", "").strip() != ""
        host = ip = rtt = None
        if responded:
            ip_m = re.search(r"\(([0-9a-fA-F:.]+)\)", rest)
            if ip_m:
                ip = ip_m.group(1)
            first = rest.split()[0]
            host = ip if first == "*" else first
            # Require a real number before "ms"; some routers emit stray dots
            # or malformed timing fields that a looser pattern would capture.
            rtt_m = re.search(r"(\d+(?:\.\d+)?)\s*ms", rest)
            if rtt_m:
                try:
                    rtt = float(rtt_m.group(1))
                except ValueError:
                    rtt = None
        hops.append({
            "hop": int(match.group(1)),
            "host": host or "*",
            "ip": ip,
            "rtt_ms": rtt,
            "responded": responded,
            "raw": rest,
        })
    return hops


def measure(host: str, port: int, scheme: str, path: str, method: str, timeout: float):
    """One probe of the application for benchmarking. Returns (succeeded, latency_ms).

    method="http" times a full HTTP round trip; method="tcp" times a TCP connect.
    """
    if method == "http":
        rung = check_http(host, port, scheme, path, timeout)
        return rung.status in (Status.OK, Status.WARN), rung.latency_ms
    rung = check_port(host, port, timeout)
    return rung.status is Status.OK, rung.latency_ms


def check_trace(host: str, timeout: float, max_hops: int = 12) -> Rung:
    rung = Rung(key="trace", title="Traceroute", core=False)
    system = platform.system().lower()
    per_hop = 1  # one second per hop, one probe per hop -> fast even when blocked
    if system == "windows":
        cmd = ["tracert", "-h", str(max_hops), "-w", str(per_hop * 1000), host]
    else:
        # -q 1: one probe per hop -> a blocked trace fails fast instead of hanging.
        cmd = ["traceroute", "-q", "1", "-m", str(max_hops), "-w", str(per_hop), host]

    # Hard wall-clock cap so default-on traceroute never stalls a quick run.
    hard_cap = min(9, max_hops * per_hop + 3)
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=hard_cap)
    except FileNotFoundError:
        rung.status = Status.SKIP
        rung.detail = "traceroute not installed"
        return rung
    except subprocess.TimeoutExpired:
        rung.status = Status.WARN
        rung.detail = "trace timed out (route may block traceroute)"
        return rung

    hops = _parse_hops(proc.stdout)
    rung.latency_ms = _elapsed_ms(start)

    dest_ip = _dest_ip(proc.stderr or "", proc.stdout or "")
    if dest_ip:
        reached = any(h["responded"] and h["ip"] == dest_ip for h in hops)
    else:
        reached = bool(hops) and hops[-1]["responded"]
    last_resp = max((h["hop"] for h in hops if h["responded"]), default=0)

    rung.data["hops"] = hops
    rung.data["dest_ip"] = dest_ip
    rung.data["reached"] = reached
    rung.status = Status.OK if hops else Status.WARN
    rung.detail = f"{len(hops)} hops · " + (
        "destination reached" if reached else f"silent after hop {last_resp}"
    )
    return rung
