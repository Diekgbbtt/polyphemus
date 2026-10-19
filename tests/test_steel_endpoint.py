"""Host-side unit tests for the shared Steel endpoint resolver (#390, D359-4).

Seam under test: `polymerhus.app.steel_endpoint.steel_browser_api_url`.
No docker, no network, no cloud key.

The value is the CLI's canonical self-hosted endpoint and carries the `/v1`
path (CLI 0.4.4 builds `{base_url}{path}`). The Python SDK appends `/v1`
itself, so the resolver returns the SDK-native origin form: one terminal
`/v1` and any trailing slash removed.
"""
import pytest

from polymerhus.app.steel_endpoint import steel_browser_api_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("\t\n", None),
        ("http://192.33.91.87:3000/v1", "http://192.33.91.87:3000"),
        ("http://192.33.91.87:3000/v1/", "http://192.33.91.87:3000"),
        ("http://192.33.91.87:3000", "http://192.33.91.87:3000"),
        ("http://192.33.91.87:3000/", "http://192.33.91.87:3000"),
        ("  http://192.33.91.87:3000/v1  ", "http://192.33.91.87:3000"),
        ("https://steel.internal.example/v1", "https://steel.internal.example"),
        ("https://steel.internal.example/api/v1", "https://steel.internal.example/api"),
        ("https://steel.internal.example/v2", "https://steel.internal.example/v2"),
    ],
)
def test_steel_browser_api_url(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    else:
        monkeypatch.setenv("STEEL_BROWSER_API_URL", raw)
    assert steel_browser_api_url() == expected


def test_resolver_reads_environment_at_call_time(monkeypatch):
    """The resolver re-reads the environment on every call (no import-time
    caching), so a container restart with a new value is picked up."""
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://h:3000/v1")
    assert steel_browser_api_url() == "http://h:3000"
    monkeypatch.setenv("STEEL_BROWSER_API_URL", "http://h2:3001/v1")
    assert steel_browser_api_url() == "http://h2:3001"
    monkeypatch.delenv("STEEL_BROWSER_API_URL", raising=False)
    assert steel_browser_api_url() is None
