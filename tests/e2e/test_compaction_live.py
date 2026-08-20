"""E2E (LIVE): compaction fires against the REAL model.

The G-ticket walkthrough run for real: a hunter-actor session on the real opencode
zen model whose usage grows past the threshold, the out-of-band pass runs, the next
turn awaits the barrier, and the compacted state is observed (running summary
present, tokens reclaimed). The threshold is lowered for the test so the pass fires
within a couple of real turns rather than ~90% of a full window - the runtime
condition compaction READS is real per-step occupancy, which this drives with the
real model's own usage metadata. Skip-guarded on the model env: a clean environment
SKIPS, never fails.

Run with the model configured, e.g. from the host:
  API_KEY_OPENCODE=<key> LLM_MODEL_HUNTING_HUNTER=opencode:deepseek/deepseek-v4-flash-free \
  .venv/bin/python -m pytest tests/e2e/test_compaction_live.py -q
"""
from __future__ import annotations

import asyncio
import os

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.session import read_session_memory
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.actors import HuntingHunterActor


def _hunter_model_available() -> bool:
    return bool(
        os.environ.get("LLM_MODEL_HUNTING_HUNTER")
        and (os.environ.get("API_KEY_OPENCODE") or os.environ.get("API_KEY_OPENCODE_GO"))
    )


@pytest.mark.skipif(
    not _hunter_model_available(),
    reason="live LLM not configured (LLM_MODEL_HUNTING_HUNTER + API_KEY_OPENCODE)",
)
def test_hunter_lane_compacts_against_the_real_model():
    """The live walkthrough: real author turns grow the per-hunt thread past the
    threshold, the out-of-band pass runs on the real model, and the next turn's
    barrier applies the running summary - reclaimed tokens observable, the compacted
    thread carrying the synthetic summary message."""
    window = C.CompactionWindow(context_limit=4000, threshold=0.9)
    mw = HL.build_hunter_compaction_middleware(
        window=window, store=C.InMemoryToolOutputStore())

    async def drive():
        saver = InMemorySaver()
        actor = HuntingHunterActor(
            "run-live", "hunt-x", checkpointer=saver, observe=False, compaction=mw)
        await actor.author("compose a test spec for a CSRF fault on service a")
        await actor.author("compose a test spec for an SSRF fault on service b")
        await actor.author("compose a test spec for an XSS fault on service c")
        await actor.stop()
        return actor, saver

    actor, saver = asyncio.run(drive())
    report = mw.manager.last_report(actor.thread_id)
    assert report is not None, "the real-model session must have triggered a compact pass"
    assert report.readability == C.READABILITY_COMPACTED
    assert report.summary_status == "ok"
    assert report.reclaimed_tokens > 0
    mem = read_session_memory(saver, actor.thread_id)
    assert mem is not None
    assert any(str(m.content).startswith("[running summary]") for m in mem.messages)
