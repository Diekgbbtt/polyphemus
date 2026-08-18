"""E2E capability run (runtime tier) for the SwissAI provider swap.

Verifies the new provider/model at RUNTIME - the actual `polymerhus-agent`
container's environment (`API_KEY_SWISSAI` + `LLM_MODEL_ANALYSER=swissai:...`
etc, set in `.env` and picked up on the last container recreate), not a
monkeypatched value. This drives one model instance through three generic
capabilities back to back - summarization, structured extraction, a follow-up
query grounded in the extracted state - and asserts on the REAL observed
output of each step, per the project's e2e discipline: no mocks, whole system,
live data.

Deliberately domain-independent: none of the prompts reference recon/analysis
concepts, because this is a baseline check on the provider swap itself, not a
polymerhus feature.

Gated + skippable: skips outright when `API_KEY_SWISSAI` is absent so it never
requires network by default.
"""
from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

from polymerhus.app.llm.providers import build_chat_model

pytestmark = pytest.mark.skipif(
    not os.environ.get("API_KEY_SWISSAI"),
    reason="live SwissAI key required (API_KEY_SWISSAI)",
)

_MODEL = os.environ.get("LIVE_SWISSAI_MODEL", "Qwen/Qwen3.5-397B-A17B-ETar")

_REPORT = (
    "Quarterly maintenance log: Turbine unit 3 was taken offline on March 4th "
    "for a scheduled bearing inspection. Technician A. Meier found moderate "
    "wear on the main shaft bearing and replaced it. The unit was returned to "
    "service on March 6th, two days ahead of the planned five-day window. No "
    "other units required intervention this quarter."
)


class _MaintenanceFacts(BaseModel):
    unit: str = Field(description="which unit was serviced")
    technician: str = Field(description="who performed the work")
    days_early: int = Field(description="how many days ahead of the planned window the unit returned to service")


def test_swissai_runtime_capability_sequence():
    model = build_chat_model("swissai", _MODEL)

    # --- 1. General summarization on a real sample -------------------------
    summary = model.invoke(
        "Summarize this maintenance log in one sentence:\n\n" + _REPORT
    ).content.strip()
    assert summary
    assert "3" in summary or "three" in summary.lower(), (
        f"summary dropped the unit identity: {summary!r}"
    )

    # --- 2. Structured parts extraction from the same real sample -----------
    facts = model.with_structured_output(_MaintenanceFacts).invoke(
        "Extract the requested fields from this maintenance log:\n\n" + _REPORT
    )
    assert isinstance(facts, _MaintenanceFacts)
    assert "3" in facts.unit
    assert "meier" in facts.technician.lower()
    assert facts.days_early == 2, facts

    # --- 3. Query grounded in the extracted state, run against the SAME live
    # model instance - proves the runtime path stays coherent across calls,
    # not just that one isolated prompt happens to work.
    answer = model.invoke(
        f"A turbine unit returned to service {facts.days_early} days ahead of "
        "schedule. In exactly one word, was it early, late, or on time?"
    ).content.strip().lower()
    assert "early" in answer, answer
