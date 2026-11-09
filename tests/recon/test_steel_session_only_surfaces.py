"""#395 D20 drift guard for the model-facing Steel surfaces.

Every client component that teaches an agent how to use the Steel browser must
be runtime-blind and session-only. This test pins those text contracts at
their real seams: the gateway prompt and branch manner, the authn loop hints,
the crawl role prompt, the auth-store tool contract, the authn meta skill, and
the external bootstrapper prompt.

These are content contracts, not behaviour tests: the behaviour lives in the
provider, wrapper, gateway, and auth-gate tiers.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def test_gateway_prompt_teaches_mounted_sessions_and_no_profile() -> None:
    text = _read(
        "src", "polymerhus", "recon", "control", "prompts", "auth-gateway.md"
    )
    lower = text.lower()
    assert "profile" not in lower
    assert "--update-profile" not in text
    assert "fingerprint replay" not in lower
    assert "web browser" in lower
    assert "browser(command" in text
    assert "browser_context" in lower


def test_gateway_branch_manner_teaches_mounted_sessions_and_no_profile() -> None:
    from polymerhus.recon.control.orchestrator_agent import _BRANCH_MANNER

    assert set(_BRANCH_MANNER) == {
        "request", "browser_only", "request_browser_first", "resolve_in_loop",
    }
    for directive, manner in _BRANCH_MANNER.items():
        lower = manner.lower()
        assert "profile" not in lower, directive
        assert "--update-profile" not in manner, directive
        assert "fingerprint replay" not in lower, directive
    assert "web browser" in _BRANCH_MANNER["browser_only"].lower()
    assert "browser_context" in _BRANCH_MANNER["browser_only"].lower()


def test_gateway_prompt_names_the_oracle_and_fails_closed() -> None:
    text = _read(
        "src", "polymerhus", "recon", "control", "prompts", "auth-gateway.md"
    )
    lower = text.lower()
    assert "auth_probe" in text
    assert "2xx" in text
    assert "401" in text and "403" in text and "3xx" in text
    assert "indeterminate" in lower
    assert "redirected" in lower
    assert "mint" in lower
    assert "fail-closed" in lower or "does not fail open" in lower
    assert "authenticated landing" not in lower


def test_gateway_prompt_uses_the_account_oracle_and_root_fallback() -> None:
    text = _read(
        "src", "polymerhus", "recon", "control", "prompts", "auth-gateway.md"
    )
    lower = text.lower()
    assert "account.auth_probe" in text
    assert "root_url" in lower
    assert "one session" in lower
    assert "overview.auth_probe.url" not in text


def test_gateway_prompt_names_the_crawl_phase_and_the_job() -> None:
    text = _read(
        "src", "polymerhus", "recon", "control", "prompts", "auth-gateway.md"
    )
    lower = text.lower()
    assert "`steel_crawl`" in text
    assert "`katana`" in text and "`ffuf`" in text
    assert "`JOBS`" in text and "`PHASES`" in text
    assert "mounts the same decoupled auth context" in lower
    assert "browser_only" in lower
    assert "d-jobset" in lower


def test_authn_meta_skill_and_bootstrap_teach_the_oracle() -> None:
    skill = _read("skills", "meta", "authn-skill-writing", "SKILL.md")
    prompt = _read(
        "skills", "meta", "authn-skill-writing", "references",
        "bootstrap-workflow.md",
    )
    for name, text in (("SKILL.md", skill), ("bootstrap-workflow.md", prompt)):
        assert "auth_probe" in text, name
        assert "2xx" in text, name
        assert "401" in text and "403" in text and "3xx" in text, name
        assert "indeterminate" in text.lower(), name
        assert "auth-oracle.sh" in text, name
        assert "mint" in text.lower(), name


def test_authn_meta_skill_and_bootstrap_teach_the_session_model() -> None:
    skill = _read("skills", "meta", "authn-skill-writing", "SKILL.md")
    prompt = _read(
        "skills", "meta", "authn-skill-writing", "references",
        "bootstrap-workflow.md",
    )
    for name, text in (("SKILL.md", skill), ("bootstrap-workflow.md", prompt)):
        lower = text.lower()
        assert "account is one session" in lower, name
        assert "role" in lower, name
        assert "root_url" in lower, name
        assert "auth_probe" in lower, name
        assert "browser_context" in lower, name
        assert "privilege" in lower, name
    assert "highest privilege first" in skill.lower()
    assert "highest privilege first" in prompt.lower()


def test_external_bootstrap_contracts_teach_role_priority_and_session_roots() -> None:
    contract = _read("tools", "bootstrap", "DATA-DEPENDENCIES.md")
    authn = _read("tools", "bootstrap", "prompts", "data-dep-authn.md")
    l1 = _read("tools", "bootstrap", "prompts", "data-dep-l1.md")

    for name, text in (
        ("DATA-DEPENDENCIES.md", contract),
        ("data-dep-authn.md", authn),
        ("data-dep-l1.md", l1),
    ):
        lower = text.lower()
        assert "role" in lower, name
        assert "root_url" in lower, name
        assert "auth_probe" in lower, name
        assert "privilege" in lower, name
        assert "first" in lower, name

    assert "one account per session" in authn.lower()
    assert "account.auth_probe" in l1 or "account's `auth_probe`" in l1


def test_gateway_prompt_uses_the_redacted_store_and_recorded_replay() -> None:
    text = _read(
        "src", "polymerhus", "recon", "control", "prompts", "auth-gateway.md"
    )
    lower = text.lower()
    assert "redacted" in lower
    assert "never read" in lower
    assert "search_http_history" in text
    assert "replay_http_request" in text
    assert "start or reuse" not in lower
    assert "stored request state" not in lower
    assert "extracted tokens" not in lower
    assert "session_in_use" in text
    assert "no_session" in text


def test_gateway_manner_and_hints_do_not_teach_raw_secret_reads() -> None:
    from polymerhus.recon.control import authn_loop
    from polymerhus.recon.control.orchestrator_agent import _BRANCH_MANNER

    text = "\n".join(_BRANCH_MANNER.values())
    text += "\n" + "\n".join((
        authn_loop.RETRIEVED_HINT,
        authn_loop.VALIDATION_HINT,
        authn_loop.GENERATION_HINT,
        authn_loop.GENERATION_SIGNIN_HINT,
        authn_loop.SELF_SERVICE_HINT,
    ))
    lower = text.lower()
    assert "start or reuse" not in lower
    assert "stored request state" not in lower
    assert "extracted tokens" not in lower
    assert "redacted" in lower
    assert "replay_http_request" in text
    assert "session_in_use" in text
    assert "no_session" in text


def test_authn_meta_skill_sizes_the_session_and_handles_typed_loss() -> None:
    skill = _read("skills", "meta", "authn-skill-writing", "SKILL.md")
    prompt = _read(
        "skills", "meta", "authn-skill-writing", "references",
        "bootstrap-workflow.md",
    )
    for name, text in (("SKILL.md", skill), ("bootstrap-workflow.md", prompt)):
        assert 'browser(command="start", account=<account>)' in text, name
        assert 'browser(command="end", persist_context=true)' in text, name
        assert "session_in_use" in text, name
        assert "no_session" in text, name
        assert "--inactivity-timeout" not in text, name
        assert "start or reuse" not in text.lower(), name
    assert "never a twin" in skill
    assert "never start a twin" in prompt


def test_authn_loop_hints_teach_live_sessions_and_no_profile() -> None:
    from polymerhus.recon.control import authn_loop

    hints = (
        authn_loop.RETRIEVED_HINT,
        authn_loop.GENERATION_HINT,
        authn_loop.GENERATION_SIGNIN_HINT,
        authn_loop.SELF_SERVICE_HINT,
    )
    for hint in hints:
        lower = hint.lower()
        assert "profile" not in lower
        assert "fingerprint replay" not in lower
    assert "mounted session" in authn_loop.RETRIEVED_HINT.lower()
    assert "browser(command" in authn_loop.GENERATION_SIGNIN_HINT.lower()
    assert "browser_context.ref" in authn_loop.GENERATION_SIGNIN_HINT.lower()


def test_auth_store_contract_has_no_profile_vocabulary() -> None:
    from polymerhus.app.auth.tool import AUTH_STORE_CONTRACT

    assert "profile" not in AUTH_STORE_CONTRACT.lower()
    assert "browser_context: {ref}" in AUTH_STORE_CONTRACT
    assert "browser auth-context reference" in AUTH_STORE_CONTRACT


def test_authn_meta_skill_and_bootstrap_prompt_have_no_profile_vocabulary() -> None:
    skill = _read("skills", "meta", "authn-skill-writing", "SKILL.md")
    prompt = _read(
        "skills", "meta", "authn-skill-writing", "references",
        "bootstrap-workflow.md",
    )
    for name, text in (("SKILL.md", skill), ("bootstrap-workflow.md", prompt)):
        assert "profile" not in text.lower(), name
        assert "--profile" not in text, name
    assert "browser_context: {ref}" in skill
    assert 'browser(command="end"' in skill
    assert 'browser(command="start", account=<account>)' in skill
    assert 'browser(command="start", account=<account>)' in prompt


def test_external_bootstrapper_prompt_uses_a_state_reference() -> None:
    text = _read("tools", "bootstrap", "prompts", "data-dep-authn.md")
    assert "{profile}" not in text
    assert "browser_context? ({ref})" in text
    assert "steel? ({state})" not in text
    assert "profile" not in text.lower()
