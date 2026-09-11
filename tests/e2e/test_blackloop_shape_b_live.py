"""Shape-B live emulation (#206 E1-companion): the phantom-usage convergence
through the real stack with a scaffolded payload.

Why a scaffold: a live provider cannot be made to emit a PHANTOM
usage_metadata (honest usage only) or megabytes of random text on demand.
So content generation alone is faked - a seeded RNG producing ~120KB of
random chars with MATCHED usage_metadata (~30k tokens) - while everything
the fix owns stays real: run_session_turn, the streamed capture, the
compaction middleware with an explicit small window, the LIVE summariser
(GLM-5.3 via the gateway), the module-scoped checkpointer, the native
turn-end barrier. A deterministic sentinel embedded in the reasoning proves
the core survives the fold; assertions are structural only.

Flow: turn 1 persists the oversized tail (pre-repair occupancy huge - the
Shape-B condition), turn 2's barrier settles the window-split chained pass,
then: report ok, occupancy under budget (convergence), chainable summary,
truncation markers on the bounded tail, sentinel in the summary.

Catalogue: #218 Shape-B predicate. Run with the live tier.
"""

from __future__ import annotations

import json
import random
import string
import subprocess
import time
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml",
           "-f", "docker-compose.dev.yml", "-f", "docker-compose.e2e.yml",
           "-f", "docker-compose.probe.yml"]
SERVICE = "agent"

KNOBS = {
    "LLM_MODEL_TRIAGER": "swissai:RCP-AIaaS/zai-org/GLM-5.3-Flash",
}

SEED = 206
SENTINEL = "SENTINEL-ALPHA-blackloop-core-7f3a9c"


def _run(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=WORKTREE, capture_output=True, text=True,
                          timeout=timeout)


def sibling_running() -> bool:
    result = _run(COMPOSE + ["ps", "--format", "json", SERVICE], timeout=60)
    if result.returncode != 0:
        return False
    for line in result.stdout.strip().splitlines():
        try:
            if json.loads(line).get("State") == "running":
                return True
        except json.JSONDecodeError:
            continue
    return False


def live_exec(code: str, *, timeout: int = 900) -> dict:
    cmd = list(COMPOSE) + ["exec", "-T"]
    for key, value in KNOBS.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [SERVICE, "python", "-c", code]
    result = _run(cmd, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"exec failed:\nSTDOUT:\n{result.stdout}\n"
                           f"STDERR:\n{result.stderr[-4000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


PROBE = """
import json, random, string
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.checkpoints import (
    get_session_checkpointer, setup_session_checkpointer)
from polymerhus.app.llm.session import read_session_memory, run_session_turn

SEED = 206
SENTINEL = "SENTINEL-ALPHA-blackloop-core-7f3a9c"

def noise(n, seed):
    rng = random.Random(seed)
    alpha = string.ascii_letters + string.digits + " \\n"
    return "".join(rng.choice(alpha) for _ in range(n))

class _SeededNoise(BaseChatModel):
    huge: bool = True
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.huge:
            return ChatResult(generations=[ChatGeneration(message=
                __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
                    content="a normal follow-up",
                    usage_metadata={"input_tokens": 120, "output_tokens": 20,
                                    "total_tokens": 140}))])
        from langchain_core.messages import AIMessage
        content = noise(60000, SEED)
        reasoning = noise(30000, SEED + 1) + SENTINEL + noise(30000, SEED + 2)
        total = (len(content) + len(reasoning)) // 4
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=content,
            additional_kwargs={"reasoning_content": reasoning},
            usage_metadata={"input_tokens": 900, "output_tokens": total - 900,
                            "total_tokens": total}))])
    @property
    def _llm_type(self):
        return "seeded-noise"
    def bind_tools(self, tools, **kwargs):
        return self

setup_session_checkpointer()
saver = get_session_checkpointer()
window = C.CompactionWindow(context_limit=2000, threshold=0.5)  # budget 1000
mw = C.build_role_compaction_middleware("triager", window=window)
tid = %r
huge = _SeededNoise(huge=True)
run_session_turn("triager", tid, [HumanMessage(content="the job")],
                 checkpointer=saver, middleware=[mw],
                 model_factory=lambda role: huge, observe=False)
mem = read_session_memory(saver, tid)
pre, _ = C.compute_occupancy(mem.messages)
# T4 mechanism on the LIVE oversized message: bound it and prove the bound
# (usage stripped, payloads excerpted with markers, head preserved).
bound = {"usage_gone": None, "marker": None, "shorter": None}
for m in mem.messages:
    kwargs = getattr(m, "additional_kwargs", None) or {}
    if isinstance(kwargs.get("reasoning_content"), str) and len(kwargs["reasoning_content"]) > 10000:
        bounded = C._bound_message(m, 2000)
        bkwargs = bounded.additional_kwargs or {}
        excerpted = bkwargs.get("reasoning_content") or ""
        original = kwargs["reasoning_content"]
        bound = {"usage_gone": getattr(bounded, "usage_metadata", None) is None,
                 "marker": "[...] (truncated)" in excerpted,
                 "shorter": len(excerpted) < len(original),
                 "head": excerpted.startswith(original[:512])}
        break
run_session_turn("triager", tid, [HumanMessage(content="continue")],
                 checkpointer=saver, middleware=[mw],
                 model_factory=lambda role: _SeededNoise(huge=False),
                 observe=False)
report = mw.manager.last_report(tid)
mem = read_session_memory(saver, tid)
post, _ = C.compute_occupancy(mem.messages)
def _full_text(m):
    parts = [str(m.content or "")]
    kwargs = getattr(m, "additional_kwargs", None) or {}
    if kwargs.get("reasoning_content"):
        parts.append(str(kwargs["reasoning_content"]))
    provider = kwargs.get("provider_specific_fields") or {}
    if isinstance(provider, dict) and provider.get("reasoning_details"):
        parts.append(str(provider["reasoning_details"]))
    return " ".join(parts)
joined = " ".join(_full_text(m) for m in mem.messages)
print(json.dumps({
    "pre_occupancy": pre, "budget": window.budget,
    "summary_status": report.summary_status if report else None,
    "summary": (report.new_summary.to_text() if report and report.new_summary
                else ""),
    "post_occupancy": post,
    "bound": bound,
    "sentinel_span": SENTINEL in joined,
}))
"""


@pytest.fixture(scope="module")
def thread_id() -> str:
    assert sibling_running(), "agent not running - bring the stack up first"
    return f"live206-shapeb-{int(time.time())}:triager"


def test_phantom_tail_converges_live(thread_id):
    """Shape-B emulation: a ~120KB seeded tail with matched ~30k-token usage
    pins occupancy; the native chained pass bounds it (usage stripped,
    payload excerpted with markers) and the thread converges under budget
    with the reasoning core folded into a chainable summary."""
    out = live_exec(PROBE % thread_id, timeout=1200)
    assert out["pre_occupancy"] > out["budget"], \
        f"scaffold must establish the over-budget condition: {out['pre_occupancy']}"
    assert out["summary_status"] == "ok", "the chained pass must settle"
    assert out["summary"], "a chainable running summary must exist"
    assert out["post_occupancy"] < out["budget"], \
        f"thread must converge: {out['post_occupancy']} >= {out['budget']}"
    assert out["bound"]["usage_gone"] is True, \
        "the bound must strip the phantom usage"
    assert out["bound"]["marker"] is True and out["bound"]["shorter"] is True, \
        "the bound must excerpt the live payload with markers"
    assert out["bound"]["head"] is True, "excerpts must preserve the head"
    assert SENTINEL in out["summary"], \
        "the reasoning core must survive into the summary"
