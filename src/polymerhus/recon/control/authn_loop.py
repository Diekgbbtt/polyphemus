"""The authn loop's state vocabulary (#223, T3 #242): the pure state-machine module.

The single source of truth for the gateway turn's loop tracking (spec "The
authn loop (the core)", D223-15): the six loop phases, the passive
detect/push transition logic, the injected transition hints, the branch
contract (D223-11), the missing-data gate (D223-17), the gateway verdict, and
the branch pruning rule.

This module is PURE by construction (the `hunter_state.py` precedent): it
imports no driver, performs no I/O at import, and holds no side effects. The
machine is PASSIVE - the harness observes the model's tool calls,
`detect_transition` maps one observed call to a transition name, and
`push_transition` moves the phase. It NEVER gates a tool call on the current
phase and never rejects an out-of-order observation: the tracker records what
the model signalled (the no-block invariant). `detect_transition` is a pure
function of the observed call alone (tool name, args, result) and never
consults the state; `push_transition` always returns a NEW state, never
mutates, never raises.

Transition table (spec, D223-15):

| Phase      | Entered on (observable tool call)                              | Hint on entry                          | Exits                                  |
| GROUNDED   | start; `auth_store` read of `overview` AND `load_skill("authn")` | retrieve and select the account        | RETRIEVED on an `accounts` read        |
|            | both observed (either order)                                    | (when grounding completes first)       | (listing, single record, or the empty  |
|            |                                                                 |                                        | full-state read - unconditional);      |
|            |                                                                 |                                        | GENERATION when the read holds no      |
|            |                                                                 |                                        | usable account                         |
| RETRIEVED  | `accounts` read holding a usable account (the empty       | validate the selected account          | VALIDATION on the first probe          |
|            | full-state read retrieves too, recording grounding alongside)   |                                        |                                        |
| VALIDATION | first probe (`execute_command` / `steel_exec`) after RETRIEVED  | conclude valid or not_valid            | GENERATION on the `not_valid` write;   |
|            |                                                                 |                                        | FINISH on the `valid` write            |
| GENERATION | `not_valid` write, or a no-usable-account read                  | run the sign-in procedure              | DEBUG at the second attempt call;      |
|            |                                                                 |                                        | FINISH when sign-in persists state     |
| DEBUG      | second and later attempt calls in the sign-in span              | per-attempt trace hint, NO cap         | FINISH on success or the terminal      |
|            |                                                                 |                                        | `exhausted` verdict                    |
| FINISH     | `valid` write (success boundary)                                | judge the skill, then emit the verdict | terminal                               |

The `exhausted` verdict is the model's own declaration emitted as the
structured turn output (D223-3/D223-16), not a tool call, so no transition
observes it: the harness records FINISH on the `valid` write and the turn's
verdict carries exhaustion. `write_skill`/`load_skill` calls after FINISH are
the outer skill-judging loop's tool boundary (D223-11): observed, never a
transition, never hinted.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Mapping, TypedDict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- the loop phases ----------------------------------------------------------

AuthnPhase = Literal["GROUNDED", "RETRIEVED", "VALIDATION", "GENERATION", "DEBUG", "FINISH"]
"""The authn loop's phases (spec transition table, D223-15)."""

PHASES: tuple[AuthnPhase, ...] = (
    "GROUNDED", "RETRIEVED", "VALIDATION", "GENERATION", "DEBUG", "FINISH",
)
"""The six loop phases in canonical order."""

AuthnTransition = Literal[
    "ground", "skill", "skill_absent", "retrieve", "probe",
    "invalidate", "validate", "none",
]
"""The transition names the detector maps one observed tool call to."""


class AuthnLoopState(TypedDict):
    """The tracker's channels: the loop phase plus the grounding evidence,
    the sign-in span counters, and the hint riding the triggering result."""

    phase: AuthnPhase
    grounded: bool
    overview_seen: bool
    skill_seen: bool
    skill_missing: bool
    accounts_seen: bool
    account: str | None
    usable_accounts: tuple[str, ...]
    probe_count: int
    attempt_count: int
    injected_hint: str | None


def initial_state() -> AuthnLoopState:
    """A fresh tracker: the turn opens in GROUNDED, the grounding span."""
    return AuthnLoopState(
        phase="GROUNDED", grounded=False, overview_seen=False, skill_seen=False,
        skill_missing=False, accounts_seen=False, account=None,
        usable_accounts=(), probe_count=0, attempt_count=0, injected_hint=None,
    )


# --- the transition hints (spec G9-analogue) -----------------------------------

GROUNDED_HINT = (
    "Grounded on the overview and the authn procedure. Retrieve and select "
    "the account: read the accounts and pick the most recently updated usable "
    "account (skip any asserted not_valid)."
)
"""Injected when grounding completes: retrieve and select the account."""

RETRIEVED_HINT = (
    "Account selected. Validate it first: replay its stored request state "
    "(snapshot, tokens) with the exec capability, or mount its Steel profile "
    "and verify the session per the branch directive. Conclude by asserting "
    "the account status valid or not_valid in the store before any sign-in."
)
"""Injected on RETRIEVED: validate the selected account."""

VALIDATION_HINT = (
    "Validation probe observed. Conclude it: on a live session assert the "
    "account status valid; on a dead one assert not_valid, then run the "
    "sign-in procedure."
)
"""Injected on the first validation probe: conclude valid or not_valid."""

GENERATION_HINT = (
    "The account is asserted not_valid. Run the sign-in procedure from the "
    "authn skill (request replay or browser flow per the branch directive). "
    "There is no mechanical attempt cap: keep debugging while progress is "
    "real; declare the space exhausted through the terminal failed verdict "
    "when it is not."
)
"""Injected on GENERATION: run the sign-in procedure."""

GENERATION_SIGNIN_HINT = (
    "No usable account on record. Run the sign-in procedure from the authn "
    "skill to mint one (request replay or browser flow per the branch "
    "directive), then persist the profile key plus extracted tokens and "
    "assert the account status valid. There is no mechanical attempt cap; "
    "declare the space exhausted through the terminal failed verdict when "
    "no sign-in path remains."
)
"""Injected when the accounts read holds no usable account: sign in to mint."""

SELF_SERVICE_HINT = (
    "No usable account and no authn skill bundle. Fall back to request-based "
    "self-service driven by the store's description and procedure: attempt "
    "sign-in over plain HTTP, persist what succeeds, and say so in the "
    "verdict rationale. A thin description yields a blind attempt; that "
    "residual risk is accepted, not mitigated."
)
"""Injected when the skill is missing too: fail-open self-service (D223-17)."""

DEBUG_HINT = (
    "Sign-in attempt observed and traced. Adjust one variable and retry, or "
    "declare the tweaking space exhausted through the terminal failed "
    "verdict. No cap, no rejection: the span ends on success or exhaustion."
)
"""Injected per attempt in DEBUG: trace, tweak, or declare exhausted."""

FINISH_HINT = (
    "Authenticated state persisted. Run the outer loop: re-read the authn "
    "skill, judge what this target taught (a blocking condition, a replay "
    "fact, a selector fix), and write the reusable part back through "
    "write_skill. Then emit the gateway verdict."
)
"""Injected on FINISH: judge the skill, then emit the verdict."""

TRANSITION_HINTS: dict[str, str] = {
    "ground": GROUNDED_HINT,
    "skill": GROUNDED_HINT,
    "retrieve": RETRIEVED_HINT,
    "probe": VALIDATION_HINT,
    "invalidate": GENERATION_HINT,
    "validate": FINISH_HINT,
}
"""The static hint per transition ("none" and "skill_absent" carry none:
"none" is not a transition; the absent-skill case resolves its hint at
retrieval, when usability is known)."""

_HINT_TAG = "authn-loop-hint"
"""The wrapper tagging an injected hint (the hunting
`<phase-transition-hint>` precedent): the hint rides the TRIGGERING tool
result only, inside this tag, and is consumed immediately."""

PROBE_TOOLS = frozenset({"execute_command", "steel_exec"})
"""The probe surface: the Kali exec capability and the Steel exec gateway
(D223-13). Any other tool call is never a probe."""


def wrap_hint(hint: str) -> str:
    """Wrap a hint for the triggering tool result (consumed immediately,
    never leaked onto a later result)."""
    return f"<{_HINT_TAG}>\n{hint}\n</{_HINT_TAG}>"


# --- detection: pure function of the observed call ------------------------------

def _bool_arg(value: Any) -> bool:
    return isinstance(value, bool) and value


def _detect_store(args: Mapping[str, Any]) -> AuthnTransition:
    command = args.get("command")
    path = args.get("path")
    if not isinstance(path, str):
        return "none"
    if command == "read":
        if path == "overview":
            return "ground"
        if path == "" or path == "accounts":
            # the full-state read carries the accounts too: it retrieves (the
            # GROUNDED exit is unconditional - "RETRIEVED on an accounts
            # read" - and the push records the grounding evidence alongside)
            return "retrieve"
        segments = path.split(".")
        if segments[0] == "accounts" and len(segments) == 2:
            return "retrieve"  # a single-record read evidences selection
        return "none"
    if command == "write":
        segments = path.split(".")
        if segments[0] != "accounts" or len(segments) < 2:
            return "none"
        value = args.get("value")
        status: Any = None
        if len(segments) == 2 and isinstance(value, dict):
            status = value.get("status")  # CREATE carrying the assertion
        elif len(segments) == 3 and segments[2] == "status":
            status = value  # the leaf assertion
        if status == "not_valid":
            return "invalidate"
        if status == "valid":
            return "validate"
        return "none"
    return "none"


def _detect_skill(args: Mapping[str, Any], result: Any) -> AuthnTransition:
    if args.get("name") != "authn":
        return "none"
    # absence is the fail-open empty (`load_skill` degrades to `''` on an
    # unknown skill, never to a shaped value): None, blank text, or no text
    # parts mean the bundle is missing; any other shape is not evidence of
    # absence, so it counts as loaded and the retrieval hint decides later.
    content = getattr(result, "content", result)
    if content is None:
        return "skill_absent"
    if isinstance(content, str):
        return "skill_absent" if not content.strip() else "skill"
    if isinstance(content, list):
        parts = [p.get("text") for p in content
                 if isinstance(p, dict) and isinstance(p.get("text"), str)]
        joined = "\n".join(parts)
        return "skill_absent" if not joined.strip() else "skill"
    return "skill"


def detect_transition(observation: Any) -> AuthnTransition:
    """Map one observed tool call to a transition name.

    A pure function of the observed call verbatim (tool name, args, result):
    it never consults the tracker state. Anything unrecognised - another tool,
    a narrow read, a non-status write, a malformed observation - maps to
    "none" (no state move). Never raises: garbage maps to "none"."""
    try:
        if not isinstance(observation, Mapping):
            return "none"
        tool = observation.get("tool")
        args = observation.get("args")
        if not isinstance(args, Mapping):
            return "none"
        if tool == "auth_store":
            return _detect_store(args)
        if tool == "load_skill":
            return _detect_skill(args, observation.get("result"))
        if tool in PROBE_TOOLS:
            return "probe"
        return "none"
    except Exception:  # noqa: BLE001 - detection never breaks the turn
        logger.warning("authn loop detection degraded on %r", observation)
        return "none"


# --- push: the passive phase mover (never gates, never rejects) -----------------

def _parse_result(result: Any) -> Any | None:
    """Best-effort parse of a tool result into its structured value (the
    auth_store envelope dict): ToolMessage content arrives stringified, so
    JSON first, literal second, raw passthrough last. None when unparseable -
    the push treats that as unknown, never as empty."""
    content = getattr(result, "content", result)
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    import json as _json  # noqa: PLC0415 - stdlib, local to the parse
    text = content.strip()
    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:  # noqa: BLE001 - fall through to the literal parse
        pass
    try:
        import ast as _ast  # noqa: PLC0415 - stdlib, local to the parse
        return _ast.literal_eval(text)
    except Exception:  # noqa: BLE001 - unparseable stays unknown
        return None


def _accounts_from_observation(observation: Mapping[str, Any]) -> dict | None:
    """The accounts mapping carried by an accounts-read observation, or None
    when the result is absent or unparseable (unknown, never empty)."""
    args = observation.get("args")
    path = args.get("path") if isinstance(args, Mapping) else None
    parsed = _parse_result(observation.get("result"))
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("value", parsed)
    if path == "":
        value = value.get("accounts") if isinstance(value, dict) else None
    elif isinstance(path, str) and path.startswith("accounts.") and len(path.split(".")) == 2:
        name = path.split(".")[1]
        value = {name: value} if isinstance(value, dict) else None
    return value if isinstance(value, dict) else None


def _usable_names(accounts: Mapping[str, Any]) -> tuple[str, ...]:
    """The usable account names: records not asserted `not_valid` (the loop
    asserted they failed - re-selecting one replays a dead session)."""
    return tuple(
        name for name, record in accounts.items()
        if isinstance(record, dict) and record.get("status") != "not_valid"
    )


def _account_from_write(args: Mapping[str, Any]) -> str | None:
    path = args.get("path") if isinstance(args, Mapping) else None
    if not isinstance(path, str):
        return None
    segments = path.split(".")
    if segments[0] == "accounts" and len(segments) >= 2 and segments[1]:
        return segments[1]
    return None


def _move(state: AuthnLoopState, phase: AuthnPhase, hint: str | None = None, **updates) -> AuthnLoopState:
    """Return the NEW tracker with the phase moved and the hint set (never
    mutating the input). A None hint means this observation carries no next
    step - repeats and out-of-order calls record silently."""
    new_state = dict(state)
    new_state["phase"] = phase
    new_state["injected_hint"] = hint
    new_state.update(updates)
    return new_state


def _push_ground(state: AuthnLoopState) -> AuthnLoopState:
    new_state = dict(state)
    new_state["overview_seen"] = True
    if (state["phase"] == "GROUNDED" and state["skill_seen"] and not state["grounded"]):
        new_state["grounded"] = True
        new_state["injected_hint"] = GROUNDED_HINT
    else:
        new_state["injected_hint"] = None
    return new_state


def _push_skill(state: AuthnLoopState, *, missing: bool) -> AuthnLoopState:
    new_state = dict(state)
    new_state["skill_seen"] = True
    if missing:
        new_state["skill_missing"] = True
    if (state["phase"] == "GROUNDED" and state["overview_seen"] and not state["grounded"]):
        new_state["grounded"] = True
        new_state["injected_hint"] = GROUNDED_HINT
    else:
        new_state["injected_hint"] = None
    return new_state


def _push_retrieve(state: AuthnLoopState, observation: Mapping[str, Any]) -> AuthnLoopState:
    if state["phase"] == "FINISH":
        return _move(state, "FINISH")
    new_state = dict(state)
    new_state["accounts_seen"] = True
    args = observation.get("args")
    if isinstance(args, Mapping) and args.get("path") == "":
        new_state["overview_seen"] = True  # the full-state read grounds too
    accounts = _accounts_from_observation(observation)
    if accounts is None:
        # unparseable result: record the read, hint nothing (fail-open - the
        # loop still follows its prompt; the verdict covers the outcome)
        new_state["injected_hint"] = None
        return new_state
    usable = _usable_names(accounts)
    new_state["usable_accounts"] = usable
    if state["phase"] != "GROUNDED":
        # a re-read later in the loop: recorded, never a second transition
        new_state["injected_hint"] = None
        return new_state
    # the GROUNDED exit is unconditional (spec table): an accounts read moves
    # the loop even when the skill half of grounding is still open - the model
    # still loads the skill per its prompt order, observed silently.
    if usable:
        new_state["phase"] = "RETRIEVED"
        new_state["injected_hint"] = RETRIEVED_HINT
        return new_state
    # no usable account (L3): straight into the sign-in span
    new_state["phase"] = "GENERATION"
    new_state["injected_hint"] = SELF_SERVICE_HINT if state["skill_missing"] else GENERATION_SIGNIN_HINT
    return new_state


def _push_probe(state: AuthnLoopState) -> AuthnLoopState:
    phase = state["phase"]
    if phase == "RETRIEVED":
        return _move(state, "VALIDATION", VALIDATION_HINT, probe_count=1)
    if phase == "VALIDATION":
        return _move(state, "VALIDATION", None, probe_count=state["probe_count"] + 1)
    if phase == "GENERATION":
        attempts = state["attempt_count"] + 1
        if attempts >= 2:
            return _move(state, "DEBUG", DEBUG_HINT, attempt_count=attempts)
        return _move(state, "GENERATION", None, attempt_count=attempts)
    if phase == "DEBUG":
        # the debug span has no mechanical cap (D223-16): attempts are
        # observed and traced, never capped or rejected
        return _move(state, "DEBUG", DEBUG_HINT, attempt_count=state["attempt_count"] + 1)
    # GROUNDED (out of order) and FINISH (terminal): record, move nothing
    return _move(state, phase)


def push_transition(
    state: AuthnLoopState,
    transition: str,
    observation: Any = None,
) -> AuthnLoopState:
    """Return the NEW tracker with the phase moved (never mutate in place).

    The passive mover: grounding evidence completes GROUNDED, an accounts read
    retrieves (or enters the sign-in span when nothing is usable), the first
    probe validates, the `not_valid` write generates, later attempts debug,
    the `valid` write finishes. A transition is NEVER gated on the phase: an
    out-of-order or repeated observation records silently (no hint), an
    unknown transition returns an unchanged copy, and nothing here ever raises
    - the machine records what the model signalled."""
    try:
        obs = observation if isinstance(observation, Mapping) else {}
        if transition == "ground":
            return _push_ground(state)
        if transition in ("skill", "skill_absent"):
            return _push_skill(state, missing=transition == "skill_absent")
        if transition == "retrieve":
            return _push_retrieve(state, obs)
        if transition == "probe":
            return _push_probe(state)
        if transition == "invalidate":
            if state["phase"] == "FINISH":
                return _move(state, "FINISH")
            return _move(state, "GENERATION", GENERATION_HINT,
                         attempt_count=0, account=_account_from_write(obs.get("args", {})))
        if transition == "validate":
            if state["phase"] == "FINISH":
                return _move(state, "FINISH")
            # the success boundary is the loop's assertion act (the call
            # args), not its persistence: on an operator-stamped account the
            # store refuses operator_immutable and the validity rides the
            # verdict instead - the boundary still moved.
            return _move(state, "FINISH", FINISH_HINT,
                         account=_account_from_write(obs.get("args", {})))
        return _move(state, state["phase"])
    except Exception:  # noqa: BLE001 - the tracker never breaks the turn
        logger.warning("authn loop push degraded on %r", transition)
        return dict(state)


# --- the branch contract (D223-11) ------------------------------------------------

BranchDirective = Literal["request", "browser_only", "request_browser_first", "resolve_in_loop"]
"""The gateway's pre-loop branch directive from the operator overview facts."""

BRANCH_DIRECTIVES: tuple[BranchDirective, ...] = (
    "request", "browser_only", "request_browser_first", "resolve_in_loop",
)


def select_branch(overview: Any) -> BranchDirective:
    """The four-way branch contract over the operator overview facts: no
    defence recorded (or an absent overview) -> the request branch; a defence
    with replayability false -> browser-only; true -> request with
    browser-first validation; null (or any non-bool) -> resolved in-loop by
    the fingerprint replayability check. Never raises: garbage selects the
    request branch (fail-open, the loop still judges)."""
    try:
        if not isinstance(overview, Mapping):
            return "request"
        if not overview.get("anti-bot"):
            return "request"
        replayability = overview.get("http-client-replayability")
        if replayability is False:
            return "browser_only"
        if replayability is True:
            return "request_browser_first"
        return "resolve_in_loop"
    except Exception:  # noqa: BLE001 - branch selection never breaks the run
        logger.warning("authn loop branch selection degraded on %r", overview)
        return "request"


# --- the missing-data gate (D223-17) -----------------------------------------------

NO_AUTH_MARKER = "no authenticated surface"
"""The structural no-auth-surface marker: matched case-insensitively inside
`overview.notes` (the only free-text overview field)."""

GatePath = Literal["run_loop", "no_auth_surface", "missing_credentials"]
"""The gateway's pre-turn gate: run the authn loop, skip it (anonymous), or
stop the run (missing prerequisite)."""


def declares_auth_surface(overview: Any) -> bool:
    """Whether the overview declares an authenticated surface: any truthy
    field other than the free-text `notes` (endpoint, mechanism, defence,
    replayability, headers, fingerprinting, conditions)."""
    if not isinstance(overview, Mapping):
        return False
    return any(
        value for key, value in overview.items()
        if key != "notes" and value not in (None, "", [], {})
    )


def has_no_auth_marker(overview: Any) -> bool:
    """Whether the overview carries the structural no-auth-surface marker."""
    if not isinstance(overview, Mapping):
        return False
    notes = overview.get("notes")
    return isinstance(notes, str) and NO_AUTH_MARKER in notes.lower()


def classify_gate(overview: Any, accounts: Any) -> GatePath:
    """Discriminate the missing-data states structurally in the store, never
    from the target's behaviour: any accounts at all run the loop (even
    all-known-bad ones - the loop judges, the gate does not); with no
    accounts, a marked or undeclared surface is the expected-shape anonymous
    path, while a declared surface with no credentials is the missing
    prerequisite that stops the run. Never raises: garbage runs the loop."""
    try:
        if isinstance(accounts, Mapping) and accounts:
            return "run_loop"
        if has_no_auth_marker(overview) or not declares_auth_surface(overview):
            return "no_auth_surface"
        return "missing_credentials"
    except Exception:  # noqa: BLE001 - the gate never breaks the run
        logger.warning("authn loop gate degraded on %r", overview)
        return "run_loop"


# --- the gateway verdict ------------------------------------------------------------

VerdictBranch = Literal["request", "browser_only"]
"""The verdict's branch: the loop's terminal release decision. The in-loop
null-replayability resolution collapses here (replayable -> request, not ->
browser_only); the pre-loop manner directives (`request_browser_first`,
`resolve_in_loop`) do not survive the turn."""


class GatewayVerdict(BaseModel):
    """The structured gateway verdict closing the authn loop (the actor's
    `response_format`, D223-15): the run's auth outcome, the selected account
    IDENTIFIER (never its material, D223-19), the release branch the pipeline
    obeys, and the run-scoped null-replayability resolution (logged loudly,
    never persisted - the overview is operator-owned, D223-11).

    `outcome` stays the D223-3 pair plus the first-class anonymous path: a
    failed authentication (`failed`, the exhausted sign-in space included)
    runs collection unauthenticated, loudly (D223-2); `anonymous` is the
    no-authenticated-surface finding, not a failure. No cross-field
    validation by design (fail-open): an `authenticated` verdict without an
    account runs the pipeline unauthenticated, loudly, rather than degrading
    the turn."""
    # the D223-2 fail-open default: a degraded turn parses to failed, never anonymous
    outcome: Literal["authenticated", "anonymous", "failed"] = "failed"
    account: str | None = Field(default=None)
    branch: VerdictBranch = "request"
    replayability_resolved: bool = Field(default=False)
    replayability: bool | None = Field(default=None)
    rationale: str = Field(default="")


# --- the branch pruning rule ----------------------------------------------------------

BROWSER_ONLY_KEEP = frozenset({"steel_crawl"})
"""The browser-only branch keeps exactly the Steel crawl path: every
request-based job is pruned (D223-11, implemented literally)."""


def prune_plan(plan: list[list[str]], branch: VerdictBranch) -> list[list[str]]:
    """Apply the verdict branch to a phase plan: browser-only keeps the Steel
    crawl jobs alone (phases left empty are dropped); the request branch keeps
    everything. Returns a NEW plan, never mutates."""
    if branch != "browser_only":
        return [list(phase) for phase in plan]
    return [[job for job in phase if job in BROWSER_ONLY_KEEP]
            for phase in plan if any(job in BROWSER_ONLY_KEEP for job in phase)]


__all__ = [
    "AuthnPhase",
    "PHASES",
    "AuthnTransition",
    "AuthnLoopState",
    "initial_state",
    "GROUNDED_HINT",
    "RETRIEVED_HINT",
    "VALIDATION_HINT",
    "GENERATION_HINT",
    "GENERATION_SIGNIN_HINT",
    "SELF_SERVICE_HINT",
    "DEBUG_HINT",
    "FINISH_HINT",
    "TRANSITION_HINTS",
    "PROBE_TOOLS",
    "wrap_hint",
    "detect_transition",
    "push_transition",
    "BranchDirective",
    "BRANCH_DIRECTIVES",
    "select_branch",
    "NO_AUTH_MARKER",
    "GatePath",
    "declares_auth_surface",
    "has_no_auth_marker",
    "classify_gate",
    "VerdictBranch",
    "GatewayVerdict",
    "BROWSER_ONLY_KEEP",
    "prune_plan",
]
