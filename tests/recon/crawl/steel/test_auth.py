"""Seam under test: `AuthOracle` through a fake page fetch.

Spec: `docs/design/steel-crawl-spec.md` sections 2.1, 4.5, and 12; seam 2 of
`docs/design/steel-crawl-implementation-plan.md` section 3. Every test drives
the oracle's public `check` and asserts the verdict; the fake `fetch_fn` stands
exactly where the production adapter runs the session client's `eval` command.
"""
from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.auth import (
    AuthOracle,
    AuthPreconditionFailed,
    session_fetch_fn,
)
from polymerhus.recon.crawl.steel.session import SessionMissing, SteelSessionClient
from tests.recon.crawl.steel.fixtures import load_cli
from tests.recon.crawl.steel.support import FakeExecFn

PAGE_URL = "https://app.example.test/"
PROBE_PATH = "/api/authentication"
PROBE_URL = "https://app.example.test/api/authentication"


class FakeFetch:
    """A queued stand-in for the oracle's `fetch_fn` seam.

    It mirrors the production contract - one resolved URL in, one browser
    fetch record out - and records every URL it was asked to fetch.
    """

    def __init__(self, *payloads: Mapping[str, Any]) -> None:
        self.urls: list[str] = []
        self._queue: deque[dict[str, Any]] = deque(dict(p) for p in payloads)

    def __call__(self, url: str) -> Mapping[str, Any]:
        self.urls.append(url)
        if not self._queue:
            raise AssertionError(f"no queued probe payload for {url}")
        return self._queue.popleft()


def probe(**overrides: Any) -> dict[str, Any]:
    """One authenticated browser fetch record, with named fields overridden."""
    payload: dict[str, Any] = {
        "status": 200,
        "redirected": False,
        "url": PROBE_URL,
        "body": '{"authenticated":true}',
    }
    payload.update(overrides)
    return payload


def test_a_2xx_probe_without_a_redirect_is_authenticated():
    fetch = FakeFetch(probe())

    verdict = AuthOracle(
        fetch_fn=fetch, page_url=PAGE_URL, probe_url=PROBE_PATH
    ).check()

    assert fetch.urls == [PROBE_URL]
    assert verdict.classification == "authenticated"
    assert verdict.probe_url == PROBE_URL
    assert verdict.probe_source == "overview.auth_probe.url"
    assert verdict.status == 200
    assert verdict.redirected is False
    assert verdict.final_url == PROBE_URL
    assert verdict.body == '{"authenticated":true}'
    assert verdict.note == ""


@pytest.mark.parametrize(
    "payload",
    [
        probe(status=401, body="unauthorized"),
        probe(status=403, body="forbidden"),
        probe(status=302, redirected=True, url="https://app.example.test/login"),
        probe(status=200, redirected=True, url="https://app.example.test/home"),
    ],
)
def test_a_rejected_probe_is_unauthenticated_and_fails_the_precondition(payload):
    oracle = AuthOracle(
        fetch_fn=FakeFetch(payload), page_url=PAGE_URL, probe_url=PROBE_PATH
    )

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        oracle.check()

    failure = excinfo.value
    assert failure.code == "auth_precondition_failed"
    assert failure.verdict.classification == "unauthenticated"
    assert failure.verdict.status == payload["status"]
    assert failure.verdict.redirected is payload["redirected"]
    assert failure.verdict.final_url == payload["url"]
    assert "unauthenticated" in str(failure)


@pytest.mark.parametrize(
    "payload",
    [
        probe(status=404, body="not found"),
        probe(status=500, body="server error"),
        probe(status=400),
        probe(status=0),
        probe(redirected=None),
        {},
    ],
)
def test_any_other_probe_outcome_is_indeterminate_and_fails_closed(payload):
    oracle = AuthOracle(
        fetch_fn=FakeFetch(payload), page_url=PAGE_URL, probe_url=PROBE_PATH
    )

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        oracle.check()

    failure = excinfo.value
    assert failure.verdict.classification == "indeterminate"
    assert failure.code == "auth_precondition_failed"
    assert failure.verdict.probe_url == PROBE_URL


def test_the_oracle_fetches_once_and_a_later_check_reuses_the_cached_verdict():
    fetch = FakeFetch(probe())
    oracle = AuthOracle(fetch_fn=fetch, page_url=PAGE_URL, probe_url=PROBE_PATH)

    first = oracle.check()
    second = oracle.check()

    assert fetch.urls == [PROBE_URL]
    assert oracle.fetch_count == 1
    assert second == first


@pytest.mark.parametrize(
    ("page_url", "probe_url", "expected"),
    [
        (
            "https://app.example.test/",
            "/api/authentication",
            "https://app.example.test/api/authentication",
        ),
        (
            "http://172.20.0.1:49017/some/page?x=1",
            "/api/authentication",
            "http://172.20.0.1:49017/api/authentication",
        ),
        (
            "https://app.example.test/deep/page",
            "probe",
            "https://app.example.test/deep/probe",
        ),
        (
            "https://app.example.test/",
            "https://other.example.test/api/authentication",
            "https://other.example.test/api/authentication",
        ),
        (
            "https://app.example.test/",
            "  /api/authentication  ",
            "https://app.example.test/api/authentication",
        ),
    ],
)
def test_a_probe_path_resolves_against_the_loaded_page_and_an_absolute_probe_is_used(
    page_url, probe_url, expected
):
    fetch = FakeFetch(probe(url=expected))

    verdict = AuthOracle(
        fetch_fn=fetch, page_url=page_url, probe_url=probe_url
    ).check()

    assert fetch.urls == [expected]
    assert verdict.probe_url == expected


@pytest.mark.parametrize("probe_url", [None, "", "   "])
def test_a_missing_probe_is_logged_and_falls_back_to_the_legacy_surface_gate(
    caplog, probe_url
):
    fetch = FakeFetch(
        probe(status=200, redirected=False, url=PAGE_URL, body="<h1>Dashboard</h1>")
    )
    oracle = AuthOracle(fetch_fn=fetch, page_url=PAGE_URL, probe_url=probe_url)

    with caplog.at_level(
        logging.WARNING, logger="polymerhus.recon.crawl.steel.auth"
    ):
        verdict = oracle.check()

    assert fetch.urls == [PAGE_URL]
    assert verdict.classification == "authenticated"
    assert verdict.probe_source == "legacy_surface_gate"
    assert verdict.probe_url == PAGE_URL
    assert verdict.note == "overview.auth_probe.url is missing"
    assert "overview.auth_probe.url is missing" in caplog.text
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


@pytest.mark.parametrize(
    ("payload", "login_url", "reason"),
    [
        (
            probe(status=200, url="https://app.example.test/login"),
            None,
            "login_redirect",
        ),
        (
            probe(status=200, url="https://app.example.test/session/new"),
            "https://app.example.test/session/new",
            "login_redirect",
        ),
        (probe(status=401, body="unauthorized"), None, "http_401"),
        (probe(status=403, body="forbidden"), None, "http_403"),
        (probe(status=302, url="https://app.example.test/home"), None, "http_302"),
        (
            probe(
                status=200,
                body=(
                    '<form action="/session">'
                    '<input type="password" name="password">'
                    "<button>Sign in</button></form>"
                ),
            ),
            None,
            "login_form",
        ),
    ],
)
def test_the_legacy_surface_gate_rejects_and_never_continues_anonymously(
    payload, login_url, reason
):
    oracle = AuthOracle(
        fetch_fn=FakeFetch(payload),
        page_url=PAGE_URL,
        probe_url=None,
        login_url=login_url,
    )

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        oracle.check()

    verdict = excinfo.value.verdict
    assert verdict.classification == "unauthenticated"
    assert verdict.probe_source == "legacy_surface_gate"
    assert verdict.final_url == payload["url"]
    assert verdict.note == f"overview.auth_probe.url is missing; {reason}"


@pytest.mark.parametrize(
    "payload",
    [
        probe(status=500, body="server error"),
        probe(status=404, body="not found"),
        {},
    ],
)
def test_an_ambiguous_legacy_surface_is_indeterminate_and_fails_closed(payload):
    oracle = AuthOracle(fetch_fn=FakeFetch(payload), page_url=PAGE_URL, probe_url=None)

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        oracle.check()

    assert excinfo.value.verdict.classification == "indeterminate"
    assert excinfo.value.verdict.probe_source == "legacy_surface_gate"


def test_a_change_password_form_on_an_authenticated_page_is_not_a_login_form():
    payload = probe(
        status=200,
        body=(
            "<h1>Account</h1><form><input type=\"password\" name=\"new_password\">"
            "<button>Change password</button></form>"
        ),
    )
    oracle = AuthOracle(fetch_fn=FakeFetch(payload), page_url=PAGE_URL, probe_url=None)

    verdict = oracle.check()

    assert verdict.classification == "authenticated"
    assert verdict.note == "overview.auth_probe.url is missing"


def test_a_followed_non_login_redirect_on_the_surface_is_not_a_login_redirect():
    payload = probe(status=200, redirected=True, url="https://app.example.test/home")
    oracle = AuthOracle(fetch_fn=FakeFetch(payload), page_url=PAGE_URL, probe_url=None)

    verdict = oracle.check()

    assert verdict.classification == "authenticated"
    assert verdict.redirected is True
    assert verdict.final_url == "https://app.example.test/home"


def test_a_failed_verdict_is_cached_too_and_never_refetched():
    fetch = FakeFetch(probe(status=401, body="unauthorized"))
    oracle = AuthOracle(fetch_fn=fetch, page_url=PAGE_URL, probe_url=PROBE_PATH)

    for _ in range(2):
        with pytest.raises(AuthPreconditionFailed) as excinfo:
            oracle.check()
        assert excinfo.value.verdict.classification == "unauthenticated"

    assert fetch.urls == [PROBE_URL]
    assert oracle.fetch_count == 1


def _probe_envelope(**overrides: Any) -> dict[str, Any]:
    """One `eval` CLI envelope whose `data` is the probe script's JSON string."""
    return {"success": True, "data": json.dumps(probe(**overrides))}


def _attached_client(probe_envelope):
    exec_fn = FakeExecFn(load_cli("catalogue"), load_cli("session"), probe_envelope)
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")
    return client, exec_fn


def test_the_default_adapter_runs_one_eval_and_returns_the_fetch_record():
    client, exec_fn = _attached_client(_probe_envelope(body="ok"))

    verdict = AuthOracle(
        fetch_fn=session_fetch_fn(client), page_url=PAGE_URL, probe_url=PROBE_PATH
    ).check()

    command = exec_fn.last_command
    assert command[:3] == ["steel", "browser", "eval"]
    # Options precede the positional script.
    assert command[3:6] == ["--session", "crawl-fixture", "--json"]
    assert command[6] == (
        "(async()=>{"
        'const r=await fetch("https://app.example.test/api/authentication",'
        '{redirect:"follow",credentials:"include",cache:"no-store"});'
        "const t=await r.text();"
        "return JSON.stringify({status:r.status,redirected:r.redirected,"
        "url:r.url,body:t.slice(0,200)});"
        "})()"
    )
    assert verdict.classification == "authenticated"
    assert verdict.body == "ok"


def test_the_adapter_accepts_an_already_parsed_fetch_record():
    client, _ = _attached_client(
        {"success": True, "data": probe(status=401, body="unauthorized")}
    )

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        AuthOracle(
            fetch_fn=session_fetch_fn(client),
            page_url=PAGE_URL,
            probe_url=PROBE_PATH,
        ).check()

    assert excinfo.value.verdict.classification == "unauthenticated"
    assert excinfo.value.verdict.status == 401


@pytest.mark.parametrize("data", ["not json at all", None, ["a", "list"]])
def test_an_unreadable_eval_payload_fails_closed_as_indeterminate(data):
    client, _ = _attached_client({"success": True, "data": data})

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        AuthOracle(
            fetch_fn=session_fetch_fn(client),
            page_url=PAGE_URL,
            probe_url=PROBE_PATH,
        ).check()

    assert excinfo.value.verdict.classification == "indeterminate"


def test_a_cli_failure_during_the_probe_stays_a_session_error():
    exec_fn = FakeExecFn(
        load_cli("catalogue"),
        load_cli("session"),
        {"success": False, "error": "session_missing"},
    )
    client = SteelSessionClient(exec_fn=exec_fn)
    client.attach("crawl-fixture")

    with pytest.raises(SessionMissing):
        AuthOracle(
            fetch_fn=session_fetch_fn(client),
            page_url=PAGE_URL,
            probe_url=PROBE_PATH,
        ).check()


def test_the_probe_body_is_capped_at_200_characters():
    long_body = "x" * 500

    verdict = AuthOracle(
        fetch_fn=FakeFetch(probe(body=long_body)),
        page_url=PAGE_URL,
        probe_url=PROBE_PATH,
    ).check()

    assert verdict.body == "x" * 200
    assert len(verdict.body) == 200


def test_a_body_marker_never_turns_a_rejection_into_a_pass():
    marker = "authenticated admin dashboard"

    oracle = AuthOracle(
        fetch_fn=FakeFetch(probe(status=401, body=marker)),
        page_url=PAGE_URL,
        probe_url=PROBE_PATH,
    )

    with pytest.raises(AuthPreconditionFailed) as excinfo:
        oracle.check()

    assert excinfo.value.verdict.classification == "unauthenticated"
    assert excinfo.value.verdict.body == marker


def test_an_empty_body_on_a_clean_2xx_still_authenticates():
    verdict = AuthOracle(
        fetch_fn=FakeFetch(probe(body="")),
        page_url=PAGE_URL,
        probe_url=PROBE_PATH,
    ).check()

    assert verdict.classification == "authenticated"
    assert verdict.body == ""


def test_the_oracle_never_navigates_and_never_fetches_twice():
    client, exec_fn = _attached_client(_probe_envelope(body="ok"))
    oracle = AuthOracle(
        fetch_fn=session_fetch_fn(client), page_url=PAGE_URL, probe_url=PROBE_PATH
    )

    oracle.check()
    oracle.check()

    assert [command[2] for command in exec_fn.commands] == [
        "sessions",
        "sessions",
        "eval",
    ]
