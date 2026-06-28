"""Target parsing must handle bare hosts, host:port, and full URLs."""
import pytest

from netdoctor.cli import parse_target


@pytest.mark.parametrize(
    "raw, host, port, scheme, path",
    [
        ("github.com",                       "github.com",      443, "https", "/"),
        ("github.com:8080",                  "github.com",      8080, "http", "/"),
        ("db.internal:5432",                 "db.internal",     5432, "http", "/"),
        ("https://api.example.com/health",   "api.example.com", 443, "https", "/health"),
        ("http://example.com",               "example.com",     80,  "http", "/"),
        ("https://example.com:8443/v1/ping", "example.com",     8443, "https", "/v1/ping"),
        ("127.0.0.1:22",                     "127.0.0.1",       22,  "http", "/"),
    ],
)
def test_parse_target(raw, host, port, scheme, path):
    t = parse_target(raw, None, None, None)
    assert (t.host, t.port, t.scheme, t.path) == (host, port, scheme, path)


def test_explicit_flags_win_over_url():
    t = parse_target("https://example.com/health", port_opt=9000, scheme_opt="http", path_opt="/up")
    assert (t.host, t.port, t.scheme, t.path) == ("example.com", 9000, "http", "/up")
