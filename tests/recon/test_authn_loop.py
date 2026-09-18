"""Unit tier: the authn loop's pure state machine (#223, T3 #242).

Covers the documented transition table as a pure contract (the hunting
`hunter_state` precedent): detection is a pure function of the observed tool
call, pushes never gate or reject, and each boundary carries its hint. Plus
the branch contract (D223-11), the missing-data gate (D223-17), and the
branch pruning rule - all pure, all in memory, no LLM, no store.
"""
from __future__ import annotations

import pytest

from polymerhus.recon.control import authn_loop as L


def _obs(tool, args=None, result=None):
    return {"tool": tool, "args": args or {}, "result": result}


def _read_envelope(path, value):
    return {"ok": True, "command": "read", "path": path, "value": value}


# --- detection: pure function of the observed call ---------------------------


def test_detect_grounding_reads():
    assert L.detect_transition(_obs("auth_store", {"command": "read", "path": ""})) == "ground"
    assert L.detect_transition(_obs("auth_store", {"command": "read", "path": "overview"})) == "ground"


def test_detect_narrow_overview_read_is_neutral():
    assert L.detect_transition(
        _obs("auth_store", {"command": "read", "path": "overview.notes"})) == "none"


def test_detect_accounts_reads():
    assert L.detect_transition(_obs("auth_store", {"command": "read", "path": "accounts"})) == "retrieve"
    assert L.detect_transition(
        _obs("auth_store", {"command": "read", "path": "accounts.alice"})) == "retrieve"


def test_detect_narrow_account_read_is_neutral():
    assert L.detect_transition(
        _obs("auth_store", {"command": "read", "path": "accounts.alice.tokens"})) == "none"


def test_detect_skill_loads():
    assert L.detect_transition(_obs("load_skill", {"name": "authn"}, "body")) == "skill"
    assert L.detect_transition(_obs("load_skill", {"name": "authn"}, "")) == "skill_absent"
    assert L.detect_transition(_obs("load_skill", {"name": "authn"}, None)) == "skill_absent"
    assert L.detect_transition(_obs("load_skill", {"name": "steel-browser"}, "body")) == "none"


def test_detect_probes():
    assert L.detect_transition(_obs("execute_command", {"command": "curl .."})) == "probe"
    assert L.detect_transition(_obs("steel_exec", {"command": "steel browser open"})) == "probe"


def test_detect_validity_assertions():
    write = {"command": "write"}
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice", "value": {"status": "not_valid"}})) == "invalidate"
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice.status", "value": "not_valid"})) == "invalidate"
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice", "value": {"status": "valid"}})) == "validate"
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice.status", "value": "valid"})) == "validate"
    # a write carrying any other status value is not a validity boundary
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice.status", "value": "stale"})) == "none"
    # a non-status write is not a validity boundary
    assert L.detect_transition(_obs(
        "auth_store", {**write, "path": "accounts.alice.notes", "value": "hi"})) == "none"


def test_detect_never_raises_on_garbage():
    for bad in (None, {}, {"tool": "auth_store"}, {"tool": "auth_store", "args": None},
                {"tool": "auth_store", "args": {"command": "read", "path": ["x"]}},
                "a string", 42):
        assert L.detect_transition(bad) == "none"


def test_detect_unknown_tools_are_neutral():
    assert L.detect_transition(_obs("write_skill", {"skill": "authn"})) == "none"
    assert L.detect_transition(_obs("something_else", {})) == "none"


# --- push: the phase path ----------------------------------------------------


def test_grounding_completes_when_both_evidences_seen():
    state = L.initial_state()
    assert state["phase"] == "GROUNDED"
    state = L.push_transition(state, "ground", _obs("auth_store", {"command": "read", "path": "overview"}))
    assert state["phase"] == "GROUNDED" and state["injected_hint"] is None
    state = L.push_transition(state, "skill", _obs("load_skill", {"name": "authn"}, "body"))
    assert state["grounded"] is True
    assert state["injected_hint"] == L.GROUNDED_HINT
    # a repeat grounding read is not a transition: no second hint
    state = L.push_transition(state, "ground", _obs("auth_store", {"command": "read", "path": "overview"}))
    assert state["injected_hint"] is None


def test_grounding_order_does_not_matter():
    state = L.initial_state()
    state = L.push_transition(state, "skill", _obs("load_skill", {"name": "authn"}, "body"))
    assert state["injected_hint"] is None
    state = L.push_transition(state, "ground", _obs("auth_store", {"command": "read", "path": ""}))
    assert state["grounded"] is True
    assert state["injected_hint"] == L.GROUNDED_HINT


def test_missing_skill_still_grounds_but_flags_self_service():
    state = L.initial_state()
    state = L.push_transition(state, "ground", _obs("auth_store", {"command": "read", "path": ""}))
    state = L.push_transition(state, "skill_absent", _obs("load_skill", {"name": "authn"}, ""))
    assert state["grounded"] is True
    assert state["skill_missing"] is True


def _accounts_payload(names=(), statuses=None):
    accounts = {}
    for name in names:
        record = {"origin": "operator", "credentials": {"username": "u", "password": "p",
                                                        "login_url": "https://x/login"}}
        if statuses and name in statuses:
            record["status"] = statuses[name]
        accounts[name] = record
    return accounts


def test_retrieve_with_usable_account_moves_to_validation_span():
    state = L.initial_state()
    obs = _obs("auth_store", {"command": "read", "path": "accounts"},
               _read_envelope("accounts", _accounts_payload(("alice",))))
    state = L.push_transition(state, "retrieve", obs)
    assert state["phase"] == "RETRIEVED"
    assert state["usable_accounts"] == ("alice",)
    assert state["injected_hint"] == L.RETRIEVED_HINT


def test_retrieve_with_no_usable_account_goes_directly_to_generation():
    state = L.initial_state()
    obs = _obs("auth_store", {"command": "read", "path": "accounts"},
               _read_envelope("accounts", _accounts_payload(("alice",), {"alice": "not_valid"})))
    state = L.push_transition(state, "retrieve", obs)
    assert state["phase"] == "GENERATION"
    assert state["injected_hint"] == L.GENERATION_SIGNIN_HINT


def test_retrieve_with_no_skill_falls_back_to_self_service():
    state = L.initial_state()
    state = L.push_transition(state, "skill_absent", _obs("load_skill", {"name": "authn"}, ""))
    obs = _obs("auth_store", {"command": "read", "path": "accounts"},
               _read_envelope("accounts", {}))
    state = L.push_transition(state, "retrieve", obs)
    assert state["phase"] == "GENERATION"
    assert state["injected_hint"] == L.SELF_SERVICE_HINT


def test_empty_path_read_grounds_and_retrieves_from_one_payload():
    full = {"overview": {"login_endpoint": "https://x/login"},
            "accounts": _accounts_payload(("alice",))}
    state = L.initial_state()
    state = L.push_transition(state, "skill", _obs("load_skill", {"name": "authn"}, "body"))
    obs = _obs("auth_store", {"command": "read", "path": ""}, _read_envelope("", full))
    state = L.push_transition(state, "retrieve", obs)
    assert state["overview_seen"] is True
    assert state["phase"] == "RETRIEVED"


def test_first_probe_enters_validation_and_counts():
    state = L.initial_state()
    state = L.push_transition(state, "retrieve", _obs(
        "auth_store", {"command": "read", "path": "accounts"},
        _read_envelope("accounts", _accounts_payload(("alice",)))))
    probe = _obs("execute_command", {"command": "curl https://x"})
    state = L.push_transition(state, "probe", probe)
    assert state["phase"] == "VALIDATION"
    assert state["probe_count"] == 1
    assert state["injected_hint"] == L.VALIDATION_HINT
    # later validation probes are counted, not re-hinted
    state = L.push_transition(state, "probe", probe)
    assert state["probe_count"] == 2
    assert state["injected_hint"] is None


def test_not_valid_assertion_enters_generation():
    state = L.initial_state()
    state = L.push_transition(state, "retrieve", _obs(
        "auth_store", {"command": "read", "path": "accounts"},
        _read_envelope("accounts", _accounts_payload(("alice",)))))
    state = L.push_transition(state, "probe", _obs("execute_command", {"command": "curl"}))
    write = _obs("auth_store", {"command": "write", "path": "accounts.alice.status",
                                "value": "not_valid"})
    state = L.push_transition(state, "invalidate", write)
    assert state["phase"] == "GENERATION"
    assert state["account"] == "alice"
    assert state["injected_hint"] == L.GENERATION_HINT


def test_second_attempt_enters_debug_with_no_cap():
    state = L.initial_state()
    state = L.push_transition(state, "invalidate", _obs(
        "auth_store", {"command": "write", "path": "accounts.alice.status", "value": "not_valid"}))
    attempt = _obs("execute_command", {"command": "curl login"})
    state = L.push_transition(state, "probe", attempt)
    assert state["phase"] == "GENERATION"  # first attempt stays, no new hint
    assert state["injected_hint"] is None
    state = L.push_transition(state, "probe", attempt)
    assert state["phase"] == "DEBUG"
    assert state["injected_hint"] == L.DEBUG_HINT
    # the debug span has no mechanical cap: attempts keep observing, never reject
    for _ in range(25):
        state = L.push_transition(state, "probe", attempt)
    assert state["phase"] == "DEBUG"
    assert state["attempt_count"] == 27


def test_valid_assertion_finishes_and_runs_the_outer_loop_hint():
    state = L.initial_state()
    write = _obs("auth_store", {"command": "write", "path": "accounts.alice.status", "value": "valid"})
    state = L.push_transition(state, "validate", write)
    assert state["phase"] == "FINISH"
    assert state["account"] == "alice"
    assert state["injected_hint"] == L.FINISH_HINT


def test_finish_is_terminal_and_hint_free():
    state = L.initial_state()
    state = L.push_transition(state, "validate", _obs(
        "auth_store", {"command": "write", "path": "accounts.alice.status", "value": "valid"}))
    for transition in ("ground", "skill", "retrieve", "probe", "invalidate", "validate", "none"):
        state = L.push_transition(state, transition, _obs("execute_command", {"command": "x"}))
        assert state["phase"] == "FINISH"
        assert state["injected_hint"] is None


def test_out_of_order_probe_never_gates():
    # a probe before any retrieval is recorded, never rejected, never moves phase
    state = L.initial_state()
    state = L.push_transition(state, "probe", _obs("execute_command", {"command": "curl"}))
    assert state["phase"] == "GROUNDED"
    assert state["injected_hint"] is None


def test_push_never_rejects_and_never_mutates():
    before = L.initial_state()
    snapshot = dict(before)
    for transition in ("ground", "skill", "skill_absent", "retrieve", "probe",
                       "invalidate", "validate", "none", "bogus"):
        after = L.push_transition(before, transition, _obs("execute_command", {}))
        assert after["phase"] in L.PHASES
    assert dict(before) == snapshot


# --- the branch contract (D223-11) --------------------------------------------


def test_branch_no_defence_is_request():
    assert L.select_branch({}) == "request"
    assert L.select_branch(None) == "request"
    assert L.select_branch({"login_endpoint": "https://x/login"}) == "request"
    assert L.select_branch({"anti-bot": None, "http-client-replayability": False}) == "request"


def test_branch_false_replayability_is_browser_only():
    assert L.select_branch({"anti-bot": "waf:cloudflare",
                            "http-client-replayability": False}) == "browser_only"


def test_branch_true_replayability_is_request_with_browser_first():
    assert L.select_branch({"anti-bot": "waf:cloudflare",
                            "http-client-replayability": True}) == "request_browser_first"


def test_branch_null_replayability_resolves_in_loop():
    assert L.select_branch({"anti-bot": "waf:cloudflare",
                            "http-client-replayability": None}) == "resolve_in_loop"
    assert L.select_branch({"anti-bot": "waf:cloudflare"}) == "resolve_in_loop"


# --- the missing-data gate (D223-17) ------------------------------------------


def test_gate_empty_store_is_no_auth_surface():
    assert L.classify_gate({}, {}) == "no_auth_surface"
    assert L.classify_gate(None, {}) == "no_auth_surface"


def test_gate_declared_surface_without_accounts_is_missing_credentials():
    assert L.classify_gate({"login_endpoint": "https://x/login"}, {}) == "missing_credentials"
    assert L.classify_gate({"anti-bot": "waf:x"}, {}) == "missing_credentials"


def test_gate_marker_wins_over_a_declared_surface():
    overview = {"login_endpoint": "https://x/login",
                "notes": "Target has NO AUTHENTICATED SURFACE."}
    assert L.classify_gate(overview, {}) == "no_auth_surface"


def test_gate_any_accounts_run_the_loop():
    overview = {"login_endpoint": "https://x/login"}
    assert L.classify_gate(overview, _accounts_payload(("alice",))) == "run_loop"
    # even all-known-bad accounts run the loop: the loop judges, the gate does not
    assert L.classify_gate(
        overview, _accounts_payload(("alice",), {"alice": "not_valid"})) == "run_loop"
    # accounts without an overview still run the loop (request branch)
    assert L.classify_gate({}, _accounts_payload(("alice",))) == "run_loop"


# --- pruning ------------------------------------------------------------------


def test_browser_only_prunes_to_the_steel_crawl():
    plan = [["subfinder", "whois"], ["httpx"], ["katana", "steel_crawl"]]
    assert L.prune_plan(plan, "browser_only") == [["steel_crawl"]]


def test_request_branches_keep_the_plan():
    plan = [["subfinder"], ["httpx"]]
    assert L.prune_plan(plan, "request") == plan
    assert L.prune_plan(plan, "request") is not plan


def test_verdict_defaults_are_the_loud_fail_open_shape():
    verdict = L.GatewayVerdict()
    assert verdict.outcome == "failed"
    assert verdict.account is None
    assert verdict.branch == "request"
    assert verdict.replayability_resolved is False
    assert verdict.replayability is None
