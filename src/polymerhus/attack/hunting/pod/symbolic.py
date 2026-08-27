"""The helper symbolic layer (spec 1.1, 2 helper symbolic layer).

Minimal deterministic testing-verification helpers the scaffold's later builds
extend: probe/payload construction from the typed `payload_vector_space`,
and a minimal SYMBOLIC symptom recogniser.

Symbolic symptom verification is the good development direction but complex
(operator, 2026-08-06): this recogniser covers the mechanically-checkable
predicate families (an HTTP status band, a non-empty/empty body, a body marker)
and returns `None` when the symptom is not symbolically decidable - the LLM
Triager then judges it. The E1 walkthrough symptom ("HTTP 200 with a non-empty
body") is symbolically decidable, so the trivial real run needs no live LLM.

This module is pure and DB/LLM-free (unit-tier safe).
"""
from __future__ import annotations

import hashlib
import json
import re

from polymerhus.attack.hunting.pod.types import (
    INFEASIBILITY_SIGNAL_CLASS,
    ProbeChain,
    ProbeStep,
    RawObservation,
    SYMPTOM_ABSENT_CLASS,
    SYMPTOM_CONFIRMED_CLASS,
)


def probe_signature(chain: ProbeChain) -> str:
    """The dedup key (O7/C10): a stable hash over `(variant_ref, the core call)`.
    Two probe chains with the same variant and the same core payload dedup to
    one execution - and, fed into the exhaustion check, an all-duplicate draw
    advances the loop to `space-exhausted` rather than spinning."""
    core = next((s for s in chain.steps if s.role == "core"), None)
    payload = core.model_dump() if core is not None else {}
    blob = json.dumps([chain.variant_ref, payload], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def default_probe_from_spec(spec: dict, variant_ref: str) -> ProbeChain | None:
    """Build the pattern's default probe from the typed `payload_vector_space`
    (O12/C11): an EMPTY vector still yields one default probe (a GET of the
    target's path), so an empty payload vector never zeroes the loop. For a
    NON-EMPTY vector there is NO defaulting for any attribute (contract #191):
    the authored `method` and `path` are read verbatim, and a vector missing
    either yields None (no probe derivable - the loop lands space-exhausted).
    Returns None only when no probe is derivable at all (no path anywhere)."""
    pvs = spec.get("payload_vector_space") or {}
    if isinstance(pvs, dict) and pvs:
        method = str(pvs.get("method") or "").upper()
        path = str(pvs.get("path") or "")
        if not method or not path:
            return None
    else:
        method = "GET"
        path = _path_from_identity(spec.get("target_identity", ""))
    if not path:
        return None
    step = ProbeStep(role="core", method=method, url=str(path), body=str(pvs.get("body", "")))
    chain = ProbeChain(variant_ref=variant_ref, steps=[step])
    chain.signature = probe_signature(chain)
    return chain


def _path_from_identity(identity: str) -> str:
    """Best-effort path from a target identity like `service:web:soupmarket` or
    a full URL. Falls back to `/` so a bare service identity still probes root."""
    if not identity:
        return ""
    if identity.startswith("http://") or identity.startswith("https://"):
        return identity
    # A kind-qualified identity (service:web:...) carries no path -> probe root.
    return "/"


# --- Minimal symbolic symptom recogniser ---------------------------------------

_STATUS_RE = re.compile(r"\b(?:http|status(?:\s+code)?)\s*[:=]?\s*(\d{3})\b", re.I)
_NONEMPTY_RE = re.compile(r"non[-\s]?empty\s+body", re.I)
_EMPTY_RE = re.compile(r"\bempty\s+body\b", re.I)


def evaluate_symptom(verification_symptoms: list[str],
                     observation: RawObservation) -> str | None:
    """Symbolically classify an observation against the verification symptom(s).

    Returns one of the observation classes when the symptom is mechanically
    decidable, or `None` when it is not (the LLM Triager then judges). Also
    surfaces `infeasibility-signal` for a structurally impossible observation
    (no response captured) so the loop can route to technical-infeasibility."""
    # A structurally missing response is an infeasibility signal, not an absence.
    if observation.status is None and not observation.body and observation.returncode not in (0, None):
        return INFEASIBILITY_SIGNAL_CLASS

    decided = False
    holds = True
    for symptom in verification_symptoms:
        text = str(symptom)
        m = _STATUS_RE.search(text)
        if m is not None:
            decided = True
            holds = holds and (observation.status == int(m.group(1)))
        if _NONEMPTY_RE.search(text):
            decided = True
            holds = holds and bool((observation.body or "").strip())
        elif _EMPTY_RE.search(text):
            decided = True
            holds = holds and not (observation.body or "").strip()

    if not decided:
        return None  # not symbolically decidable -> defer to the LLM Triager
    return SYMPTOM_CONFIRMED_CLASS if holds else SYMPTOM_ABSENT_CLASS
