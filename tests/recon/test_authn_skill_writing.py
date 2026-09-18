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
4. Replay the trusted context surgically. When a browser session holds the trusted context, attempt to reproduce it with a plain HTTP client. Start from the account `snapshot` (headers, cookies, params) and the stored tokens with their locations. Identify line by line what carries the trust: header set and order, cookies, token values and locations, user-agent and client hints, query and body parameters, request and network parameters you control, and TLS/HTTP signature specifics where your tooling lets you control them. Change one variable at a time and read the response; iterate until the replay reaches the authenticated state or you can name what blocks it.
5. Record the verdict honestly. When a plain-client replay reaches the authenticated state, record `http-client-replayability: true` and record which shape elements are static (replayable as-is) and which are dynamic (must be re-minted or are browser-bound): the continuation facts a follower needs. When replay cannot reach the authenticated state, record `http-client-replayability: false`; browser-only is a complete, honest result, never a failure.
6. Script-driven logins. When the sign-in is programmed by client-side script, fetch and read the script; replay the exact request shape it builds (endpoints, headers, nonces, parameter order); where the script derives values dynamically (nonces, signatures, fingerprints), say so and treat those parts as browser-bound.
7. Re-verify stale state. Treat an expired or missing session or profile as a loud failure. Re-run the verification predicate before recording or replaying; never fall back silently to anonymous state.
8. Persist through the operator seed face. Write both facts into the operator-owned overview with `PUT /projects/{project_id}/auth`. A present `overview` section replaces wholesale, so read `GET /projects/{project_id}/auth` first and send the merged overview. A shape violation returns 400 `{ok: false, error: "auth_invalid", detail}` and lands nothing. Never write with the in-process agent tool; never put `origin` in the payload.

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
