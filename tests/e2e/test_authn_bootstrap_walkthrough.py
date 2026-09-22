"""Authn-bootstrap walkthrough (#237) - the live e2e verification predicates.

Source of truth: ticket #237's acceptance shape, read through the operator's
own eyes: an external bootstrapper (the subagent this harness dispatches)
follows `skills/meta/authn-skill-writing/SKILL.md` against a live target and
leaves two artifacts on the app-owned data root - the auth store bucket
(`data/<project_id>/auth/`) and the per-project authn skill
(`data/<project_id>/skills/authn/SKILL.md`).

These are WALKTHROUGH predicates, not unit tests: they read the terminal
quantities back out of the real datastore the run wrote (the YAML bucket and
the skill bundle on disk, plus the live read face `GET /projects/{id}/auth`),
and the one live edge is the target itself (moodique.com) and its Steel
profile. They are gated: with no run artifacts they skip, so the tier is inert
until the operator green-lights the live run.

The catalogue (see the ticket report for the full predicate list):
  E1  the project authn skill exists at the designed path with valid frontmatter
  E2  the skill embeds the mandatory anti-bot/replayability block verbatim and
      leaks no secret value (it cites names only)
  E3  the read face returns the two typed facts with the right types
  E4  the store account carries the verified facts (credentials, steel profile,
      located tokens, procedure label)
  E5  the persisted Steel profile is mountable in a NEW session and reaches an
      authenticated (non-login) state
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROJECT_ID = os.environ.get("AUTHN_E2E_PROJECT_ID", "authn-e2e")
DATA = REPO / "data" / PROJECT_ID
SKILL_PATH = DATA / "skills" / "authn" / "SKILL.md"
OVERVIEW_PATH = DATA / "auth" / "overview.yaml"
CREDENTIALS_PATH = DATA / "auth" / "credentials.yaml"
META_SKILL = REPO / "skills" / "meta" / "authn-skill-writing" / "SKILL.md"

AGENT_URL = os.environ.get("AUTHN_E2E_AGENT_URL", "http://localhost:8083")
LANDING_URL = os.environ.get(
    "AUTHN_E2E_LANDING_URL", "https://moodique.com/it/area-cliente"
)

_VALID_TOKEN_LOCATIONS = {"cookie", "header", "storage"}


def _require_run() -> None:
    if not SKILL_PATH.exists() and not OVERVIEW_PATH.exists():
        pytest.skip(
            f"no authn-bootstrap run artifacts under {DATA} "
            "(the live run has not been dispatched)"
        )


def _skill_text() -> str:
    _require_run()
    if not SKILL_PATH.exists():
        pytest.skip(f"the project authn skill was not written at {SKILL_PATH}")
    return SKILL_PATH.read_text(encoding="utf-8")


def _skill_frontmatter(text: str) -> dict:
    assert text.startswith("---"), "the skill must carry YAML frontmatter"
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert isinstance(meta, dict), "the skill frontmatter must be a mapping"
    return meta


def _overview() -> dict:
    _require_run()
    if not OVERVIEW_PATH.exists():
        pytest.skip(f"the auth overview was not written at {OVERVIEW_PATH}")
    body = yaml.safe_load(OVERVIEW_PATH.read_text(encoding="utf-8")) or {}
    assert isinstance(body, dict)
    return body


def _accounts() -> dict:
    _require_run()
    if not CREDENTIALS_PATH.exists():
        pytest.skip(f"the auth accounts were not written at {CREDENTIALS_PATH}")
    body = yaml.safe_load(CREDENTIALS_PATH.read_text(encoding="utf-8")) or {}
    accounts = body.get("accounts")
    assert isinstance(accounts, dict) and accounts, "at least one account is required"
    return accounts


def _mandatory_block() -> str:
    """The operator's target-agnostic block, extracted from the meta skill's
    fenced ```markdown section - the independent literal the project skill must
    carry verbatim (extracted rather than re-typed so the two cannot drift)."""
    text = META_SKILL.read_text(encoding="utf-8")
    match = re.search(r"```markdown\n(.*?)\n```", text, re.DOTALL)
    assert match, "the meta skill must embed the mandatory block in a ```markdown fence"
    return match.group(1)


# --- E1: the skill exists, at the designed path, with valid frontmatter -------

def test_e1_project_skill_bundle_is_written_at_the_designed_path():
    text = _skill_text()
    meta = _skill_frontmatter(text)
    assert meta.get("name") == "authn", (
        "frontmatter 'name' must equal the bundle directory 'authn'"
    )
    assert isinstance(meta.get("description"), str) and meta["description"]
    version = (meta.get("metadata") or {}).get("version")
    assert isinstance(version, str) and version, "metadata.version must be non-empty"
    assert (SKILL_PATH.parent / "references").is_dir(), (
        "the bundle must carry its canonical references/ directory"
    )


# --- E2: the verbatim block is embedded and no secret leaks -------------------

def test_e2_skill_embeds_the_mandatory_block_verbatim():
    assert _mandatory_block() in _skill_text()


def test_e2_skill_cites_names_and_never_secret_values():
    text = _skill_text()
    secrets: list[str] = []
    for record in _accounts().values():
        credentials = record.get("credentials") or {}
        if isinstance(credentials.get("password"), str):
            secrets.append(credentials["password"])
        for token in (record.get("tokens") or {}).values():
            if isinstance(token, dict) and isinstance(token.get("value"), str):
                secrets.append(token["value"])
    assert secrets, "the store must carry at least one secret to prove non-leakage"
    for secret in secrets:
        assert secret not in text, "a secret value must never appear in the skill"


# --- E3: the read face returns the two typed facts ----------------------------

def test_e3_read_face_returns_the_two_typed_overview_facts():
    _require_run()
    try:
        response = httpx.get(f"{AGENT_URL}/projects/{PROJECT_ID}/auth", timeout=10)
    except httpx.HTTPError as exc:
        pytest.skip(f"the agent read face is unreachable at {AGENT_URL}: {exc}")
    assert response.status_code == 200, response.text
    overview = response.json().get("overview") or {}
    # The store on disk and the live read face must agree on the typed facts.
    disk = _overview()
    for source in (overview, disk):
        anti_bot = source.get("anti-bot")
        assert anti_bot is None or (isinstance(anti_bot, str) and anti_bot), (
            "anti-bot must be a non-empty string or null"
        )
        replayability = source.get("http-client-replayability")
        assert isinstance(replayability, bool), (
            "http-client-replayability must be a real boolean once recorded"
        )
    assert overview.get("http-client-replayability") == disk.get(
        "http-client-replayability"
    )


# --- E4: the store account carries the verified facts -------------------------

def test_e4_account_carries_credentials_steel_tokens_and_procedure():
    accounts = _accounts()
    assert accounts, "at least one account is required"
    any_tokens = False
    for name, record in accounts.items():
        assert isinstance(record, dict), f"account {name} must be a mapping"
        assert record.get("origin") == "operator", (
            f"account {name} was seeded through the operator face"
        )
        credentials = record.get("credentials") or {}
        assert credentials.get("username") and credentials.get("password"), (
            f"account {name} must carry verified credentials"
        )
        assert credentials.get("login_url"), f"account {name} needs a login_url"
        # The steel reference is conditional on the browser path: a request-only
        # run persists no profile, and the assertion must not invent one.
        steel = record.get("steel")
        if steel is not None:
            assert isinstance(steel, dict) and isinstance(
                steel.get("profile"), str
            ) and steel["profile"], (
                f"account {name}: a persisted steel reference must carry a profile key"
            )
        assert isinstance(record.get("procedure"), str) and record["procedure"], (
            f"account {name} must carry the procedure label (the store<->skill join)"
        )
        procedure = record["procedure"].lower()
        tokens = record.get("tokens") or {}
        if tokens:
            any_tokens = True
            for token_name, token in tokens.items():
                assert token.get("value"), f"token {token_name} needs a value"
                assert token.get("location") in _VALID_TOKEN_LOCATIONS, (
                    f"token {token_name} needs a cookie|header|storage location"
                )
        else:
            # A sign-up flow mints no session by design, so only a sign-in
            # (session-minting) account is required to persist tokens.
            assert "sign-in" not in procedure and "signin" not in procedure, (
                f"account {name} ({procedure}) reaches an authenticated state "
                "and must persist at least one token"
            )
    assert any_tokens, "at least one account must persist a verified session token"


# --- E6: sign-up and sign-in are separate verified flows (when expected) ------

def test_e6_signup_is_a_separate_verified_flow_when_expected():
    """When the target has a sign-up surface, the skill carries a distinct
    sign-up procedure and the store carries a distinct sign-up account: the
    meta skill forbids merging the two flows."""
    if os.environ.get("AUTHN_E2E_EXPECT_SIGNUP") != "1":
        pytest.skip("target has no sign-up flow (AUTHN_E2E_EXPECT_SIGNUP != 1)")
    text = _skill_text().lower()
    assert "sign-up" in text or "signup" in text, (
        "the skill must carry a distinct sign-up procedure"
    )
    procedures = {
        (record.get("procedure") or "").lower()
        for record in _accounts().values()
    }
    has_signup = any("sign-up" in p or "signup" in p for p in procedures)
    has_signin = any("sign-in" in p or "signin" in p for p in procedures)
    assert has_signup and has_signin, (
        f"sign-up and sign-in must be separate procedures/accounts, got {procedures}"
    )


# --- E5: the persisted profile mounts in a NEW session ------------------------

def test_e5_profile_is_mountable_in_a_new_session():
    accounts = _accounts()
    profile = None
    for record in accounts.values():
        candidate = (record.get("steel") or {}).get("profile")
        if candidate:
            profile = candidate
            break
    if not profile:
        pytest.skip("no steel profile was persisted (request-only run)")
    steel = shutil.which("steel")
    if not steel:
        pytest.skip("the steel CLI is not on PATH")

    # A WAF target answers an anonymous session with its own landing (the root
    # or a block page), so "not the login page" alone is too weak: the mounted
    # profile must land somewhere an anonymous session does not.
    url_anon = _steel_landing(steel, LANDING_URL)
    url_profile = _steel_landing(steel, LANDING_URL, profile=profile)
    assert "/login" not in url_profile.lower(), (
        f"the mounted profile reached the login page, not an authenticated "
        f"state: {url_profile}"
    )
    assert url_profile != url_anon, (
        f"the mounted profile reached the same page as an anonymous session "
        f"({url_profile}); the profile carries no authenticated state"
    )


def _steel_landing(steel: str, url: str, profile: str | None = None) -> str:
    """Mount an optional profile in a fresh session, navigate to `url`, and
    return the settled URL. Always `--wait-until load`, never `networkidle`: a
    target with continuous network activity never reaches network idle and the
    navigate errors (observed live on magnific)."""
    session = f"polymerhus-authn-e2e-{uuid.uuid4().hex[:8]}"
    started = False
    try:
        start_cmd = [steel, "browser", "start", "--session", session]
        if profile:
            start_cmd += ["--profile", profile]
        start_cmd += ["--json"]
        start = subprocess.run(
            start_cmd, capture_output=True, text=True, timeout=180,
        )
        assert start.returncode == 0, f"session start failed: {start.stderr}"
        started = True
        nav = subprocess.run(
            [steel, "browser", "navigate", url, "--session", session,
             "--wait-until", "load", "--json"],
            capture_output=True, text=True, timeout=180,
        )
        assert nav.returncode == 0, f"navigate failed: {nav.stderr}"
        out = subprocess.run(
            [steel, "browser", "get", "url", "--session", session, "--json"],
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, f"url read failed: {out.stderr}"
        return _settled_url(out.stdout)
    finally:
        if started:
            subprocess.run(
                [steel, "browser", "stop", "--session", session, "--json"],
                capture_output=True, text=True, timeout=60,
            )


def _settled_url(raw: str) -> str:
    """The URL out of a `steel browser get url --json` line: `{"data": "<url>"}`
    (or a `{"data": {"url": ...}}` shape), falling back to the raw text."""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, str):
            return data
        if isinstance(data, dict) and isinstance(data.get("url"), str):
            return data["url"]
    return raw.strip()


def _json_field(raw: str, field: str):
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and field in body:
            return body[field]
    return None
