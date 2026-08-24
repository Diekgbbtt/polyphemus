"""The in-memory context-management component (operator, 2026-08-06).

The pod's "memory" (D67-01): it holds the experiment log (the D6 trail), tracks
the dedup signatures, and builds the FILTERED context each agent's session
sees - only the relevant slice (prior variants, filtered tool outputs), never
the whole raw log. This is what makes the two agents
semi-stateful: the Triager has direct observability of every prior variant, so
it does not elicit a duplicate (the dedup solution), and the Runner sees the
filtered log so it does not re-issue an identical chain.

`ExperimentLog.executed` doubles as the exhaustion signal: an all-duplicate
draw (every candidate probe already executed) is `space-exhausted`, so dedup
and termination are one mechanism (no spin).

This module is pure and DB/LLM-free (unit-tier safe).
"""
from __future__ import annotations

import hashlib
import json

from polymerhus.attack.hunting.pod.types import (
    Interpretation,
    KbObservation,
    RawObservation,
    VariantSpec,
)

# Max chars of a raw tool body surfaced into a session turn (per-turn filtering).
_BODY_SLICE = 1200


def canonical_spec_hash(spec: dict) -> str:
    """The canonical spec fingerprint (D84-2, relocated from the parent
    `hunting_agent._canonical_hash`): equal D4 dicts hash equal regardless of
    key order, so an identical spec is never dispatched twice (C9) and the pod's
    per-spec session discriminator stays byte-identical to the parent's
    experiment-log key."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _message_id(role: str, content: str) -> str:
    """The deterministic channel-message id (D84-4): identical (role, content)
    stamps identically, so the graph channel's `add_messages` reducer merges
    duplicate-content messages (dedup-under-same-id) while changed content gets
    a fresh id and appends."""
    return hashlib.sha256(f"{role}\x00{content}".encode("utf-8")).hexdigest()


def _dicts_to_lc(messages: list[dict]):
    """Dict views -> id-bearing BaseMessages (D84-4): every message is stamped
    with the deterministic (role, content) id - or carries an explicit dict
    "id" when present - so the channel's `add_messages` can dedup/merge instead
    of stacking duplicates."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    out = []
    for m in messages:
        role = m.get("role") or "human"
        content = m.get("content", "")
        msg_id = m.get("id") or _message_id(role, content)
        if role == "system":
            out.append(SystemMessage(content=content, id=msg_id))
        elif role == "ai":
            out.append(AIMessage(content=content, id=msg_id))
        else:  # human, tool
            out.append(HumanMessage(content=content, id=msg_id))
    return out


def _lc_to_dicts(messages) -> list[dict]:
    """BaseMessages -> the seam-facing curated views: `{role, content}` plus the
    channel id (stamped when the message carries none), so a view re-converted
    by `_dicts_to_lc` keeps its identity under `add_messages`."""
    role_of = {"system": "system", "ai": "ai", "human": "human"}
    out = []
    for m in messages:
        role = role_of.get(getattr(m, "type", "human"), "human")
        content = m.content
        out.append({"role": role, "content": content,
                    "id": getattr(m, "id", None) or _message_id(role, content)})
    return out


class ExperimentLog:
    """The D6 experiment log plus the dedup ledger (T2: the deterministic
    write surface AND the symbolic-layer capture middleware).

    The in-memory log stays the model-visible deterministic write surface
    (spec Further Notes): its recording methods are the ONLY place the D6 trail
    and the `executed` ledger mutate. Each recording method is ALSO the capture
    seam (operator, 2026-08-24): when a `PodMemoryStore` sink is bound it
    re-persists the affected variant's experiment-log slice to
    `experiment-log/<order>.yaml` (idempotent overwrite) and the minted variant
    to `variants/<ref>.yaml`. No LLM-facing tool writes the log; the model's
    judgment enters only as CONTENT through these mechanical stages.

    The order of a record is derived from its own variant ref (`vN` -> order N);
    the `executed` ledger is persisted in FULL (the operator's ruling: signatures
    are opaque, so the full accumulated ledger rides every slice write and
    overwrite-on-re-run makes it the current truth)."""

    def __init__(self, *, store=None, spec_id: str | None = None) -> None:
        self.store = store           # the PodMemoryStore capture sink (may be None)
        self.spec_id = spec_id
        self.variant_specs: list[VariantSpec] = []
        self.raw_observations: list[RawObservation] = []
        self.kb_observations: list[KbObservation] = []
        self.interpretations: list[Interpretation] = []
        self.executed: list[str] = []  # probe signatures (O7/C10)

    # --- the capture sink -------------------------------------------------------
    def _order_of(self, ref: str | None) -> int:
        from polymerhus.attack.hunting.pod.pod_memory import order_of
        return order_of(ref)

    def start_run(self) -> None:
        """A fresh run starts with a CLEAN slice for order 0 (D84-37: a re-run
        rewrites the file - the persisted log is the current truth). Without
        this, a prior run's `experiment_summary` terminal record would survive
        into the new run's file until the new P3 write replaces it. Fail-open:
        no store/no slice -> no-op."""
        if self.store is None or not self.spec_id:
            return
        try:
            current = self.store.read_experiment_log(self.spec_id, 0)
            if isinstance(current, dict) and current.get("experiment_summary"):
                current.pop("experiment_summary")
                self.store.write_experiment_log(self.spec_id, 0, current)
        except Exception:  # noqa: BLE001 - fail-open (O3)
            pass

    def _persist(self, order: int) -> None:
        """The capture seam: re-write the variant's experiment-log slice
        idempotently. No-op when no store/spec_id is bound (fail-open - the
        contract tier never persists). The slice is rebuilt from the in-memory
        log but PRESERVES the `experiment_summary` terminal record already on
        file (D84-35): the triager's interpretation write lands AFTER the
        runner's P3 note write, so a blind rebuild would clobber the summary."""
        if self.store is None or not self.spec_id:
            return
        try:
            from polymerhus.attack.hunting.pod.pod_memory import variant_ref
            current = self.store.read_experiment_log(self.spec_id, order)
            slice = {
                "order": int(order),
                "variant_ref": variant_ref(order),
                "raw_observations": [
                    o.model_dump() for o in self.raw_observations
                    if self._order_of(o.variant_ref) == order],
                "kb_observations": [
                    k.model_dump() for k in self.kb_observations
                    if self._order_of(k.variant_ref) == order],
                "interpretations": [
                    i.model_dump() for i in self.interpretations
                    if self._order_of(i.variant) == order],
                "executed": list(self.executed),
            }
            if isinstance(current, dict) and current.get("experiment_summary"):
                slice["experiment_summary"] = current["experiment_summary"]
            self.store.write_experiment_log(self.spec_id, order, slice)
        except Exception:  # noqa: BLE001 - fail-open (O3: the caller warns/keeps serving)
            pass

    # --- recording -------------------------------------------------------------
    def record_variant(self, variant: VariantSpec) -> None:
        if variant.ref not in {v.ref for v in self.variant_specs}:
            self.variant_specs.append(variant)
            if self.store is not None and self.spec_id:
                try:
                    self.store.write_variant(self.spec_id, variant.ref,
                                             variant.model_dump())
                except Exception:  # noqa: BLE001 - fail-open (O3)
                    pass

    def record_observation(self, obs: RawObservation) -> None:
        self.raw_observations.append(obs)
        self._persist(self._order_of(obs.variant_ref))

    def record_kb_observation(self, obs: KbObservation) -> None:
        """The KB-retrieve recording stage (T3/#179): a KB response enters the
        D6 trail + the variant's experiment-log file as a first-class
        `KbObservation`, through the SAME capture seam as every other
        deterministic mutation (the store persists the slice idempotently)."""
        self.kb_observations.append(obs)
        self._persist(self._order_of(obs.variant_ref))

    def record_interpretation(self, interp: Interpretation) -> None:
        self.interpretations.append(interp)
        self._persist(self._order_of(interp.variant))

    # --- dedup / exhaustion ----------------------------------------------------
    def has_executed(self, signature: str) -> bool:
        return signature in self.executed

    def mark_executed(self, signature: str) -> None:
        if signature not in self.executed:
            self.executed.append(signature)
            # The full `executed` ledger is persisted by the record_observation
            # that always follows (ExecTool._record / tool_exec) - the opaque
            # signatures cannot be split per variant, so every slice write
            # carries the full accumulated list (operator ruling).

    # --- filtered context for the agent sessions -------------------------------
    def variant_refs(self) -> list[str]:
        """Every variant already tried - handed to the Triager so it never mines
        a duplicate (the non-duplication verbatim rides on this)."""
        return [v.ref for v in self.variant_specs]

    def runner_context(self, spec: dict, feedback: str, iteration: int,
                       budget: int) -> str:
        """The filtered slice the Runner's session sees each lap: the current
        spec variant, the tried-probe signatures (so it does not duplicate),
        the Triager's feedback, and the budget state."""
        parts = [
            f"# Lap {iteration} of at most {budget}",
            f"## Current spec variant\n{json.dumps(spec, indent=2)}",
        ]
        if self.executed:
            parts.append("## Probe signatures already executed (do not repeat)\n"
                         + "\n".join(f"- {s}" for s in self.executed))
        if feedback:
            parts.append(f"## Triager feedback (declination to honour)\n{feedback}")
        return "\n\n".join(parts)

    def triager_context(self, spec: dict,
                        observation: RawObservation | None) -> str:
        """The filtered slice the Triager's session sees each lap: the current
        variant, the latest raw observation (body-capped), and every prior
        variant (so it does not re-mine one)."""
        parts = [f"## Current spec variant\n{json.dumps(spec, indent=2)}"]
        if observation is not None:
            obs = observation.model_dump()
            obs["body"] = (obs.get("body") or "")[:_BODY_SLICE]
            parts.append(f"## Latest observation\n{json.dumps(obs, indent=2)}")
        if self.variant_refs():
            parts.append("## Variants already tried (never mine a duplicate)\n"
                         + "\n".join(f"- {r}" for r in self.variant_refs()))
        if self.interpretations:
            recent = self.interpretations[-5:]
            parts.append("## Recent interpretations\n"
                         + "\n".join(f"- [{i.classification}] {i.note}" for i in recent))
        return "\n\n".join(parts)


def compose_runner_delta(log: ExperimentLog, spec: dict, feedback: str,
                         iteration: int, budget: int, *, store, spec_id: str) -> str:
    """The Runner's lap-opener HumanMessage delta (D84-9/10/11/27): the filtered
    `runner_context` slice PLUS the per-turn indexable pod-memory key-list +
    reading guidance. `store` may be None (fail-open: the guidance renders with
    an empty index)."""
    from polymerhus.attack.hunting.pod.pod_memory import compose_memory_guidance

    base = log.runner_context(spec, feedback, iteration, budget)
    return f"{base}\n\n{compose_memory_guidance(store, spec_id)}"


def compose_triager_delta(log: ExperimentLog, spec: dict,
                          observation: RawObservation | None, *, store,
                          spec_id: str, order: int) -> str:
    """The Triager's delta (D84-23): the VERBATIM P3 consolidation note (read
    from the pod-owned store) + the filtered `triager_context` + the per-turn
    memory key-list/guidance. No structured `RunnerStep` crosses the seam; a
    missing note degrades to the raw context (fail-open)."""
    from polymerhus.attack.hunting.pod.pod_memory import (
        compose_memory_guidance,
        read_variant_summary,
    )

    note_body = read_variant_summary(store, spec_id, order)
    note_part = (f"## Runner's consolidation note (verbatim)\n{note_body}" if note_body
                 else "## Runner's consolidation note (verbatim)\n"
                       "(no consolidation note for this stretch yet)")
    return (f"{note_part}\n\n{log.triager_context(spec, observation)}\n\n"
            f"{compose_memory_guidance(store, spec_id)}")
