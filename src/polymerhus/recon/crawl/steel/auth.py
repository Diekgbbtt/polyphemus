"""The authenticated-context oracle: one browser fetch, classified, fail-closed.

Spec: `docs/design/steel-crawl-spec.md` sections 2.1, 4.5, and 12.

The oracle is a browser `fetch`, never a navigation envelope: `steel browser
navigate` follows a 302 and reports success with the final 200 URL, so it
cannot see the redirect. The fetch exposes `status`, `redirected`, and the
final `url`, and the classification is fixed - a 2xx with `redirected: false`
is authenticated, `401`, `403`, any 3xx, or `redirected: true` is
unauthenticated, and anything else is indeterminate and fails closed.

It runs once. The first `check` fetches and caches the verdict; a later
`check` returns the cached verdict and issues no second fetch, so a submit or a
navigation can never re-open the authentication question.

A missing probe is loud: the oracle logs it and falls back to the legacy
surface gate, which rejects a login path or login redirect, `401`, `403`, any
3xx, and a login-form body. Neither path continues anonymously: a
non-authenticated verdict raises `AuthPreconditionFailed` carrying that
verdict, so the job logs the evidence and the orchestrator resurrects the
session.

Only the injected `fetch_fn` performs I/O (CODING_STANDARD section 6). The
default adapter is `session_fetch_fn`, which renders the canonical script and
runs it through the session client's `eval` verb and nothing else.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.crawl.steel.session import SteelSessionClient

logger = logging.getLogger(__name__)

# The probe body is diagnostic evidence, not a pass condition: only the status
# and the redirect flag classify the outcome.
BODY_CAP = 200

Classification = Literal["authenticated", "unauthenticated", "indeterminate"]

PROBE_SOURCE = "overview.auth_probe.url"
LEGACY_PROBE_SOURCE = "legacy_surface_gate"
MISSING_PROBE_NOTE = "overview.auth_probe.url is missing"

# The legacy gate rejects a final URL on a login path. Segments are matched
# whole: `logout` and `login-history` are not login surfaces.
_LOGIN_SEGMENTS = frozenset(
    {
        "login",
        "log-in",
        "log_in",
        "signin",
        "sign-in",
        "sign_in",
        "signon",
        "sign-on",
        "sign_on",
    }
)

# A login form carries a password field and login wording. Both are required: an
# authenticated page can hold a password field (a change-password form) or login
# wording alone (a footer link), so either signal by itself would reject a
# normal authenticated page.
_PASSWORD_FIELDS = ('type="password"', "type='password'", "type=password")
_LOGIN_WORDING = ("log in", "login", "log-in", "sign in", "signin", "sign-in")

# `fetch_fn(url) -> {status, redirected, url, body}`: the one impure seam.
FetchFn = Callable[[str], Mapping[str, Any]]


def render_probe_script(url: str) -> str:
    """The canonical probe fetch (spec 4.5, `references/auth-oracle.sh`).

    It is one `eval` expression: a browser `fetch` that follows redirects so it
    can report `redirected`, carries the session credentials, bypasses the
    cache, and returns the four evidence fields as one JSON string. A followed
    redirect is visible in `redirected`, which a navigation envelope cannot
    show. The body is cut here as well as in the verdict, so a large page never
    crosses the CLI boundary.
    """
    return (
        "(async()=>{"
        f"const r=await fetch({json.dumps(url)},"
        '{redirect:"follow",credentials:"include",cache:"no-store"});'
        "const t=await r.text();"
        "return JSON.stringify({status:r.status,redirected:r.redirected,"
        "url:r.url,body:t.slice(0,"
        f"{BODY_CAP}"
        ")});"
        "})()"
    )


def session_fetch_fn(client: SteelSessionClient) -> FetchFn:
    """The production `fetch_fn`: one `eval` command, and nothing else.

    The CLI envelope's `data` is the script's JSON string. A session failure is
    not swallowed: the client's typed error propagates so the job takes the
    session-recovery path rather than the auth-retry path. Only a payload the
    oracle cannot read degrades to `{}`, which classifies indeterminate and
    fails closed.
    """

    def fetch(url: str) -> Mapping[str, Any]:
        envelope = client.execute("eval", render_probe_script(url))
        data = envelope.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return {}
        if isinstance(data, Mapping):
            return data
        return {}

    return fetch


class AuthVerdict(BaseModel):
    """One oracle outcome and the evidence that produced it."""

    model_config = ConfigDict(frozen=True)

    classification: Classification
    probe_url: str
    probe_source: str
    status: int | None = None
    redirected: bool | None = None
    final_url: str = ""
    body: str = ""
    note: str = ""


def resolve_probe_url(page_url: str, probe_url: str | None) -> str | None:
    """Resolve the configured probe against the loaded page's origin.

    The store records a deployment-neutral path, so a path resolves against the
    page whose authenticated context the fetch runs in; an absolute probe is
    already deployment-specific and is used as given. No probe at all is
    `None`: the caller owns the loud fallback.
    """
    raw = (probe_url or "").strip()
    if not raw:
        return None
    return urljoin(page_url, raw)


def classify_probe(status: int | None, redirected: bool | None) -> Classification:
    """The fixed classification (spec 4.5): only a 2xx that did not redirect passes."""
    if redirected is True:
        return "unauthenticated"
    if status is None:
        return "indeterminate"
    if 300 <= status < 400 or status in (401, 403):
        return "unauthenticated"
    if 200 <= status < 300 and redirected is False:
        return "authenticated"
    return "indeterminate"


def classify_legacy_surface(
    *,
    status: int | None,
    final_url: str,
    body: str,
    login_url: str | None = None,
) -> tuple[Classification, str]:
    """The legacy surface gate: `(classification, reason)` for one loaded page.

    It is deliberately not `recon.crawl.auth_gate.evaluate_auth_gate`: that gate
    passes a 3xx, and spec A8 requires the fallback to reject one. It also reads
    no page body, so it cannot see the login form an unauthenticated app renders
    at the root. The login-URL comparison keeps that gate's path semantics.

    A login path or login redirect, `401`, `403`, and any 3xx are rejected. Only
    an explicit 2xx without a login form passes; every other outcome is
    indeterminate, and indeterminate fails closed exactly like a rejection.
    """
    if _is_login_url(final_url, login_url):
        return "unauthenticated", "login_redirect"
    if status in (401, 403):
        return "unauthenticated", f"http_{status}"
    if status is not None and 300 <= status < 400:
        return "unauthenticated", f"http_{status}"
    if not status:
        return "indeterminate", "no_response"
    if _has_login_form(body):
        return "unauthenticated", "login_form"
    if 200 <= status < 300:
        return "authenticated", ""
    return "indeterminate", f"http_{status}"


def _is_login_url(final_url: str, login_url: str | None) -> bool:
    if _has_login_segment(final_url):
        return True
    if not final_url or not login_url:
        return False
    final, login = urlsplit(final_url), urlsplit(login_url)
    if (final.scheme, final.netloc) != (login.scheme, login.netloc):
        return False
    final_path = (final.path or "/").rstrip("/") or "/"
    login_path = (login.path or "/").rstrip("/") or "/"
    return final_path == login_path or final_path.startswith(login_path + "/")


def _has_login_segment(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(segment in _LOGIN_SEGMENTS for segment in path.split("/") if segment)


def _has_login_form(body: str) -> bool:
    text = body.lower()
    if not any(field in text for field in _PASSWORD_FIELDS):
        return False
    return any(word in text for word in _LOGIN_WORDING)


class AuthPreconditionFailed(RuntimeError):
    """The authenticated context is not proven; the run must not continue.

    The verdict rides on the failure so the job logs the evidence that failed
    the precondition (status, redirect, final URL, capped body) without a
    second fetch. It is deliberately not a session error: an auth failure earns
    the orchestrator's one bounded resurrection retry, while a session failure
    takes the recreate path (spec 2.1, A9 and A10).
    """

    code = "auth_precondition_failed"

    def __init__(self, verdict: AuthVerdict) -> None:
        self.verdict = verdict
        super().__init__(
            "the authenticated precondition failed: "
            f"{verdict.classification} (source={verdict.probe_source}, "
            f"status={verdict.status}, redirected={verdict.redirected}, "
            f"final_url={verdict.final_url!r})"
        )


class AuthOracle:
    """One-shot authenticated-context oracle bound to one loaded page."""

    def __init__(
        self,
        *,
        fetch_fn: FetchFn,
        page_url: str,
        probe_url: str | None = None,
        login_url: str | None = None,
    ) -> None:
        self._fetch_fn = fetch_fn
        self._page_url = page_url
        self._probe_url = probe_url
        self._login_url = login_url
        self._verdict: AuthVerdict | None = None
        self._fetch_count = 0

    @property
    def fetch_count(self) -> int:
        """How many browser fetches the oracle issued; one is the whole contract."""
        return self._fetch_count

    def check(self) -> AuthVerdict:
        """Run the oracle once and return its verdict, or fail the precondition."""
        if self._verdict is None:
            self._verdict = self._probe()
        verdict = self._verdict
        if verdict.classification != "authenticated":
            raise AuthPreconditionFailed(verdict)
        return verdict

    def _probe(self) -> AuthVerdict:
        probe_url = resolve_probe_url(self._page_url, self._probe_url)
        if probe_url is None:
            return self._legacy_surface_gate()
        payload = self._fetch(probe_url)
        status = _as_int(payload.get("status"))
        redirected = _as_bool(payload.get("redirected"))
        return AuthVerdict(
            classification=classify_probe(status, redirected),
            probe_url=probe_url,
            probe_source=PROBE_SOURCE,
            status=status,
            redirected=redirected,
            final_url=str(payload.get("url") or probe_url),
            body=str(payload.get("body") or "")[:BODY_CAP],
        )

    def _legacy_surface_gate(self) -> AuthVerdict:
        """The loud fallback for a missing probe: check the loaded surface itself.

        The page is already authenticated-context-bearing, so the gate fetches
        the loaded URL back and rejects a login path, a login redirect, `401`,
        `403`, any 3xx, and a login-form body. It never continues anonymously;
        an indeterminate outcome fails closed with the same typed failure.
        """
        logger.warning(
            "%s; falling back to the legacy surface gate", MISSING_PROBE_NOTE
        )
        payload = self._fetch(self._page_url)
        status = _as_int(payload.get("status"))
        redirected = _as_bool(payload.get("redirected"))
        final_url = str(payload.get("url") or self._page_url)
        body = str(payload.get("body") or "")[:BODY_CAP]
        classification, reason = classify_legacy_surface(
            status=status,
            final_url=final_url,
            body=body,
            login_url=self._login_url,
        )
        return AuthVerdict(
            classification=classification,
            probe_url=self._page_url,
            probe_source=LEGACY_PROBE_SOURCE,
            status=status,
            redirected=redirected,
            final_url=final_url,
            body=body,
            note=f"{MISSING_PROBE_NOTE}; {reason}" if reason else MISSING_PROBE_NOTE,
        )

    def _fetch(self, url: str) -> Mapping[str, Any]:
        self._fetch_count += 1
        payload = self._fetch_fn(url)
        return payload if isinstance(payload, Mapping) else {}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


__all__ = [
    "BODY_CAP",
    "LEGACY_PROBE_SOURCE",
    "MISSING_PROBE_NOTE",
    "PROBE_SOURCE",
    "AuthOracle",
    "AuthPreconditionFailed",
    "AuthVerdict",
    "Classification",
    "FetchFn",
    "classify_legacy_surface",
    "classify_probe",
    "render_probe_script",
    "resolve_probe_url",
    "session_fetch_fn",
]
