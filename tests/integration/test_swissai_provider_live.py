"""Live capability check for the new SwissAI provider/model swap.

The operator repointed every role's `.env` entry at
`swissai:Qwen/Qwen3.5-397B-A17B-ETar` and added a real `API_KEY_SWISSAI`. What
needs proving here is narrower than a role or a domain pipeline: that the
provider wiring in `polymerhus.app.llm.providers` actually reaches the new
endpoint/model and gets back usable completions for generic capabilities -
summarization, structured field extraction, and query answering - built
directly via `build_chat_model`, not through any role or domain seam. This is
deliberately NOT correlated with the recon/analysis domain: it is a baseline
sanity check on the provider swap itself.

Gated + skippable: skips outright when `API_KEY_SWISSAI` is absent, so it never
breaks the offline suite and never requires network by default.
"""
from __future__ import annotations

import json
import os

import pytest
from pydantic import BaseModel, Field

from polymerhus.app.llm.providers import build_chat_model

pytestmark = pytest.mark.skipif(
    not os.environ.get("API_KEY_SWISSAI"),
    reason="live SwissAI key required (API_KEY_SWISSAI)",
)

_MODEL = os.environ.get("LIVE_SWISSAI_MODEL", "Qwen/Qwen3.5-397B-A17B-ETar")


def _model():
    return build_chat_model("swissai", _MODEL)


def test_swissai_smoke():
    """Cheapest possible round-trip: the endpoint answers at all."""
    reply = _model().invoke("Reply with exactly the word: pong")
    assert "pong" in reply.content.lower()


_ARTICLE = (
    "The Rhine begins in the Swiss Alps and flows north through Lake Constance, "
    "then forms part of the border between Switzerland and Germany before "
    "continuing through France, Germany, and the Netherlands, where it empties "
    "into the North Sea. It is one of the longest rivers in Europe and has been "
    "used for trade and transport for centuries. Several major cities, including "
    "Basel, Strasbourg, and Cologne, sit directly on its banks."
)


def test_swissai_general_summarization():
    """Generic summarization: no domain vocabulary, just prose in, shorter
    prose out that still carries the source's core facts."""
    reply = _model().invoke(
        "Summarize the following text in one sentence:\n\n" + _ARTICLE
    )
    summary = reply.content.strip()
    assert summary, "empty summary"
    assert len(summary) < len(_ARTICLE)
    assert "rhine" in summary.lower()


class _RiverFacts(BaseModel):
    river_name: str = Field(description="the name of the river discussed")
    origin: str = Field(description="where the river originates")
    cities: list[str] = Field(description="cities on the river mentioned in the text")


def test_swissai_structured_extraction():
    """Generic structured extraction: pull typed fields out of free text via
    `with_structured_output`, independent of any polymerhus domain schema."""
    extractor = _model().with_structured_output(_RiverFacts)
    result = extractor.invoke(
        "Extract the requested fields from this text:\n\n" + _ARTICLE
    )
    assert isinstance(result, _RiverFacts)
    assert "rhine" in result.river_name.lower()
    assert result.origin.strip()
    assert any("basel" in c.lower() for c in result.cities), result.cities


def test_swissai_query_answering():
    """Generic query answering: a plain factual question with a checkable
    answer, unrelated to any recon/analysis concept."""
    reply = _model().invoke(
        "In exactly one word, what is the capital of Switzerland?"
    )
    assert "bern" in reply.content.lower()
