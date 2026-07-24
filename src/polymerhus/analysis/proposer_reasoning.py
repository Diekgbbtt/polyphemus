"""Reusable proposer-reasoning pattern (#26 Q1): composable prompt fragments + a
two-call reason->extract runner that any analyser proposer adopts.

The Bootstrapper is the first adopter; the Assigner / DataPlane / TechnicalSystem
reuse these fragments with their own content. The pattern applies the ratified
prompt-engineering primitives - system-prompt role design, an explicit
chain-of-thought scaffold, few-shot CoT exemplars (show-don't-tell), and a
structured-extraction second call - deliberately WITHOUT hardcoded domain examples
(the example-pollution pitfall the old bootstrap prompt fell into).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def role_header(role: str, goal: str) -> str:
    """The system-prompt role/goal fragment (prompt-engineering: establish role +
    expertise + the success criterion up front)."""
    return f"ROLE: {role}\nGOAL: {goal}"


def cot_scaffold(steps: list[str]) -> str:
    """The chain-of-thought reasoning scaffold: an explicit, numbered process the
    model works THROUGH out loud (the free-text reasoning call)."""
    lines = ["Reason step by step, out loud, in this exact order:"]
    lines += [f"{i}. {step}" for i, step in enumerate(steps, 1)]
    return "\n".join(lines)


def few_shot_block(exemplars: list[str]) -> str:
    """The few-shot CoT block. The exemplars teach the REASONING SHAPE; they are
    chosen from divergent domains so no single domain anchors the projection
    (show-don't-tell without example pollution)."""
    parts = ["WORKED EXAMPLES - imitate the REASONING SHAPE, never the domain:"]
    parts += [f"--- Example {i} ---\n{ex}" for i, ex in enumerate(exemplars, 1)]
    return "\n\n".join(parts)


def bounded_retry(fn, *, attempts: int = 3):
    """Call `fn` up to `attempts` times until it returns a non-None result; return
    that result, or None if every attempt yielded None or raised (exhausted).

    The LLM client handles service-level failures (credits / rate-limit) upstream
    (#26 Q6), so this retry targets the low-probability transient empty/malformed
    generation. Its exhaustion (a None return) is the caller's FAIL-CLOSED block
    signal - the two-call proposer must not proceed on an unmet generation."""
    for _ in range(attempts):
        try:
            result = fn()
        except Exception:  # a raised attempt counts as a failed one; retry then block
            logger.warning("bounded_retry: attempt raised; retrying", exc_info=True)
            continue
        if result is not None:
            return result
    return None
