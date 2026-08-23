"""The hunting agent (#83): the test-DESIGN side of the Q8 partition.

The hunt-orchestrator (#82) feeds this module one declarative `HuntConfig` per
hunt (IA-2); the harness navigates the ratified decision-tree architecture
(implementation doc section 3) into goal-directed reasoning turns - ground and
query the symptom-technique KB, author the spec, dispatch the pod, derive the
four-valued hypothesis verdict, and judge the meaningful continuation - then
writes exactly the two record kinds Q6 declares (`spec` and `evidence`) into
the append-only hunt store.

The harness is the async-native client (feat/async-actor-agents):
`build_hunting_agent` returns an `async dispatch_fn`, and the production
`author`/`judge` seams are per-hunt `HuntingHunterActor` turns
(`HuntingActorRegistry`), so each hunt resumes ONE mailbox-actor thread. Every
injected collaborator is called through `_await_seam` - an async seam is
awaited, a sync seam is offloaded via `asyncio.to_thread` - so thin sync fakes
stay injectable and the caller's event loop never stalls.

Everything external is a typed seam, injected at construction:

  kb(query)     the symptom-technique KB (IA-8) on the (fault-class, axis) join key
  pod(spec)     the test-executor pod (IA-3/IA-4), returning {verdict, evidence}
  author(text)  the spec-authoring LLM turn (D4), returning the D4 dict or None
  judge(text)   the D5 continuation judgment, consulted ONLY on an
                insufficient-evidence derivation

Never raise out of `dispatch_fn`; every collaborator failure degrades
(fail-open) and is flagged in the feedback. The verdict derivation is the
harness's PURE, trail-driven responsibility (D67-02, Q3): `derive_verdict`
reads ONLY the pod's terminal reason plus the single `clean` flag (plus
`init_validation` for the INIT rejection case), never per-variant machine
outcomes, never the LLM.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal

from polymerhus.attack.hunting.hunt_orchestrator import (
    DispatchResult,
    HuntConfig,
)
from polymerhus.attack.hunting.hunting_tracing import (
    flush_hunting_traces,
    hunting_span,
    trace_span,
)

logger = logging.getLogger(__name__)

# The D7 hypothesis verdict (Q3-amended, implementation doc 2.3): four values,
# derived by the harness, never by the LLM.
HypothesisVerdict = Literal[
    "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
]

# Q5: exactly ONE re-authoring pass per hunt after an INIT rejection; a second
# rejection lands `underspecified-spec` with the validation evidence.
_MAX_RE_AUTHORING_PASSES = 1


@dataclass(frozen=True)
class SymptomTechniqueQuery:
    """The IA-8 join key (implementation doc 2.2): the symptom-technique KB is
    queried on the `(fault-class, unit technological-axis)` pair; the axis is
    derived deterministically from the unit's card, never a typed predicate
    facet (#66 non-conflation)."""

    fault_class: str
    axis: str


def derive_technological_axis(card: dict | None) -> str:
    """The deterministic technological axis of a unit's index card (IA-8/D10).

    Prefers the typed spine's `api_paradigm`, then its `navigation_model` -
    both describe the mechanism-System the unit rides on; falling back to the
    unit's kind (lowercased) keeps the axis deterministic and non-empty for a
    card whose spine carries neither (the contract asserts a non-empty axis,
    C1). A card with no axis signal reports "unknown". Pure and fail-open: a
    malformed card degrades to "unknown", never raises."""
    if not card:
        return "unknown"
    try:
        spine = card.get("spine") or {}
        for key in ("api_paradigm", "navigation_model"):
            value = spine.get(key)
            if value:
                return str(value).lower()
        kind = card.get("kind")
        return str(kind).lower() if kind else "unknown"
    except Exception:  # noqa: BLE001 - fail-open: an unreadable card is unknown
        return "unknown"


def derive_verdict(
    terminal_reason: str,
    *,
    clean: bool,
    init_validation: list[str] | None = None,
) -> HypothesisVerdict:
    """The D7 verdict derivation (D67-02, Q3-amended; implementation doc 2.3).

    A PURE, trail-driven function reading ONLY the pod's terminal reason plus
    the single `clean` flag (plus `init_validation` for the INIT-rejection
    case) - never per-variant machine outcomes, never the LLM. The ratified
    map:

      symptom-confirmed            -> successful
      space-exhausted              -> unsuccessful
      technical-infeasibility      -> unsuccessful (a structural blocker)
      specific-defence-prevention  -> unsuccessful
      no-symptom-evidence          -> unsuccessful when the trail is clean
                                      (a symptom-absent is established), else
                                      insufficient-evidence
      budget-timeout               -> unsuccessful when the trail is clean,
                                      else insufficient-evidence (the loop was
                                      cut mid-flight)
      technical-infeasibility carrying INIT validation evidence (the pod
                                      rejected the spec at INIT)
                                   -> underspecified-spec

    An out-of-enum terminal reason is uninterpretable, so the derivation is
    conservative - `insufficient-evidence`, never a success or a clean absence
    claim (fail-open).
    """
    init_validation = init_validation or []
    if terminal_reason == "technical-infeasibility" and init_validation:
        return "underspecified-spec"
    if terminal_reason == "symptom-confirmed":
        return "successful"
    if terminal_reason in (
        "space-exhausted", "technical-infeasibility", "specific-defence-prevention",
    ):
        return "unsuccessful"
    if terminal_reason in ("no-symptom-evidence", "budget-timeout"):
        return "unsuccessful" if clean else "insufficient-evidence"
    return "insufficient-evidence"


# The stable system prompt (implementation doc sections 4.1-4.6) is
# single-sourced from `skills/hunting/hunting-agent/SKILL.md` through the
# shared `skill_for` (FR-SKILLIF, section 4.10), degraded to the terse fallback
# below when the mount is unavailable. The per-invocation user prompts
# (sections 4.7-4.9) are composed by the harness from the HuntConfig parts, the
# KB retrieval, and the working set state; the harness embeds the stable
# system prompt ahead of EVERY composed turn (`_with_stable_skill`), so the
# ratified decision-tree verbatims reach each LLM seam (implementation doc
# 4.10; the triager/curation precedent of skill-as-system-prompt).
_HUNTING_AGENT_SKILL_FALLBACK = (
    "You are the hunting agent: the hypothesis formulation and verification "
    "agent of the hunting design/execution partition. For the dispatched "
    "HuntConfig, formulate candidate fault hypotheses for the testable unit, "
    "author a TestImplementationSpec for each candidate worth testing, and "
    "verify each hypothesis through the test-executor pod, ending with an "
    "evidence-backed verdict. You are a scientist, not a script writer: every "
    "spec is an experiment design, every claim must be backed by evidence you "
    "actually hold, and the pod is the only source of experimental evidence - "
    "you never declare success, the evidence does. A hypothesis is a candidate "
    "specific fault of the dispatched class; a variant is the pod's internal "
    "loop, you consume variants, you do not author them. One hypothesis per "
    "spec; no bulldozing - never re-dispatch a closed candidate without new "
    "evidence. Degraded grounding (empty or raising KB, missing config parts, "
    "raising pod) degrades the run, never raises; flag the gap in the feedback."
)


def _load_hunting_agent_skill() -> str:
    """The stable system prompt, single-sourced from
    `skills/hunting/hunting-agent/SKILL.md` through the shared `skill_for`
    (implementation doc 4.10): YAML frontmatter stripped, cached in-process,
    degraded to the terse fallback above when the mount is unavailable."""
    from polymerhus.recon.domain.skills import skill_for

    return skill_for("hunting/hunting-agent", fallback=_HUNTING_AGENT_SKILL_FALLBACK)


def _with_stable_skill(text: str) -> str:
    """The system-prompt embedding (implementation doc 4.10): the stable
    decision-tree verbatims ahead of the per-invocation turn text, so every
    LLM seam - authoring, re-authoring, continuation judgment - navigates the
    ratified architecture even when it only ever sees one string."""
    return f"{_load_hunting_agent_skill()}\n\n{text}"


# --- pure prompt/composition helpers -----------------------------------------

def _fmt_list(items) -> str:
    if not items:
        return "(none)"
    return "; ".join(str(i) for i in items)


def _evidence_notes(evidence: dict | None) -> list[str]:
    """The interpretation notes on the pod's D5 trail: the NL insight strings
    the evidence-backed feedback rides on (never empty for a closed hunt)."""
    notes: list[str] = []
    for interpretation in (evidence or {}).get("interpretations") or []:
        if isinstance(interpretation, dict) and interpretation.get("note"):
            notes.append(str(interpretation["note"]))
    return notes


def _verdict_line(derived: str, evidence: dict | None) -> str:
    parts: list[str] = []
    terminal = (evidence or {}).get("terminal_reason")
    if terminal:
        parts.append(f"hypothesis derived {derived} (pod terminal: {terminal})")
    else:
        parts.append(f"hypothesis derived {derived}")
    parts += _evidence_notes(evidence)
    return " together with ".join(p for p in parts if p)


def _canonical_hash(spec: dict) -> str:
    """The canonical spec fingerprint for Q5's experiment log (C9): equal D4
    dicts hash equal regardless of key order, so an identical spec is never
    dispatched twice."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _nonempty(parts: list[str]) -> list[str]:
    return [p for p in parts if p]


def _result(verdict: str, feedback: list[str], *, spec_ref=None, pod_result_ref=None,
            back_edge_needs=()):
    """The one DispatchResult assembly (IA-2/D11): the joined non-empty
    feedback and the optional delivered refs / inline back-edge needs."""
    return DispatchResult(
        spec_ref=spec_ref, pod_result_ref=pod_result_ref,
        hypothesis_verdict=verdict,
        feedback=" ".join(_nonempty(feedback)),
        back_edge_needs=list(back_edge_needs),
    )


def _append_spec(store_append, ws: dict, config: HuntConfig, spec: dict, *,
                 parent_spec_ref: str | None) -> str:
    """Commit one authored D4 (SPEC-WRITE, Q5/C9): the spec record with hunt
    identity and the D67-03/D67-08 parent lineage, plus its canonical-hash
    experiment-log entry. Returns the record ref."""
    spec_hash = _canonical_hash(spec)
    spec_ref = store_append("spec", {
        "hunt_id": config.hunt_id,
        "hypothesis_id": config.hunt_id,
        "unit_id": config.unit_id,
        "fault_class": config.fault_class,
        "parent_spec_ref": parent_spec_ref,
        "canonical_hash": spec_hash,
        **spec,
    })
    ws["log"][spec_hash] = {
        "hash": spec_hash, "spec": spec, "spec_ref": spec_ref,
        "pod_result_ref": None, "evidence": {},
    }
    return spec_ref


def _first_card(config: HuntConfig) -> dict | None:
    cards = (config.surface_context or {}).get("cards") or []
    return cards[0] if cards else None


def _config_gaps(config: HuntConfig) -> list[str]:
    """The O3 gap flags for a degraded HuntConfig: the agent still authors from
    the present parts (C4) and flags each missing part in the feedback."""
    gaps: list[str] = []
    if not (config.surface_context or {}).get("cards"):
        gaps.append("surface context missing (no adapted index cards); grounding degraded")
    if not config.prompt_template.rationale:
        gaps.append("orchestrator rationale missing; grounding degraded")
    if not config.target_caveats:
        gaps.append("target caveats missing; grounding degraded")
    return gaps


def compose_authoring_prompt(
    config: HuntConfig,
    kb_result: dict,
    axis: str,
    *,
    kb_degraded: bool,
    working_set: str,
) -> str:
    """The per-invocation authoring user prompt (verbatim 4.7): the HuntConfig's
    five-part parameter set, the KB retrieval, and the working-set state."""
    tpl = config.prompt_template
    surface = config.surface_context or {}
    cards = surface.get("cards") or []
    kb_text = (kb_result if not kb_degraded
               else "(KB unavailable; grounded on the HuntConfig alone)")
    return (
        f"You are dispatched to hunt {config.unit_id} for fault class "
        f"{config.fault_class}.\n\n"
        f"Vulnerability class: {config.vulnerability_class or '(none)'}\n"
        f"Orchestrator's fault-matching rationale: {tpl.rationale or '(none)'}\n"
        f"Research direction: {tpl.research_direction or '(none)'}\n"
        f"Adversarial capabilities: {_fmt_list(config.adversarial_capabilities)}\n"
        f"Environmental assumptions: {_fmt_list(config.assumptions)}\n"
        f"Technique primitives: {_fmt_list(config.technique_primitives)}\n"
        f"L0 fault-applicability evidence: {_fmt_list(tpl.l0_evidence)}\n\n"
        f"Adapted surface context (index card of {config.unit_id}): "
        f"{_fmt_list(cards) if cards else '(no adapted index cards)'}\n"
        f"Target caveats: {_fmt_list(config.target_caveats)}\n"
        f"Prior-hunt insights: {_fmt_list(config.prior_hunt_insights)}\n"
        f"Fault-targeting tool registry: {_fmt_list(config.tool_registry)}\n\n"
        f"Symptom-technique KB retrieval on ({config.fault_class}, {axis}): "
        f"{kb_text}\n\n"
        f"Your working set: {working_set}\n\n"
        "Navigate the decision tree from where the working set leaves you, "
        "honouring the decision points, and return the spec as JSON with the "
        "D4 typed base (target_identity, verification_symptoms, "
        "testing_pattern, assumptions, payload_vector_space) plus the NL core "
        "(rationale, interpretation_guidance)."
    )


def compose_reauthoring_prompt(config: HuntConfig, init_validation: list[str]) -> str:
    """The re-authoring user prompt (verbatim 4.8, exactly once per hunt): decline
    the attributes the validation evidence points at, keep everything that passed."""
    return (
        "The pod rejected the previous spec at INIT validation.\n\n"
        f"INIT validation evidence: {_fmt_list(init_validation)}\n\n"
        "Re-author the spec in a single pass. Decline exactly the attributes "
        "the validation evidence points at; keep everything that passed. If "
        "the validation evidence is not addressable by a decline, do not "
        "re-roll: land with the validation evidence (the verdict derives as "
        "underspecified-spec). Return the spec as JSON with the D4 typed base "
        "(target_identity, verification_symptoms, testing_pattern, "
        "assumptions, payload_vector_space) plus the NL core (rationale, "
        "interpretation_guidance)."
    )


def compose_judgment_prompt(
    config: HuntConfig, evidence: dict | None, routed: tuple = (),
) -> str:
    """The D5 continuation-judgment user prompt (verbatim 4.9): the pod outcome,
    the evidence trail, and any routed back-edge results."""
    routed_note = ", ".join(
        f"{r.status} (correlation_id={r.correlation_id})" for r in routed
    ) or "(none)"
    evidence = evidence or {}
    return (
        f"The pod returned for the dispatched spec (hunt {config.hunt_id}, "
        f"{config.unit_id}, {config.fault_class}):\n"
        f"verdict: {evidence.get('pod_verdict')}\n"
        f"terminal reason: {evidence.get('terminal_reason')}\n"
        f"interpretations: {_fmt_list(_evidence_notes(evidence))}\n\n"
        f"Routed back-edge results: {routed_note}\n\n"
        'Decide the next step as JSON: {"meaningful_insight": bool, '
        '"next_step": "end"|"back_edge", "rationale": str, '
        '"back_edge_requests": [AnalyserReconRequest]}. '
        "meaningful_insight is false when the evidence carries no new "
        "information about the hypothesis: an empty trail, a bare repeat of a "
        "prior infeasibility, or a result unrelated to the hypothesis - a "
        "no-meaningful-insight response closes the candidate. back_edge is "
        "rare, only for target-knowledge gaps the surface context and KB "
        "cannot answer; the returned result re-enters the same candidate."
    )


# --- the harness --------------------------------------------------------------

def build_hunting_agent(*, store, run_id, kb, pod, author, judge, axis=None):
    """Build the hunting-agent dispatch seam (IA-2).

    `store`, `run_id`, `kb`, `pod`, `author`, `judge` follow the integration
    contract (tests/integration/test_hunting_agent_contracts.py); `axis`
    overrides the deterministic technological-axis derivation for the KB join
    key. Returns `async dispatch_fn(config: HuntConfig, routed=()) -> DispatchResult`
    (the async-native harness; callers with a running loop `await` it, sync
    callers use `asyncio.run`/`run_coro_blocking`). Every collaborator is
    awaited when async and offloaded via `asyncio.to_thread` when sync.
    The closure holds the per-hunt working set (Q5's in-memory experiment log),
    so a re-entry after a routed back-edge resumes the SAME candidate instead
    of re-dispatching it (D67-14, C9)."""
    import asyncio
    import inspect

    # hunt_id -> working set: {"kb_grounded": bool,
    #                          "log": {canonical_hash: {"hash", "spec", "spec_ref",
    #                                    "pod_result_ref", "evidence"}}}
    working_sets: dict[str, dict[str, Any]] = {}

    async def _await_seam(fn, *args):
        """Await an async seam, else offload a sync one to a worker thread."""
        if inspect.iscoroutinefunction(fn):
            return await fn(*args)
        return await asyncio.to_thread(fn, *args)

    def _append(kind: str, record: dict) -> str | None:
        """Fail-open store write (O3): a failure warns and the agent keeps
        serving with a None ref; it never raises out of the dispatch."""
        try:
            return store.append(run_id, kind, record)
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            logger.warning("hunt store (%s): %s record write failed (%s)",
                           run_id, kind, exc)
            return None

    async def dispatch_fn(config: HuntConfig, routed: tuple = ()) -> DispatchResult:
        hunt_id = config.hunt_id
        ws = working_sets.setdefault(hunt_id, {"kb_grounded": False, "log": {}})
        # #94: bind the per-hunt session so a SYNC-lane author/judge (the legacy
        # `invoke_role` rollback factories) runs STATEFUL on ONE thread per hunt.
        # The actor-backed production seams ignore it - the per-hunt
        # `HuntingHunterActor` already owns that thread. Import lazily so this
        # module stays driver-free at import.
        from polymerhus.attack.hunting.llm import hunt_session
        try:
            with hunting_span(run_id, hunt_id), hunt_session(run_id, hunt_id):
                return await _dispatch(config, tuple(routed), ws)
        except Exception as exc:  # noqa: BLE001 - never raise out of dispatch_fn
            logger.warning("hunt %s degraded (%s)", hunt_id, exc, exc_info=True)
            return _result("unsuccessful",
                           [f"hunt {hunt_id} degraded: {exc}"])
        finally:
            flush_hunting_traces()

    async def _dispatch(config: HuntConfig, routed: tuple, ws: dict) -> DispatchResult:
        hunt_id = config.hunt_id
        feedback: list[str] = list(_config_gaps(config))

        # GROUND / QUERY (D1, IA-8): one KB call per hunt on the join key; an
        # empty or raising KB degrades to HuntConfig-only grounding (C2/C3).
        kb_result: dict = {}
        kb_degraded = False
        axis_value = axis or derive_technological_axis(_first_card(config))
        if not ws["kb_grounded"]:
            query = SymptomTechniqueQuery(fault_class=config.fault_class, axis=axis_value)
            try:
                trace_span("kb-retrieval", input={
                    "fault_class": config.fault_class,
                    "axis": axis_value,
                })
                kb_result = await _await_seam(kb, query) or {}
            except Exception as exc:  # noqa: BLE001 - C2/C3: degrade, never raise
                kb_degraded = True
                logger.warning("symptom-technique KB degraded for %s (%s)",
                               config.fault_class, exc)
                feedback.append("symptom-technique KB unavailable; "
                                "grounded on the HuntConfig alone")
            ws["kb_grounded"] = True

        # Re-entry after a routed back-edge (D67-14): the candidate is
        # dispatched; the verdict may revise with each returned result.
        if routed:
            return await _reenter(config, routed, ws, feedback)

        if not ws["log"]:
            # SPEC-WRITE for the committed candidate slot (one per hunt in this
            # build; a future phase may fan a hunt out into several hypotheses).
            try:
                turn = _with_stable_skill(compose_authoring_prompt(
                    config, kb_result, axis_value,
                    kb_degraded=kb_degraded,
                    working_set="fresh hunt: no prior dispatch; begin at GROUND",
                ))
                trace_span("spec-composition", input={"prompt": turn})
                spec = await _await_seam(author, turn)
            except Exception as exc:  # noqa: BLE001 - fail-open
                logger.warning("hunt %s spec authoring degraded (%s)", hunt_id, exc)
                feedback.append(f"spec authoring unavailable ({exc})")
                return _result("unsuccessful", feedback)
            if not isinstance(spec, dict) or not spec:
                feedback.append("the authoring turn returned no spec; "
                                "the hypothesis is not testable")
                return _result("unsuccessful", feedback)
            spec_ref = _append_spec(_append, ws, config, spec, parent_spec_ref=None)

        return await _pod_loop(config, ws, feedback)

    async def _pod_loop(config: HuntConfig, ws: dict, feedback: list[str]) -> DispatchResult:
        """Dispatch the committed spec to the pod (IA-3/IA-4) and evaluate the
        outcome: the INIT-rejection re-authoring pass (exactly once, Q5), the
        pure verdict derivation, and the D5 continuation judgment."""
        hunt_id = config.hunt_id
        re_authored = 0
        entry = next(iter(ws["log"].values()))
        spec, spec_ref = entry["spec"], entry["spec_ref"]

        while True:
            try:
                outcome = await _await_seam(pod, spec)
            except Exception as exc:  # noqa: BLE001 - O5/C11: degrade, never raise
                message = f"pod turn exhausted: {exc}"
                feedback.append(message)
                _append("evidence", {
                    "hunt_id": hunt_id,
                    "hypothesis_id": hunt_id,
                    "spec_ref": spec_ref,
                    "error": message,
                    "derived_verdict": "unsuccessful",
                })
                return _result("unsuccessful", feedback, spec_ref=spec_ref)

            outcome = outcome if isinstance(outcome, dict) else {}
            envelope = outcome.get("evidence") or {}
            terminal = envelope.get("terminal_reason")
            init_validation = envelope.get("init_validation") or []
            if init_validation and not isinstance(init_validation, list):
                init_validation = [str(init_validation)]
            derived = derive_verdict(
                terminal or "",
                clean=bool(envelope.get("clean", False)),
                init_validation=init_validation or None,
            )
            snapshot = {
                "pod_verdict": outcome.get("verdict"),
                "terminal_reason": terminal,
                "iterations": envelope.get("iterations"),
                "clean": bool(envelope.get("clean", False)),
                "interpretations": envelope.get("interpretations", []),
                "init_validation": init_validation or None,
            }
            entry["pod_result_ref"] = _append("evidence", {
                "hunt_id": hunt_id,
                "hypothesis_id": hunt_id,
                "spec_ref": spec_ref,
                "derived_verdict": derived,
                **snapshot,
            })
            entry["evidence"] = snapshot

            if terminal == "technical-infeasibility" and init_validation:
                # INIT rejection (Q3/Q5): exactly ONE re-authoring pass; a second
                # rejection lands underspecified-spec with the validation evidence.
                if re_authored >= _MAX_RE_AUTHORING_PASSES:
                    feedback.append("the re-authored spec was rejected again at "
                                    "INIT; landing underspecified-spec")
                    return _result(derived, feedback, spec_ref=spec_ref,
                                   pod_result_ref=entry["pod_result_ref"])
                try:
                    turn = _with_stable_skill(
                        compose_reauthoring_prompt(config, init_validation))
                    trace_span("spec-composition", input={"prompt": turn})
                    re_spec = await _await_seam(author, turn)
                except Exception as exc:  # noqa: BLE001 - fail-open
                    re_spec = None
                    feedback.append(f"re-authoring unavailable ({exc})")
                if not isinstance(re_spec, dict) or not re_spec:
                    feedback.append("re-authoring evidence unaddressable; "
                                    "landing underspecified-spec")
                    return _result(derived, feedback, spec_ref=spec_ref,
                                   pod_result_ref=entry["pod_result_ref"])
                re_ref = _append_spec(_append, ws, config, re_spec,
                                      parent_spec_ref=spec_ref)  # D67-08 lineage
                re_hash = _canonical_hash(re_spec)
                re_authored += 1
                entry = ws["log"][re_hash]
                spec, spec_ref = re_spec, re_ref
                continue

            feedback.append(_verdict_line(derived, snapshot))
            if derived == "insufficient-evidence":
                # D67-14: the meaningfulness guard is LLM-judged and consulted
                # only here; it may surface an inline need or end the evaluation.
                return await _judge_and_finish(config, spec_ref, entry["pod_result_ref"],
                                               snapshot, (), feedback)
            return _result(derived, feedback, spec_ref=spec_ref,
                           pod_result_ref=entry["pod_result_ref"])

    async def _reenter(config: HuntConfig, routed: tuple, ws: dict,
                 feedback: list[str]) -> DispatchResult:
        """Re-enter the evaluation for the SAME dispatched candidate (D67-14):
        the routed back-edge result may revise the verdict with each returned
        result. The experiment log short-circuits any re-dispatch of an
        identical spec (Q5/C9): the committed refs stand, the judge consumes the
        routed evidence, never a second pod run."""
        if not ws["log"]:
            feedback.append("no committed experiment to re-evaluate; hunt degraded")
            return _result("unsuccessful", feedback)
        # The CURRENTLY committed spec is the LAST log entry: a re-authoring
        # pass inserts the derived variant and the pod loop continues on it
        # (Q5), so a routed re-entry must judge against THAT spec's evidence,
        # never the superseded original (D67-08 lineage).
        entry = list(ws["log"].values())[-1]
        snapshot = entry.get("evidence") or {}
        feedback.append("re-entered the evaluation with the routed back-edge result")
        feedback.extend(_evidence_notes(snapshot))
        return await _judge_and_finish(config, entry.get("spec_ref"),
                                       entry.get("pod_result_ref"), snapshot,
                                       routed, feedback)

    async def _judge_and_finish(config: HuntConfig, spec_ref, pod_result_ref,
                          snapshot: dict, routed: tuple,
                          feedback: list[str]) -> DispatchResult:
        """The shared D5 continuation judgment: consult the guard (fail-open),
        surface the inline needs, or close the candidate - a no-meaningful-
        insight response that ends the evaluation degrades an
        insufficient-evidence verdict to unsuccessful (D67-12, C10/C9)."""
        derived = derive_verdict(
            (snapshot or {}).get("terminal_reason", ""),
            clean=bool((snapshot or {}).get("clean", False)),
            init_validation=(snapshot or {}).get("init_validation"),
        )
        try:
            judgment = await _await_seam(judge, _with_stable_skill(
                compose_judgment_prompt(config, snapshot, routed))) or {}
        except Exception as exc:  # noqa: BLE001 - fail-open
            judgment = {}
            feedback.append(f"continuation judgment unavailable ({exc})")
        if not isinstance(judgment, dict):
            judgment = {}
        if judgment.get("next_step") == "back_edge" and judgment.get("back_edge_requests"):
            needs = list(judgment["back_edge_requests"])
            feedback.append(judgment.get("rationale") or
                            "back-edge surfaced for the residual gap")
            return _result(derived, feedback, spec_ref=spec_ref,
                           pod_result_ref=pod_result_ref, back_edge_needs=needs)
        if not judgment.get("meaningful_insight", False):
            derived = "unsuccessful"  # D67-12: the guard ended the evaluation
        feedback.append(judgment.get("rationale") or _verdict_line(derived, snapshot))
        return _result(derived, feedback, spec_ref=spec_ref,
                       pod_result_ref=pod_result_ref)

    return dispatch_fn


def build_sync_hunting_agent(*, store, run_id, kb, pod, author, judge, axis=None):
    """The SYNC lane of the hunting-agent harness: a thin wrapper that runs the
    async `build_hunting_agent` dispatch to completion, so the harness canon is
    never re-implemented (the mirror of `hunt_orchestrator.run_orchestration`).

    Sync injectable seams (the legacy `invoke_role` factories, test fakes)
    travel through `asyncio.to_thread` inside the canon; async seams (the
    actor-backed defaults) are awaited natively. When called from a running
    event loop, `run_coro_blocking` runs the dispatch on a separate thread so
    `asyncio.run` is never re-entered on the caller's loop."""
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    dispatch_fn = build_hunting_agent(
        store=store, run_id=run_id, kb=kb, pod=pod,
        author=author, judge=judge, axis=axis,
    )

    def dispatch(config: HuntConfig, routed: tuple = ()) -> DispatchResult:
        return run_coro_blocking(dispatch_fn(config, tuple(routed)))

    return dispatch