"""FR-ELICIT unit tier - the Bootstrapper's PURE units, with injected fakes (no LLM/DB).

Scope split: the delivery semantics of the whole two-call runner (fail-closed, call
ordering, linchpin forcing, idempotence) are the integration catalogue's job
(`tests/integration/test_bootstrap_reasoned_contracts.py`, C1-C18). This tier covers
what is purely local: the props allowlist and contract cleaning, the shared bounded
retry, the skill seam, and the settings-reading entry point.

This file previously tested `bootstrap_from_kb`, the superseded single-call path
retired in #29; every behaviour it asserted is covered against the reasoned path by
the C-catalogue.
"""
import pytest

from polymerhus.analysis import bootstrap
from polymerhus.analysis.bootstrap import (
    ServiceShell,
    SystemShell,
    _clean_contract,
    _service_props,
    shells_to_batch,
)


def _svc_props(batch):
    return {s.business_function_slug: s.props for s in batch.services}


# --- the props allowlist + contract cleaning (#29) -----------------------------

def test_service_props_keeps_only_exposure_and_contract():
    shell = ServiceShell(
        business_function_slug="checkout", exposure="public",
        service_contract="Take a basket to a paid order.",
        label="Checkout", salience="high", aggregates=[{"x": 1}], data_flows=[{"y": 2}],
    )
    assert _service_props(shell) == {
        "exposure": "public",
        "service_contract": "Take a basket to a paid order.",
    }


def test_service_props_drops_an_out_of_enum_exposure_but_keeps_the_contract():
    """The two props are validated INDEPENDENTLY: a strayed exposure must not take a
    perfectly good contract down with it (the contract is the routing evidence)."""
    shell = ServiceShell(
        business_function_slug="x", exposure="semi-public",
        service_contract="Browse the catalogue.",
    )
    assert _service_props(shell) == {"service_contract": "Browse the catalogue."}


@pytest.mark.parametrize("raw", [None, "", "   ", "\n\t "])
def test_blank_contract_is_omitted_not_persisted_as_empty(raw):
    """`absence means not-yet-filled` is the convention every consumer reads. An
    empty-string prop would satisfy a presence check while telling the Assigner
    nothing, so blank must normalise to omitted."""
    assert _clean_contract(raw) is None
    assert "service_contract" not in _service_props(
        ServiceShell(business_function_slug="x", service_contract=raw)
    )


def test_contract_whitespace_is_collapsed():
    assert _clean_contract("Pay for\n  an   order.\n\nDeals in payments.") == (
        "Pay for an order. Deals in payments."
    )


def test_contract_over_the_cap_is_trimmed_not_dropped():
    """A too-long contract still carries its discriminating nouns up front, so it is
    trimmed rather than discarded - dropping it would lose all routing signal."""
    long = "word " * 400
    cleaned = _clean_contract(long)
    assert cleaned is not None
    assert len(cleaned) <= bootstrap._CONTRACT_MAX_CHARS


# --- forced service linchpins carry a contract (#29) ---------------------------

def test_forced_linchpins_are_minted_with_their_single_sourced_contract():
    props = _svc_props(shells_to_batch([], []))
    for ls in bootstrap._LINCHPIN_SERVICES:
        if not ls.forced:
            continue
        assert props[ls.slug]["service_contract"] == ls.contract
        assert props[ls.slug]["exposure"] == ls.exposure


def test_forced_linchpin_proposed_without_a_contract_is_filled_from_the_constant():
    """The LLM may propose `sign-in` and give it no usable contract. The guaranteed
    account surface must not end up unroutable, so the constant fills the gap."""
    batch = shells_to_batch(
        [ServiceShell(business_function_slug="sign-in", exposure="public")], []
    )
    contract = _svc_props(batch)["sign-in"]["service_contract"]
    assert contract == bootstrap._LINCHPIN_SERVICES[0].contract


def test_an_llm_contract_for_a_forced_linchpin_is_never_clobbered():
    """A KB-grounded contract is richer than the generic constant, so the LLM's wins."""
    batch = shells_to_batch(
        [ServiceShell(business_function_slug="sign-in", exposure="public",
                      service_contract="Sign in with a seller account.")], []
    )
    assert _svc_props(batch)["sign-in"]["service_contract"] == "Sign in with a seller account."


def test_duplicate_slug_fills_empty_slots_per_key_without_clobbering():
    """Two shells for one identity: each key fills independently, and a filled key is
    never overwritten by a later shell."""
    batch = shells_to_batch([
        ServiceShell(business_function_slug="orders", exposure="authenticated"),
        ServiceShell(business_function_slug="orders", exposure="public",
                     service_contract="Track an order to delivery."),
    ], [])
    assert _svc_props(batch)["orders"] == {
        "exposure": "authenticated",                      # first wins, not clobbered
        "service_contract": "Track an order to delivery.",  # second fills the empty slot
    }


# --- out-of-vocabulary System kinds are dropped LOUDLY (#29 D6) ----------------

def test_out_of_vocabulary_system_kind_is_dropped_with_a_warning(caplog):
    """Live, the model proposed `PaymentSystem` and the sole-writer's typo-guard
    swallowed it SILENTLY - so a systematically mis-named KB would yield a
    linchpins-only skeleton that reads like a modelling result."""
    with caplog.at_level("WARNING"):
        batch = shells_to_batch([], [SystemShell(kind="PaymentSystem")])
    kinds = {s.kind for s in batch.systems}
    assert "PaymentSystem" not in kinds
    assert kinds == set(bootstrap._LINCHPIN_SYSTEMS)  # only the forced triad survives
    assert "PaymentSystem" in caplog.text


def test_an_in_vocabulary_system_kind_survives():
    batch = shells_to_batch([], [SystemShell(kind="WAF", claim="KB says 'behind Cloudflare'")])
    assert "WAF" in {s.kind for s in batch.systems}


# The shared bounded retry these tests guarded was RETIRED (#73); the escalating
# retry that replaces it (transient-failure + None-as-failure + exhaustion) is now
# covered by tests/test_llm_providers.py::test_escalating_invoke_*.


# --- the skill seam (#29) ------------------------------------------------------

def test_reasoning_system_prompt_layers_base_plus_skill():
    """#29: the reasoning system message is TWO layers - a stable base prompt (identity,
    pipeline position, output-field contract - the WHAT) plus the operator-tunable
    discipline skill (the 5 stages and service-contract craft - the HOW). The reasoned
    path had earlier LOST the skill seam entirely, leaving reasoning as inline constants."""
    base = bootstrap._BOOTSTRAPPER_BASE_SYSTEM
    assert "Bootstrapper" in base
    assert "business_function_slug" in base  # the output-field contract lives in the base
    skill = bootstrap._load_bootstrapper_skill()
    assert "service contract" in skill  # the discipline that teaches the contract craft


def test_the_skill_carries_the_no_invented_paths_rule():
    """The one content rule the operator ratified: domain nouns and verbs, never a
    guessed path - a guessed path would enter the graph looking like evidence."""
    skill = bootstrap._load_bootstrapper_skill().lower()
    assert "never invent a path" in skill or "never write a path" in skill


def test_a_missing_skill_mount_degrades_to_a_fallback_that_keeps_the_constraints():
    fallback = bootstrap._BOOTSTRAPPER_SKILL_FALLBACK
    assert "service_contract" in fallback
    assert "NEVER write a path" in fallback
    for stage in ("DECOMPOSE", "EXPAND", "GROUND", "WITHHOLD", "DECIDE"):
        assert stage in fallback


def test_both_layers_actually_reach_the_model(monkeypatch):
    """The layering is only real if BOTH halves reach the model. WHICH TURN each rides
    in is the configurable part (the default puts the discipline in the user turn); that
    both are present is not."""
    captured = {}

    def fake_invoke_role(role, messages, *, schema=None, temperature=0):
        captured["system"] = messages[0].content
        captured["human"] = messages[1].content
        return "reasoning"

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    assert bootstrap.default_reason_fn("a juice marketplace", ["checkout"]) == "reasoning"

    both = captured["system"] + captured["human"]
    assert bootstrap._BOOTSTRAPPER_BASE_SYSTEM in both
    assert bootstrap._load_bootstrapper_skill() in both
    # the base (identity + output contract) is ALWAYS the system message, in every arm
    assert bootstrap._BOOTSTRAPPER_BASE_SYSTEM in captured["system"]
    # the run-specific material rides in the HUMAN turn, never the system prompt
    assert "a juice marketplace" in captured["human"]
    assert "checkout" in captured["human"]  # the FR-INVENTORY reuse block


def test_the_breadth_sensitive_reasoning_prompt_stays_free_of_the_linchpin_umbrellas(monkeypatch):
    """Regression guard for commit 760e93d: pushing the account-surface umbrellas into
    the REASONING prompt coarsened the model's granularity prior and collapsed breadth
    25/16/20 -> 13. The pre-auth surface is guaranteed deterministically by the forcing
    in shells_to_batch instead, so the reasoning prompt must stay clean (B-Q2, #31)."""
    captured = {}

    def fake_invoke_role(role, messages, *, schema=None, temperature=0):
        captured["prompt"] = messages[0].content + messages[1].content
        return "reasoning"

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    bootstrap.default_reason_fn("a juice marketplace", [])

    assert "ACCOUNT-SURFACE UMBRELLAS" not in captured["prompt"]
    assert "password-recovery" not in captured["prompt"]


# --- the settings-reading entry point -----------------------------------------

def test_run_bootstrap_reads_operator_kb_from_settings_and_uses_the_reasoned_path():
    """`run_bootstrap` is the ONLY settings-aware entry point, and the API route calls
    it. Before #29 it still delegated to the superseded fail-OPEN single-call path."""
    seen = {}

    def fake_load_settings(project_id):
        return {"operator_kb": "an online marketplace with reviews", "target_domain": "x"}

    def reason_fn(kb, service_slugs):
        seen["kb"] = kb
        return "reasoning"

    def extract_fn(reasoning):
        seen["reasoning"] = reasoning
        return ([ServiceShell(business_function_slug="reviews", exposure="public",
                              service_contract="Read and write product reviews.")], [])

    export = bootstrap.run_bootstrap(
        "proj-1", load_settings_fn=fake_load_settings,
        reason_fn=reason_fn, extract_fn=extract_fn,
        curate_fn=lambda s, sy, p: (len(s), len(sy)), service_slugs=[],
    )
    assert seen["kb"] == "an online marketplace with reviews"
    assert seen["reasoning"] == "reasoning"      # the two-call handoff, not the old path
    assert export.blocked is False


def test_run_bootstrap_on_a_missing_kb_is_a_valid_linchpins_only_proceed():
    export = bootstrap.run_bootstrap(
        "proj-1", load_settings_fn=lambda p: {"target_domain": "x"},
        curate_fn=lambda s, sy, p: (len(s), len(sy)), service_slugs=[],
    )
    assert export.blocked is False
    assert export.systems_written == len(bootstrap._LINCHPIN_SYSTEMS)


def test_the_retired_single_call_path_is_gone():
    """#29 retired the example-polluted, fail-open elicitation. Guarding its absence
    keeps it from being resurrected by a merge."""
    for retired in ("bootstrap_from_kb", "default_elicit_fn", "_BOOTSTRAP_INSTRUCTION"):
        assert not hasattr(bootstrap, retired), f"{retired} should be retired"


def test_forced_linchpin_proposed_without_an_exposure_is_filled_from_the_constant():
    """Same fill-never-clobber rule as the contract: a guaranteed surface that arrives
    exposure-less is only half-guaranteed."""
    batch = shells_to_batch(
        [ServiceShell(business_function_slug="register", service_contract="Sign up.")], []
    )
    props = _svc_props(batch)["register"]
    assert props["exposure"] == "public"                 # filled from the constant
    assert props["service_contract"] == "Sign up."       # the LLM's own, not clobbered


# --- call-1 prompt configurations (#29, operator directive 2026-07-27) ---------

def _capture_prompt(monkeypatch, config=None):
    captured = {}

    def fake_invoke_role(role, messages, *, schema=None, temperature=0):
        captured["system"] = messages[0].content
        captured["human"] = messages[1].content
        return "reasoning"

    if config is None:
        monkeypatch.delenv("BOOTSTRAP_PROMPT_CONFIG", raising=False)
    else:
        monkeypatch.setenv("BOOTSTRAP_PROMPT_CONFIG", config)
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    bootstrap.default_reason_fn("a juice marketplace", [])
    return captured


def test_the_default_is_skill_in_prompt(monkeypatch):
    """Operator-ratified 2026-07-27 on the comparative eval: `skill_in_prompt` had the
    best mean AND the best floor over 15 live runs. Pinning the default here means a
    silent revert shows up as a failure rather than as a quiet breadth loss."""
    assert bootstrap._DEFAULT_PROMPT_CONFIG == "skill_in_prompt"
    cap = _capture_prompt(monkeypatch)
    assert cap["system"] == bootstrap._BOOTSTRAPPER_BASE_SYSTEM
    assert bootstrap._load_bootstrapper_skill() in cap["human"]


def test_baseline_still_reproduces_the_pre_seam_arrangement(monkeypatch):
    """`baseline` must stay byte-identical to what existed before the seam, or every
    measurement taken against it stops being comparable - which is what makes the
    eval's baseline column meaningful at all."""
    cap = _capture_prompt(monkeypatch, "baseline")
    assert cap["system"] == (
        f"{bootstrap._BOOTSTRAPPER_BASE_SYSTEM}\n\n{bootstrap._load_bootstrapper_skill()}"
    )
    for ex in bootstrap._FEW_SHOT:
        assert ex in cap["human"]
    for ex in bootstrap._FEW_SHOT_EXTRA:
        assert ex not in cap["human"]
    assert bootstrap._BREADTH_VERBATIM not in cap["human"]


def test_skill_in_prompt_moves_the_discipline_to_the_user_turn(monkeypatch):
    cap = _capture_prompt(monkeypatch, "skill_in_prompt")
    skill = bootstrap._load_bootstrapper_skill()
    assert skill not in cap["system"]           # system keeps identity/output contract only
    assert cap["system"] == bootstrap._BOOTSTRAPPER_BASE_SYSTEM
    assert skill in cap["human"]                # ... and the discipline rides beside the task


def test_more_fewshot_adds_the_extra_exemplars(monkeypatch):
    cap = _capture_prompt(monkeypatch, "more_fewshot")
    for ex in list(bootstrap._FEW_SHOT) + list(bootstrap._FEW_SHOT_EXTRA):
        assert ex in cap["human"]


def test_breadth_verbatim_adds_the_elicit_then_debug_block(monkeypatch):
    cap = _capture_prompt(monkeypatch, "breadth_verbatim")
    assert bootstrap._BREADTH_VERBATIM in cap["human"]
    assert "SPLIT it" in cap["human"]           # the operative debugging instruction
    # ... and it must NOT become licence to invent (the withholding discipline holds)
    assert "still needs its own support in the text" in cap["human"]


def test_combined_applies_every_variant(monkeypatch):
    cap = _capture_prompt(monkeypatch, "combined")
    assert bootstrap._load_bootstrapper_skill() in cap["human"]
    assert bootstrap._FEW_SHOT_EXTRA[0] in cap["human"]
    assert bootstrap._BREADTH_VERBATIM in cap["human"]


def test_an_unknown_config_falls_back_to_the_default_loudly(monkeypatch, caplog):
    """A typo'd config must not silently produce an unrecorded prompt arrangement -
    that would make an eval result untraceable to what actually ran."""
    with caplog.at_level("WARNING"):
        cap = _capture_prompt(monkeypatch, "nonsense")
    assert cap["human"] == _capture_prompt(monkeypatch, bootstrap._DEFAULT_PROMPT_CONFIG)["human"]
    assert "nonsense" in caplog.text
    assert bootstrap._DEFAULT_PROMPT_CONFIG in caplog.text


def test_the_account_umbrellas_stay_out_of_every_config(monkeypatch):
    """The 760e93d regression guard must hold across ALL arms, not just baseline."""
    for cfg in bootstrap._PROMPT_CONFIGS:
        cap = _capture_prompt(monkeypatch, cfg)
        blob = cap["system"] + cap["human"]
        assert "ACCOUNT-SURFACE UMBRELLAS" not in blob, cfg
        assert "password-recovery" not in blob, cfg
