"""Typed, versioned construction of LightRAG ``/query/data`` requests.

``QuerySpecV1`` is a PROVISIONAL simulation contract. The production query
spec is owned by the Polyphemus module on ``dev``; when that contract lands,
replace the input model here while keeping ``build_q3``, ``derive_keywords``
and the hashing helpers stable so retrieval payloads remain auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

QUERY_SPEC_VERSION = "lightrag-query-spec/v1"
MAX_KEYWORDS = 8

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-./]*")

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "no", "not", "of", "on", "or", "that", "the", "this",
        "to", "with", "unknown", "unknowns", "evidence", "behavior",
        "behaviour", "testing", "test",
    }
)


def _require_non_blank(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class RetrievalConfigV1(BaseModel):
    """Per-mode parameters with the exact semantics observed on rc3.

    naive: chunk_top_k + max_total_tokens. mix: chunk_top_k + top_k +
    max_total_tokens. Entity/relation budgets and reranker are intentionally
    not exposed because the installed image does not use them.
    """

    mode: Literal["naive", "mix"] = "naive"
    chunk_top_k: int = Field(default=20, ge=1, le=100)
    top_k: int = Field(default=20, ge=1, le=100)
    max_total_tokens: int = Field(default=8000, ge=1000, le=32000)


# The two evidence-backed comparators from the Phase 6 report.
R_A = RetrievalConfigV1(mode="naive", chunk_top_k=20, top_k=20, max_total_tokens=8000)
R_B = RetrievalConfigV1(mode="mix", chunk_top_k=10, top_k=20, max_total_tokens=16000)


class EvidenceRefV1(BaseModel):
    ref: str
    summary: str

    @field_validator("ref", "summary")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        return _require_non_blank(value)


class QuerySpecV1(BaseModel):
    """Bounded projection of one testing concern onto LightRAG vocabulary.

    Mirrors the Phase 6B scenario fields so the Q3 baseline can be rebuilt
    byte-for-byte and hashed. Retrieved/injected content must never appear in
    these fields.
    """

    schema_version: Literal["lightrag-query-spec/v1"] = QUERY_SPEC_VERSION
    scenario_id: str
    attack_goal: str
    concern: str
    technology_stack: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    input_vectors: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    acceptable_technique_families: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRefV1] = Field(default_factory=list)
    expected_no_hypothesis: bool = False
    retrieval: RetrievalConfigV1 = Field(default_factory=RetrievalConfigV1)

    @field_validator("scenario_id", "attack_goal", "concern")
    @classmethod
    def _required_strings(cls, value: str) -> str:
        return _require_non_blank(value)

    @field_validator(
        "technology_stack",
        "target_refs",
        "input_vectors",
        "known_facts",
        "acceptable_technique_families",
        "unsupported_claims",
    )
    @classmethod
    def _string_lists(cls, values: list[str]) -> list[str]:
        return [_require_non_blank(value) for value in values]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: Any) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _joined(values: list[str], separator: str = ",") -> str:
    return separator.join(value for value in values if value.strip())


def build_q3(spec: QuerySpecV1) -> str:
    """Q3: natural-language goal + canonical controlled fields.

    Exact template that produced the best measured composite in Phase 6:
    ``<goal> Fields: target=.. | technology=.. | concern=.. | vectors=.. | sources=..``
    Empty field groups are omitted.
    """
    goal = spec.attack_goal.strip().rstrip(".")
    fields: list[str] = []
    if spec.target_refs:
        fields.append("target=" + _joined(spec.target_refs))
    fields.append("technology=" + _joined(spec.technology_stack))
    fields.append("concern=" + spec.concern.strip())
    if spec.input_vectors:
        fields.append("vectors=" + _joined(spec.input_vectors))
    return goal + " Fields: " + " | ".join(fields)


def _key_tokens(texts: list[str]) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        for token in _TOKEN_RE.findall(str(text).lower()):
            if token in _STOPWORDS or len(token) < 2:
                continue
            tokens.append(token)
    return list(dict.fromkeys(tokens))


def derive_keywords(spec: QuerySpecV1) -> dict[str, list[str]]:
    """Deterministic high/low-level keywords. No keyword LLM, no injection data."""
    high = _key_tokens([*spec.technology_stack, spec.concern])
    low = _key_tokens(
        [
            *spec.input_vectors,
            *spec.known_facts,
            *spec.acceptable_technique_families,
        ]
    )
    if not low:
        low = [token for token in high if token != "wstg"][: MAX_KEYWORDS // 2]
    if not low:
        low = ["application", "boundary"]
    return {"hl": high[:MAX_KEYWORDS], "ll": low[:MAX_KEYWORDS]}


def build_retrieval_payload(
    spec: QuerySpecV1, config: RetrievalConfigV1 | None = None
) -> dict[str, Any]:
    """Full ``POST /query/data`` body, including per-call parameter overrides."""
    config = config or spec.retrieval
    payload: dict[str, Any] = {
        "query": build_q3(spec),
        "mode": config.mode,
        "chunk_top_k": config.chunk_top_k,
        "max_total_tokens": config.max_total_tokens,
    }
    keywords = derive_keywords(spec)
    if config.mode == "mix":
        payload["top_k"] = config.top_k
        payload["hl_keywords"] = keywords["hl"]
        payload["ll_keywords"] = keywords["ll"]
    return payload
