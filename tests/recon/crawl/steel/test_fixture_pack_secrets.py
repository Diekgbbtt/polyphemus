"""Guard: the fixture pack carries only placeholder hosts and no secrets.

The pack is checked in and copied into every later ticket. A live host, a
cookie, or a token here would leak into test output and eventually into a
report, so the whole tree is scanned rather than trusted.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from tests.recon.crawl.steel.fixtures import FIXTURES_ROOT

URL_RE = re.compile(r"(?:https?|wss?)://[^\s\"'<>\\]+")
HOST_RE = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:app|cloud|com|dev|internal|invalid|io|local|net|org|test)\b",
    re.IGNORECASE,
)
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
LOCALHOST_RE = re.compile(r"\blocalhost\b", re.IGNORECASE)
TOKEN_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._-]+|eyj[a-z0-9._-]{10,}|ghp_[a-z0-9]{20,}|akia[0-9a-z]{16})"
)
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "password",
    "refresh_token",
    "secret",
    "set-cookie",
    "token",
    "access_token",
}


def _fixture_files():
    return sorted(
        path
        for path in FIXTURES_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def _walk_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def test_every_fixture_url_uses_the_placeholder_origin():
    seen = []
    offenders = []
    for path in _fixture_files():
        for url in URL_RE.findall(path.read_text(encoding="utf-8")):
            host = urlsplit(url).hostname or ""
            seen.append(host)
            if host != "example.test" and not host.endswith(".example.test"):
                offenders.append((path.name, url))

    assert seen
    assert offenders == []


def test_no_fixture_names_a_live_host():
    offenders = []
    for path in _fixture_files():
        text = path.read_text(encoding="utf-8")
        for host in HOST_RE.findall(text):
            if host != "example.test" and not host.lower().endswith(".example.test"):
                offenders.append((path.name, host))
        offenders.extend((path.name, ip) for ip in IPV4_RE.findall(text))
        if LOCALHOST_RE.search(text):
            offenders.append((path.name, "localhost"))

    assert offenders == []


def test_no_fixture_carries_a_sensitive_key_or_token_value():
    json_files = 0
    key_offenders = []
    token_offenders = []
    for path in _fixture_files():
        text = path.read_text(encoding="utf-8")
        token_offenders.extend((path.name, match) for match in TOKEN_RE.findall(text))
        if path.suffix != ".json":
            continue
        json_files += 1
        for key, value in _walk_json(json.loads(text)):
            if key.lower() in SENSITIVE_KEYS and value not in (None, "", [], {}):
                key_offenders.append((path.name, key))

    assert json_files
    assert key_offenders == []
    assert token_offenders == []
