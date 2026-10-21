"""The helper symbolic layer (spec 1.1, 2 helper symbolic layer).

Minimal deterministic testing-verification helpers the scaffold's later builds
extend: the LLM-free approximation of the runner's probe authoring over the
REDUCED D4 (`author_probe_from_spec`, T8/S5 8.5), and a minimal SYMBOLIC symptom
recogniser.

The reduced D4 carries no structured payload vector: the runner authors the
probe from the spec's target identity and evidence. The optional
`provenance.baseline_ref` names one recorded artifact to replay; otherwise the
first probe is a GET of the base URL. The legacy `payload_vector_space`
mutation parser is deleted (T8/T10): a replay's overrides are authored at the
pod's own exec tool, never read from a retired D4 field.

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
    baseline_ref_from_spec,
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


def author_probe_from_spec(spec: dict, variant_ref: str) -> ProbeChain | None:
    """Author the runner's first probe from the REDUCED D4 (S5 8.5).

    The optional `provenance.baseline_ref` wins: it names one recorded artifact
    to replay, so the core step carries `request_ref` and no URL. Otherwise the
    core step is a GET of `target_identity.url`. A chain with neither is the
    real "no probe derivable" outcome (None) - the graph then lands
    `no-symptom-evidence` with `clean=false`, never a fabricated request."""
    baseline = baseline_ref_from_spec(spec)
    if baseline:
        step = ProbeStep(role="core", request_ref=baseline)
    else:
        identity = spec.get("target_identity") or {}
        url = identity.get("url") if isinstance(identity, dict) else ""
        url = url.strip() if isinstance(url, str) else ""
        if not url:
            return None
        step = ProbeStep(role="core", method="GET", url=url)
    chain = ProbeChain(variant_ref=variant_ref, steps=[step])
    chain.signature = probe_signature(chain)
    return chain


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
