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


def curate_messages(messages: list[dict], max_tokens: int | None = None) -> list[dict]:
    """Compact a bounded VIEW of an agent's canonical session for one model call
    (the LangGraph pre_model_hook / `llm_input_messages` pattern): the full
    session stays on the graph state, this returns what the model SEES.

    Two-stage, token-aware compaction (the context-window handling):
      1. per-turn filtering - each raw tool-output body is truncated to a slice
         so one huge response cannot dominate the window;
      2. window compaction - `trim_messages` keeps the system prompt plus the
         most recent turns that fit `max_tokens` (counted with
         `count_tokens_approximately`), dropping the OLDEST turns - reasoning AND
         tool turns alike, so the session can never grow unbounded across laps.
    A compaction marker records how many earlier turns were elided; the FULL raw
    trail is always preserved in the experiment log (D6) for export - compaction
    only bounds what the agent sees, never what the pod reports."""
    from langchain_core.messages import trim_messages
    from langchain_core.messages.utils import count_tokens_approximately

    from polymerhus.attack.hunting.pod.config import HUNT_POD_SESSION_TOKENS

    budget = max_tokens if max_tokens is not None else HUNT_POD_SESSION_TOKENS

    filtered: list[dict] = []
    for m in messages:
        content = m.get("content", "")
        if m.get("role") == "tool" and len(content) > _BODY_SLICE:
            content = content[:_BODY_SLICE] + f"\n...[{len(content) - _BODY_SLICE} chars elided]"
        view = {"role": m.get("role", "human"), "content": content}
        mid = m.get("id")
        if mid:
            view["id"] = mid  # the view keeps pointing at its source channel message
        filtered.append(view)

    lc = _dicts_to_lc(filtered)
    trimmed = trim_messages(
        lc, max_tokens=budget, token_counter=count_tokens_approximately,
        strategy="last", include_system=True, start_on="human", allow_partial=False)
    out = _lc_to_dicts(trimmed)

    dropped = len(filtered) - len(out)
    if dropped > 0:
        marker = {"role": "human",
                  "content": f"[context compacted: {dropped} earlier turn(s) elided to fit "
                             f"the window; the full experiment log is preserved for export]"}
        if out and out[0]["role"] == "system":
            out = [out[0], marker] + out[1:]
        else:
            out = [marker] + out
    return out


class ExperimentLog:
    """The D6 experiment log plus the dedup ledger. Append-only in spirit; the
    terminal node renders its lists into the `PodExport`."""

    def __init__(self) -> None:
        self.variant_specs: list[VariantSpec] = []
        self.raw_observations: list[RawObservation] = []
        self.interpretations: list[Interpretation] = []
        self.executed: list[str] = []  # probe signatures (O7/C10)

    # --- recording -------------------------------------------------------------
    def record_variant(self, variant: VariantSpec) -> None:
        if variant.ref not in {v.ref for v in self.variant_specs}:
            self.variant_specs.append(variant)

    def record_observation(self, obs: RawObservation) -> None:
        self.raw_observations.append(obs)

    def record_interpretation(self, interp: Interpretation) -> None:
        self.interpretations.append(interp)

    # --- dedup / exhaustion ----------------------------------------------------
    def has_executed(self, signature: str) -> bool:
        return signature in self.executed

    def mark_executed(self, signature: str) -> None:
        if signature not in self.executed:
            self.executed.append(signature)

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
