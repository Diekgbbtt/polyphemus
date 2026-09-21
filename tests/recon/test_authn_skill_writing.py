"""#237 content tier - the authn meta skill's self-containment and contract.

The external authn bootstrapper consumes `skills/meta/authn-skill-writing/`
with no repository access, so these tests pin the skill's deliverable contract:
it conforms to the data-section convention, embeds the operator's target-agnostic
block verbatim, names the typed overview facts and the shared blocking-signature
vocabulary, cites only references that exist, and carries a worked example whose
seed payloads validate against the real overview schema.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from polymerhus.app.auth.records import validate_overview
from polymerhus.app.llm import skills

REPO = Path(__file__).resolve().parents[2]
SKILL = "meta/authn-skill-writing"
SKILL_DIR = REPO / "skills" / SKILL
STEEL_REFERENCES = REPO / "skills" / "steel-browser" / "references"

# The operator's target-agnostic block (ticket #237), held here as an
# independent literal so the skill text and the operator's block cannot drift.
VERBATIM_BLOCK = """## Anti-bot posture and HTTP-client replayability (mandatory, target-agnostic)

Whatever the target, establish and record these two facts before you record its authentication state.

1. Probe request-side first. Using your own request tooling against the target, send the shape a plain client would send (no browser) to the sign-in endpoint or to any authenticated area named in the overview, applying the account's cookies, tokens, and snapshot exactly as recorded. Inspect status, headers, body, and challenge markers.
2. Classify the response, distinguishing three signals. An authentication failure is a 401, or a 403 whose body and headers show an application-level denial. A rate limit is typically a 429 or a documented retry signal. A WAF or anti-bot block is a 403 (or a 200 interstitial) carrying block-page fingerprints, a JS-challenge script, or bot-management cookies. Never collapse these into one another; record the evidence that forced the call.
3. Name the defence. If a WAF or anti-bot defence is present, name its type as precisely as the evidence allows (for example `akamai_v3`, `cf_clearance`, `datadome`, `incapsula`, a named challenge, or `waf:<name>`). Research unfamiliar block patterns (vendor block pages, challenge scripts, characteristic cookies) before naming them. If no defence signal appears, the type is null.
4. Replay the trusted context surgically. When a browser session holds the trusted context, attempt to reproduce it with a plain HTTP client. Start from the overview's `required_headers` (the single source of the required header fact), the account `snapshot` (cookies, params) and the stored tokens with their locations. Identify line by line what carries the trust: header set and order, cookies, token values and locations, user-agent and client hints, query and body parameters, request and network parameters you control, and TLS/HTTP signature specifics where your tooling lets you control them. Change one variable at a time and read the response; iterate until the replay reaches the authenticated state or you can name what blocks it.
5. Record the verdict honestly. When a plain-client replay reaches the authenticated state, record `http-client-replayability: true` and record which shape elements are static (replayable as-is) and which are dynamic (must be re-minted or are browser-bound): the continuation facts a follower needs. When replay cannot reach the authenticated state, record `http-client-replayability: false`; browser-only is a complete, honest result, never a failure.
6. Script-driven logins. When the sign-in is programmed by client-side script, fetch and read the script; replay the exact request shape it builds (endpoints, headers, nonces, parameter order); where the script derives values dynamically (nonces, signatures, fingerprints), say so and treat those parts as browser-bound.
7. Re-verify stale state. Treat an expired or missing session or profile as a loud failure. Re-run the verification predicate before recording or replaying; never fall back silently to anonymous state.
8. Persist through the operator seed face. Write both facts into the overview with `PUT /projects/{project_id}/auth`. A present `overview` section replaces wholesale, so read `GET /projects/{project_id}/auth` first and send the merged overview. A shape violation returns 400 `{ok: false, error: "auth_invalid", detail}` and lands nothing. This seed face is your write path: the in-process agent store tool is the in-system agents' path (their writes merge into the same overview, D220-12), so never use it here and never put `origin` in the payload.

Two rules bind every target: facts live in the store, steps live in the skill; secret values stay in the store, the skill cites names only."""


def _body() -> str:
    return skills.skill_for(SKILL)


def test_skill_conforms_to_the_data_section_contract():
    assert skills.validate_skill(SKILL) == []


def test_the_operator_block_is_embedded_verbatim():
    assert VERBATIM_BLOCK in _body()


def test_names_the_two_typed_overview_facts():
    body = _body()
    assert "anti-bot" in body
    assert "http-client-replayability" in body
    assert "UNKNOWN" in body  # unknown is distinct from false


def test_shares_the_blocking_signature_vocabulary():
    body = _body()
    assert "waf_protected" in body
    assert "waf_detection" in body
    assert "rate_limited" in body


def test_carries_no_dangling_or_in_repo_reference():
    body = _body()
    # the non-existent paths the previous revision cited
    assert "steel-browser-commands.md" not in body
    assert "steel-browser-lifecycle.md" not in body
    # no dependency on in-repo decision records
    assert "docs/design" not in body


def test_every_cited_reference_file_exists():
    """Each `references/<file>` the skill names resolves beside the steel-browser
    skill or beside the meta skill itself (no dangling pointer)."""
    cited = set(re.findall(r"references/[\w.-]+", _body()))
    for ref in cited:
        name = ref[len("references/"):]
        assert (
            (STEEL_REFERENCES / name).exists()
            or (SKILL_DIR / "references" / name).exists()
        ), f"dangling reference: {ref}"


def test_names_the_parametrizable_project_skill_write_location():
    """The external agent knows the skill's content AND where to persist it:
    the parametrized bundle path, never a hardcoded absolute one."""
    body = _body()
    assert "skills/authn/SKILL.md" in body
    assert "skills/authn/references/" in body
    assert "<data_root>" in body
    assert "<project_id>" in body


def test_profile_discipline_mounts_by_name_not_by_id():
    """The CLI's `--profile` takes the name and the store holds the name, so the
    skill must not say "mount by id" (the #237 e2e wording defect)."""
    body = _body()
    assert "Mount by name:" in body
    assert "Mount by id" not in body
    assert "Record the profile name from the mint" in body


def test_account_identity_is_the_credential_not_the_procedure():
    """An account is keyed by its credential identity, so sign-up and sign-in
    for the same credentials share ONE account, not two records differing only
    by `procedure` (the #237 e2e fork defect)."""
    body = _body()
    assert "<username>-<minting_context>" in body
    assert "email location suffix" in body
    assert "never the procedure" in body
    assert "ONE account per credential identity" in body
    assert "separate flows with separate accounts" not in body


def test_bootstrap_prompt_keys_accounts_by_credential_identity():
    prompt = (SKILL_DIR / "references" / "bootstrap-workflow.md").read_text(
        encoding="utf-8"
    )
    assert "<username>-<minting_context>" in prompt
    assert "email location suffix" in prompt
    assert "share ONE account" in prompt
    assert "separate accounts" not in prompt


def test_bootstrap_workflow_prompt_is_target_agnostic_and_request_first():
    """The reusable prompt is generalisable (placeholders, no target) and never
    presumes the browser: it defaults to request-based and takes the browser
    only on a defence signal."""
    prompt = (SKILL_DIR / "references" / "bootstrap-workflow.md").read_text(
        encoding="utf-8"
    )
    for placeholder in ("<project_id>", "<target>", "<login_url>", "<data_root>"):
        assert placeholder in prompt
    assert "moodique" not in prompt.lower(), "the prompt must stay target-agnostic"
    assert "defaults to request-based" in prompt
    assert "Probe request-side first" in prompt
    assert "no defence signal -> request-based" in prompt
    for name in ("waf_protected", "waf_detection", "rate_limited"):
        assert name in prompt


def test_worked_example_seed_overviews_validate_and_cover_both_verdicts():
    fixture = SKILL_DIR / "references" / "worked-example.yaml"
    data = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]
    assert scenarios, "the worked example must carry at least one scenario"
    for scenario in scenarios:
        # every seed payload is a valid overview for the real seed face
        assert validate_overview(scenario["seed_overview"]) == scenario["seed_overview"]
        assert scenario["classification"]["signal"] in {
            "waf_protected", "waf_detection", "rate_limited",
        }
        assert scenario["anti_bot"]
        assert isinstance(scenario["http_client_replayability"], bool)
    verdicts = {s["http_client_replayability"] for s in scenarios}
    assert verdicts == {True, False}, "the example must show both verdicts"


def test_skill_carries_the_browser_fast_path():
    """The e2e latency finding: the bootstrapper re-derived the CLI from `--help`
    and paid snapshot round-trips and a networkidle timeout. The skill must inline
    the four habits (interactive snapshot, batch, variadic boundary, observable
    wait) and point at the operation-mechanics skill."""
    body = _body()
    assert "steel-browser` skill" in body
    assert "snapshot -i" in body
    assert "batch --session" in body
    assert "-- <value>" in body
    assert "wait --url" in body


def test_skill_warns_against_networkidle_settle():
    """A login page or SPA with continuous activity never reaches network idle,
    so `navigate --wait-until networkidle` times out; the skill must steer to
    `load` plus a condition, and must not prescribe the networkidle wait."""
    body = _body()
    assert "wait --load networkidle" not in body
    assert "never reaches network idle" in body


def test_bootstrap_prompt_cites_the_mechanics_skill():
    """The prompt must point the bootstrapper at the operation-mechanics skill
    before the first browser step, so it is not re-derived from `--help`."""
    prompt = (SKILL_DIR / "references" / "bootstrap-workflow.md").read_text(
        encoding="utf-8"
    )
    assert "<mechanics_skill_path>" in prompt
    assert "steel-browser" in prompt
    assert "do not re-derive the steel CLI from `--help`" in prompt


def test_browser_discipline_mounts_first_and_logs_in_only_on_failure():
    """The reCAPTCHA diagnosis (D237-14): a fresh login is the score-gated
    action, so the profile is mounted first and a login happens only when the
    mount does not verify - never on a disposable profile (D237-15)."""
    body = _body()
    assert "Mount first, every time" in body
    assert "log in only when the mount does not yield the authenticated landing" in body
    assert "never on a disposable one" in body
    assert "mint or mount" not in body


def test_bootstrap_prompt_mounts_first_and_keeps_the_login_warm():
    prompt = (SKILL_DIR / "references" / "bootstrap-workflow.md").read_text(
        encoding="utf-8"
    )
    assert "Mount first, read-only" in prompt
    assert "Log in only when the mount does not yield the authenticated landing" in prompt
    assert "warm identity is written back and never discarded" in prompt
    assert "Mint the profile in flow on first login" not in prompt


def test_mechanics_skill_paces_the_login_and_sizes_the_clock():
    """The non-reactive half of the fix: one submit (no blind resubmits) and a
    session clock sized for a human step. No solving surface is taught."""
    body = skills.skill_for("steel-browser")
    assert "Submit once, then wait on the condition" in body
    assert "--inactivity-timeout" in body
    assert "the 120 s default releases it mid-solve" in body
