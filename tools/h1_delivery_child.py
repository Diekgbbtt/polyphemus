"""H1 Phase-1 child: emit ONE synthetic generation through the REAL handler +
real exporter, then die instantly via os._exit (defeats atexit flush).

Modes:
  noflush : exit immediately after on_llm_end (control arm - the bug)
  barrier : own-client flush() first, then exit (mechanism proof arm)

Usage: python h1_child.py <marker> <noflush|barrier>
Runs INSIDE the agent container (env keys + code mount live there).
"""
import os
import sys
import uuid

sys.path.insert(0, os.getcwd())

from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, LLMResult  # noqa: E402

from polymerhus.app.observability.langfuse_tracing import (  # noqa: E402
    get_langfuse_callbacks,
)


def main(marker, mode):
    handlers = get_langfuse_callbacks()
    assert len(handlers) == 1, "expected 1 real handler, got %d" % len(handlers)
    handler = handlers[0]
    run_id = uuid.uuid4()
    handler.on_llm_start(
        serialized={"name": "h1-loop"},
        prompts=["h1-prompt " + marker],
        run_id=run_id,
        parent_run_id=None,
        tags=["h1-loop"],
        metadata={"h1": True},
        invocation_params={"model_name": "h1-synthetic"},
    )
    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(
                message=AIMessage(content="h1-reply " + marker))]],
            llm_output={"model_name": "h1-synthetic",
                        "token_usage": {"prompt_tokens": 5,
                                        "completion_tokens": 7,
                                        "total_tokens": 12}},
        ),
        run_id=run_id,
        parent_run_id=None,
        inputs=["h1-prompt " + marker],
    )
    if mode == "barrier":
        client = getattr(handler, "_langfuse_client", None)
        if client is not None and hasattr(client, "flush"):
            client.flush()
    tid = str(getattr(handler, "last_trace_id", "") or "")
    os.write(1, ("TRACEID=%s\n" % tid).encode())
    try:
        with open("/tmp/h1_%s.tid" % mode, "w") as fh:
            fh.write(tid)
    except OSError:
        pass
    os._exit(0)


main(sys.argv[1], sys.argv[2])
