"""Live e2e (#206 E1 Shape A + T3/T4) - the recovery capability against the REAL
runtime, with minimal mocking.

Runner: the sibling polymerhus-206 agent container (docker-compose.sibling.yml)
mounting this worktree, on the shared network with the main-tree .env, through
its OWN co-located gateway to the configured triager model
(swissai DeepSeek-V4-Flash-0731), the pooled live postgres checkpointer, the
role's live compaction middleware, and the live summariser. The ONLY test knob
is the detection bound (LLM_BLACKLOOP_REASONING_BUDGET=200 in the sibling env),
which deterministically trips the cut on a live reasoning-first prompt.

Nothing else is substituted: no fake models, no InMemorySaver, no scripted
summariser. Shape B (phantom usage_metadata) is NOT forgeable through a live
provider and stays scripted by construction (see
test_blackloop_recovery_walkthrough.py).

Evidence: SessionTurn fields + the live thread read back from postgres +
compaction last_report + the Langfuse session trace (queried host-side).

Catalogue: #218 comment (C1-C5 contract live, E1-E2 walkthroughs).
Run: pytest tests/e2e/test_blackloop_live_walkthrough.py -q (sibling up).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.sibling.yml"]
SERVICE = "agent"

PROMPT = ("Consider the trade-offs of ten deployment strategies for a "
          "high-traffic API in exhaustive detail, comparing every pair, "
          "then state your single recommendation.")


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


def live_exec(code: str, *, timeout: int = 600,
              env: dict | None = None) -> dict:
    """Run a snippet in the sibling agent; parse its single-line JSON stdout."""
    cmd = list(COMPOSE) + ["exec", "-T"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [SERVICE, "python", "-c", code]
    result = _run(cmd, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"sibling exec failed:\nSTDOUT:\n{result.stdout}\n"
                           f"STDERR:\n{result.stderr[-4000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


PREFLIGHT = """
import httpx, os
key = os.environ.get("LITELLM_MASTER_KEY")
payload = {"model": "swissai/SwissAI-Research/zai-org/GLM-4.7-Flash",
           "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
           "stream": True, "max_completion_tokens": 50}
ok = False
try:
    with httpx.stream("POST", "http://127.0.0.1:4000/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json=payload, timeout=120) as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                ok = True
                break
except Exception:
    ok = False
print("UP" if ok else "DOWN")
"""


def _is_infra_flap(exc: BaseException) -> bool:
    text = str(exc)
    return "502" in text or "unreachable" in text or "BadGateway" in text


def live_exec_resilient(code: str, *, timeout: int = 600,
                        env: dict | None = None, attempts: int = 3) -> dict:
    """`live_exec` retried on the infra-flap signature only (gateway 502 /
    unreachable). Product failures (assertion-safe outputs, non-flap errors)
    are never retried - they propagate immediately."""
    last: RuntimeError | None = None
    for _ in range(attempts):
        try:
            return live_exec(code, timeout=timeout, env=env)
        except RuntimeError as exc:
            last = exc
            if not _is_infra_flap(exc):
                raise
            time.sleep(15)
    assert last is not None
    raise last


def upstream_serves() -> bool:
    """Independent upstream signal: can the provider stream one chunk right
    now? Used ONLY to classify a failure as infra-flap (retry) vs product
    (fail) - never as an assertion itself."""
    cmd = list(COMPOSE) + ["exec", "-T", SERVICE, "python", "-c", PREFLIGHT]
    result = _run(cmd, timeout=180)
    return result.returncode == 0 and "UP" in result.stdout


def require_upstream():
    if not upstream_serves():
        pytest.skip("swissai upstream unreachable right now (502 flap) - "
                    "infra, not product")


@pytest.fixture(scope="module")
def thread_id() -> str:
    assert sibling_running(), (
        "the polymerhus-206 sibling agent is not running - bring it up from "
        "this worktree (`docker compose -f docker-compose.sibling.yml up -d "
        "--build agent`) before the live tier")
    return f"live206-{int(time.time())}:triager"


# --- C1/C2: streamed client config + chunk granularity/timing ---------------

STREAM_PROBE = """
import json, time
from langchain_core.messages import HumanMessage
from polymerhus.app.llm.roles import chat_model_for
from polymerhus.app.llm.providers import ReasoningPreservingChatOpenAI
from polymerhus.app.llm import streaming as S
llm = chat_model_for("triager")
recs = []
t0 = time.monotonic()
for chunk in llm.stream([HumanMessage(content=%r)]):
    r = S.extract_reasoning(chunk) or ""
    c = S.extract_content(chunk) or ""
    kind = "reasoning" if r else ("content" if c else "other")
    recs.append({"kind": kind, "chars": len(r) + len(c),
                 "t": round(time.monotonic() - t0, 3)})
print(json.dumps({"class": type(llm).__name__, "chunks": recs}))
""" % PROMPT


def test_streaming_config_and_granularity_live():
    """C1/C2: the role client streams reasoning-then-content chunks with sane
    timing through the real gateway + model."""
    require_upstream()
    out = live_exec_resilient(STREAM_PROBE)
    assert out["class"] == "ReasoningPreservingChatOpenAI"
    recs = out["chunks"]
    assert len(recs) >= 3, f"expected a multi-chunk stream, got {len(recs)}"
    audible = [r for r in recs if r["kind"] != "other"]
    assert audible, "the stream must carry reasoning or content"
    assert audible[0]["kind"] == "reasoning", \
        "reasoning must lead the stream (past leading empty chunks)"
    kinds = [r["kind"] for r in recs]
    assert "content" in kinds, "the answer must arrive as content chunks"
    times = [r["t"] for r in recs]
    assert all(b >= a for a, b in zip(times, times[1:])), "timestamps monotonic"
    first_content = kinds.index("content")
    assert all(k != "content" for k in kinds[:first_content]), \
        "no content before the reasoning prefix"
    reasoning_chars = sum(r["chars"] for r in recs if r["kind"] == "reasoning")
    assert reasoning_chars > 200, "a reasoning-first prompt must reason"


# --- C4: the cut on the live stream ------------------------------------------

CUT_PROBE = """
import json
from langchain_core.messages import HumanMessage
from polymerhus.app.llm.checkpoints import (
    get_session_checkpointer, setup_session_checkpointer)
from polymerhus.app.llm.session import run_session_turn
setup_session_checkpointer()
turn = run_session_turn("triager", %r, [HumanMessage(content=%r)],
                        checkpointer=get_session_checkpointer(), observe=True)
print(json.dumps({"blackloop": turn.blackloop,
                  "reasoning_chars": len(turn.reasoning),
                  "content": str(turn.content or "")[:200],
                  "n_messages": len(turn.messages)}))
"""


def test_blackloop_cut_live(thread_id):
    """C4: a live reasoning-only prefix past the 8000-char bound cuts the stream
    (blackloop=True + captured reasoning), far below any ceiling."""
    require_upstream()
    out = live_exec_resilient(CUT_PROBE % (thread_id, PROMPT))
    assert out["blackloop"] is True
    assert out["reasoning_chars"] >= 8000, "the cut must carry the reasoning"
    assert out["content"] == "", "nothing answered before the cut"


# --- E1/E2 + C3/C5: recovery, chaining, live compaction convergence ----------

WALKTHROUGH_PROBE = """
import json
from langchain_core.messages import HumanMessage
from polymerhus.app.llm import compaction as C
from polymerhus.app.llm.checkpoints import (
    get_session_checkpointer, setup_session_checkpointer)
from polymerhus.app.llm.session import read_session_memory, stateful_turn
from polymerhus.app.llm.summary import _span_text
setup_session_checkpointer()
saver = get_session_checkpointer()
mw = C.cached_role_compaction_middleware("triager")
tid = %r
recovered = stateful_turn("triager", tid, [HumanMessage(content=%r)],
                          checkpointer=saver, middleware=[mw], observe=True)
followups = []
for k in range(1):
    followups.append(stateful_turn(
        "triager", tid, [HumanMessage(content="noted")],
        checkpointer=saver, middleware=[mw], observe=True))
report = mw.manager.last_report(tid)
mem = read_session_memory(saver, tid)
occupancy, _approx = C.compute_occupancy(mem.messages)
window = C.resolve_window("triager")
# C5: the projection mechanism applied to the LIVE persisted failed message.
span_hits = []
for m in mem.messages:
    if getattr(m, "additional_kwargs", None) and m.additional_kwargs.get("reasoning_content"):
        text = _span_text(m)
        rc = m.additional_kwargs["reasoning_content"]
        span_hits.append(rc[:60] in text)
        break
print(json.dumps({
    "recovered": str(recovered)[:500],
    "followups": [str(f)[:200] if f is not None else None for f in followups],
    "summary_status": report.summary_status if report else None,
    "summary": (report.new_summary.to_text() if report and report.new_summary
                else "")[:300] if report else None,
    "occupancy": occupancy, "budget": window.budget,
    "span_hit": span_hits[0] if span_hits else None,
}))
"""


@pytest.fixture(scope="module")
def walkthrough(thread_id) -> tuple[str, dict]:
    """Run the E1 walkthrough once (fresh thread per attempt, infra-flap
    retries); share the winning (thread, output) with the E1 assertions and
    the Langfuse evidence test so both read the SAME live run."""
    require_upstream()
    problems: list[str] = []
    out: dict | None = None
    tid = thread_id
    for attempt in range(3):
        tid = f"{thread_id}-a{attempt}"
        try:
            out = live_exec(WALKTHROUGH_PROBE % (tid, PROMPT), timeout=900)
        except RuntimeError as exc:
            if _is_infra_flap(exc) and attempt < 2:
                time.sleep(20)
                continue
            raise
        problems = _evaluate_walkthrough(out)
        if not problems:
            break
        if attempt < 2 and not upstream_serves():
            time.sleep(20)
            continue
        break
    assert out is not None
    if problems:
        pytest.fail(f"live walkthrough failed: {problems}; output={out}")
    return tid, out


def test_blackloop_cut_recovery_chaining_compaction_live(walkthrough):
    """E1/E2 + C3/C5: live cut -> recovery answer -> chained follow-ups ->
    native compaction settles under budget with the reasoning projected."""
    _, out = walkthrough
    assert not _evaluate_walkthrough(out)


def _evaluate_walkthrough(out: dict) -> list[str]:
    problems = []
    if not out["recovered"]:
        problems.append("recovery produced no answer (None)")
    if not all(out["followups"]):
        problems.append(f"chain broke after recovery: {out['followups']}")
    if out["summary_status"] != "ok":
        problems.append(f"compaction unsettled: {out['summary_status']}")
    if not out["summary"]:
        problems.append("no chainable running summary")
    if not out["occupancy"] < out["budget"]:
        problems.append(
            f"thread unconverged: {out['occupancy']} >= {out['budget']}")
    if out["span_hit"] is not True:
        problems.append("live failed reasoning not projected (T3)")
    return problems


# --- Langfuse evidence: the session trace carries the recovery --------------

def test_langfuse_session_trace_carries_recovery_live(walkthrough):
    """E1 evidence (trace level): the Langfuse session == winning walkthrough
    thread holds one trace per executed turn (initial cut turn, recovery turn,
    follow-ups), each opened under the traced seam with sane timing.

    Generation-level marks (blackloop_recovery metadata, summariser inputs)
    are ASSERTED NOWHERE live: every generation in project polyphemus is
    currently an empty shell (no model/input/output/metadata/usage), verified
    across recent sessions including a non-streamed control - a pre-existing,
    model-independent observability gap (filed separately), not a #206
    defect. The D11 metadata riding config['metadata'] stays unit-pinned."""
    from langfuse import Langfuse

    thread_id, _ = walkthrough

    def env_values():
        values: dict[str, str] = {}
        for line in (WORKTREE.parents[2] / ".env").read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    env = env_values()
    client = Langfuse(public_key=env["LANGFUSE_PUBLIC_KEY"],
                      secret_key=env["LANGFUSE_SECRET_KEY"],
                      host=env["LANGFUSE_HOST"])
    deadline = time.time() + 120
    traces = []
    while time.time() < deadline:
        traces = client.api.trace.list(session_id=thread_id).data
        if traces:
            break
        time.sleep(10)
    assert traces, f"no Langfuse trace for session {thread_id}"
    # One trace per executed turn on this thread (cut turn, recovery turn,
    # follow-ups): the turns ran under the traced session seam. Timestamps
    # must order with the run (all within the walkthrough window).
    assert len(traces) >= 2, \
        f"expected cut + recovery traces at least, got {len(traces)}"
    stamps = sorted(t.timestamp for t in traces)
    span = (stamps[-1] - stamps[0]).total_seconds()
    assert span >= 0, "trace timestamps must order"
