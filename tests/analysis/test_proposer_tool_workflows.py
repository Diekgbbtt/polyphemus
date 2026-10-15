"""Unit tier: the proposers' tool-use WORKFLOWS (prompt specs + call-site dedup).

Two surfaces are pinned here, both from the proposer-tool-workflows rework:

- **The Assigner's prompt layering.** The recorded-response read policy lives in
  the SYSTEM prompt (`prompts/assigner.md`); the volatile user turn
  carries the task and the deductive target, and repeats no tooling
  verbatim. The HTTP-history pair is the central widening seam: its remit
  reaches past disambiguation-only to an adjacently promising endpoint's
  fuller response, while the judgment stays chunk-scoped.
- **The mechanism-typist's tool-use specs.** The when+how for `graph_view`, the
  HTTP-history pair, and the bounded `exec` term are stated in both the skill
  (`prompts/technical-system.md`) and the reflection scaffold, and the 2nd/3rd
  chain calls rely on the seam's default role prompt instead of re-passing it.
"""
from __future__ import annotations

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.mechanism_typist import (
    _load_skill,
    _reflection_prompt,
    type_mechanisms,
)
from polymerhus.recon.domain.types import AssetDelta


def _endpoint(path, baseurl="https://a"):
    return AssetDelta(type="Endpoint", identity={"path": path, "baseurl": baseurl})


# --- the Assigner's prompt layering -------------------------------------------

def test_the_assigner_user_prompt_no_longer_repeats_the_graph_view_verbatim():
    """The adjacent-surface widening is the SYSTEM prompt's job (D-A2); the user
    turn must not duplicate it. The volatile half keeps the task and the
    deductive target and drops the `graph_view` verbatim."""
    from polymerhus.analysis.assigner import _user_prompt

    prompt = _user_prompt({"nodes": [], "edges": []}, {})
    assert "graph_view" not in prompt
    assert "DEDUCTIVE TARGET" in prompt


def test_the_assigner_skill_widens_the_http_pair_past_disambiguation_only():
    """The HTTP-history pair is no longer disambiguation/confirmation only: when a
    collected Endpoint looks even adjacently promising for a candidate Service
    (one endpoint often embeds several features), the assigner MAY pull its fuller
    response before judging ownership. The bound and the mechanism-typist
    ownership fence survive the widening."""
    from polymerhus.analysis.assigner import _load_assigner_skill

    skill = _load_assigner_skill()
    assert "search_http_history" in skill and "get_http_artifact" in skill
    assert "promising" in skill           # the widened remit
    assert "mechanism-typist" in skill    # the ownership fence is intact
    assert "never a trawl" in skill       # the bound is intact


# --- the mechanism-typist's tool-use specs ------------------------------------

def test_the_typist_skill_specifies_when_and_how_to_use_the_tools():
    """The skill must teach WHEN a tool call pays off (ORIENT/V ground a
    hypothesis; EMIT commits) and HOW to use each term, not merely name them."""
    skill = _load_skill()
    for term in ("graph_view", "search_http_history", "get_http_artifact", "exec"):
        assert term in skill, f"the skill names {term}"
    assert "Ground each hypothesis" in skill or "ground each hypothesis" in skill
    assert "read-only" in skill.lower()


def test_the_reflection_prompt_specifies_when_and_how_to_use_the_tools():
    """The reflection call is where the tool calls pay off, so its scaffold must
    license them (the old prompt forbade any tool call) and name the terms."""
    chunk = Chunk(chunk_id="c", concern="service", assets=(_endpoint("/x"),))
    prompt = _reflection_prompt(chunk, None)
    for term in ("graph_view", "search_http_history", "get_http_artifact", "exec"):
        assert term in prompt, f"the reflection prompt names {term}"
    assert "ORIENT" in prompt and "VERIFY" in prompt
    assert "may call" in prompt.lower() or "may run" in prompt.lower()


# --- the chain's prompt delivery (4c dedup) -----------------------------------

def test_the_typist_skill_is_the_seam_default_prompt_memoized():
    """The 4c pre-condition: `_load_skill()` is exactly the seam default for the
    role and is memoized byte-identical, so a call site that omits
    `system_prompt=` sends the SAME request bytes."""
    from polymerhus.analysis.proposer_turn import _role_prompt

    assert _load_skill() == _role_prompt("mechanism_typist")
    assert _load_skill() is _load_skill()


def test_the_later_typist_calls_rely_on_the_seam_default_prompt():
    """Dedup: only the first chain call passes the skill explicitly; the 2nd/3rd
    calls omit it (`None`) and let the seam resolve the byte-identical default,
    so the call sites no longer restate the prompt string."""
    captured: list[str | None] = []

    def invoke(messages, *, schema=None, system_prompt=None):
        captured.append(system_prompt)
        return "prose" if schema is None else L1DeltaBatch()

    type_mechanisms(
        Chunk(chunk_id="c", concern="service", assets=(_endpoint("/x"),)),
        invoke_fn=invoke,
    )
    assert captured == [_load_skill(), None, None]
