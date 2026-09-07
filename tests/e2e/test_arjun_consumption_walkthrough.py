"""E1 walkthrough (e2e tier) for #37 - arjun consumption set.

A full traced path from the pipeline's entry seam to its observable outcome:
a multi-route project seeded into Neo4j runs the arjun PHASE ONLY
(`job_subset=["arjun"]` - the dispatch shape under test, no crawl needed)
against a live reachable target. Terminal quantities are read back from the
persisted `recon_jobs` row.

Expected values come from the #37 grilling record, not recomputed:
  - `recon_jobs` shows pods == DISTINCT ROUTE CLUSTERS, not endpoints:
    `/anything/1` + `/anything/2` collapse to one pod, the
    JS-concat junk path (`/'+_(i[8])+'`) gets no pod at all.
  - the job reaches `success` (arjun actually probes each surviving cluster).

The live edge is arjun's real probing: each pod issues ~260 requests at
`--rate-limit 5` (~52s+ per pod), so this walkthrough takes minutes.
Runs host-side (localhost ports) or in-network (the compose `tests` runner,
service DNS) - whichever stack is reachable; skips when no live stack or no
LLM key is present, so it never breaks the offline suite.
"""
from __future__ import annotations

import importlib
import os
import socket
import uuid

import pytest

pytestmark = pytest.mark.live_neo4j

# NOTE (target selection, measured 2026-09-08): the first version of this
# walkthrough probed https://httpbin.org. Dispatch was perfect live (5 assets
# -> 3 pods on exactly the right clusters), but `/get` and `/anything/1`
# each need >200s of solo arjun time (vs ~100s for `/post`) - target-specific
# probe cost that exceeds EXEC_TIMEOUT_S=300 in-pod and fails the pods for
# reasons outside input-set selection. The second version probed a
# kali-local static-file stub and went VACUOUS: arjun "Skipped due to
# errors" after ONE request per pod with exit 0 (a static file server trips
# its stability probe), so three "successful" pods proved nothing. This
# version probes a kali-local QUERY-ECHO stub (mirrors the request path +
# args as JSON, like httpbin's /anything): arjun runs its FULL chunk set
# against it (~90s/pod locally). The stub counts every request to a file and
# the walkthrough asserts a request-volume floor - the anti-vacuous
# tripwire: a stability-skip (3 requests total) can never go green.
_STUB_PORT = 8888
_ARJUN_BASEURL = f"http://127.0.0.1:{_STUB_PORT}"
_ARJUN_PATHS = ["/get", "/post", "/anything/1", "/anything/2"]
# The echo stub, base64-embedded (no shell-quoting hazards). Plaintext:
#   from http.server import BaseHTTPRequestHandler, HTTPServer
#   from urllib.parse import urlparse, parse_qs
#   import json
#   class H(BaseHTTPRequestHandler):
#       def _r(self):
#           u = urlparse(self.path)
#           body = json.dumps({"path": u.path,
#                              "args": parse_qs(u.query)}).encode()
#           self.send_response(200)
#           self.send_header("Content-Type", "application/json")
#           self.send_header("Content-Length", str(len(body)))
#           self.end_headers()
#           self.wfile.write(body)
#           with open("/tmp/echo.count", "ab") as f:
#               f.write(b".")
#       do_GET = _r
#       do_POST = _r
#       def log_message(self, *a): pass
#   HTTPServer(("127.0.0.1", 8888), H).serve_forever()
_STUB_B64 = (
    "ZnJvbSBodHRwLnNlcnZlciBpbXBvcnQgQmFzZUhUVFBSZXF1ZXN0SGFuZGxlciwgSFRUUFNlcnZlcg"
    "pmcm9tIHVybGxpYi5wYXJzZSBpbXBvcnQgdXJscGFyc2UsIHBhcnNlX3FzCmltcG9ydCBqc29uCmNsYXNzIEgoQmFzZUhUVFBSZXF1ZXN0SGFuZGxlcik6CiAgICBkZWYgX3Ioc2VsZik6CiAgICAgICAgdSA9IHVybHBhcnNlKHNlbGYucGF0aCkKICAgICAgICBib2R5ID0ganNvbi5kdW1wcyh7InBhdGgiOiB1LnBhdGgsICJhcmdzIjogcGFyc2VfcXModS5xdWVyeSl9KS5lbmNvZGUoKQogICAgICAgIHNlbGYuc2VuZF9yZXNwb25zZSgyMDApCiAgICAgICAgc2VsZi5zZW5kX2hlYWRlcigiQ29udGVudC1UeXBlIiwgImFwcGxpY2F0aW9uL2pzb24iKQogICAgICAgIHNlbGYuc2VuZF9oZWFkZXIoIkNvbnRlbnQtTGVuZ3RoIiwgc3RyKGxlbihib2R5KSkpCiAgICAgICAgc2VsZi5lbmRfaGVhZGVycygpCiAgICAgICAgc2VsZi53ZmlsZS53cml0ZShib2R5KQogICAgICAgIHdpdGggb3BlbigiL3RtcC9lY2hvLmNvdW50IiwgImFiIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShiIi4iKQogICAgZG9fR0VUID0gX3IKICAgIGRvX1BPU1QgPSBfcgogICAgZGVmIGxvZ19tZXNzYWdlKHNlbGYsICphKTogcGFzcwpIVFRQU2VydmVyKCgiMTI3LjAuMC4xIiwgODg4OCksIEgpLnNlcnZlX2ZvcmV2ZXIoKQo="
)
# Floor: one full arjun probe issues ~107 requests against this stub
# (measured 2026-09-08: 321 across the 3 pods); 200 demands roughly two full
# probes while a stability-skip issues 3 and can never clear it.
_MIN_REQUESTS = 200
# JS string-concat fragment: the curator gate classifies it malformed, so the
# consumption set must exclude it preprocess-side - no pod is ever spent on it.
_ARJUN_JUNK_PATH = "/'+_(i[8])+'"

# Seed N distinct route clusters (dynamic-pair collapses to one).
_EXPECTED_PODS = 3  # /get, /post, /anything/*

_LLM_KEYS = ("OPENAI_API_KEY", "API_KEY_OPENROUTER", "API_KEY_OPENCODE")

pytestmark = pytest.mark.skipif(
    not any(os.environ.get(k) for k in _LLM_KEYS),
    reason="live LLM key required (one of OPENAI_API_KEY, API_KEY_OPENROUTER, "
    "API_KEY_OPENCODE - the last rides the in-network gateway)",
)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _in_network() -> bool:
    """True inside the compose network (service DNS resolves `neo4j`)."""
    try:
        socket.gethostbyname("neo4j")
        return True
    except OSError:
        return False


def _stack_reachable() -> bool:
    if _in_network():
        return (_port_open("neo4j", 7687) and _port_open("postgres", 5432)
                and _port_open("kali", 8000))
    return (_port_open("localhost", 7687) and _port_open("localhost", 5432)
            and _port_open("localhost", 8000))


def _bridge_env_to_localhost() -> None:
    """Bind the process to the live stack. Host-side: bridge the operator's
    env onto localhost service URLs (then reload config + neo4j_client, since
    conftest may have frozen dummy values at collection). In-network (the
    compose `tests` runner): the container env already carries service-DNS
    URLs, so only the model default and the pod-iteration bound are applied -
    localhost is never written over them."""
    if _in_network():
        os.environ["LLM_MODEL_TRIAGER"] = os.environ.get(
            "SB_ARJUN_MODEL", os.environ.get(
                "LLM_MODEL_TRIAGER", "openrouter:deepseek/deepseek-v4-flash"))
        os.environ.setdefault("MAX_POD_ITERS", "2")
        return
    if os.environ.get("API_KEY_OPENROUTER") or os.environ.get("OPENAI_API_KEY"):
        os.environ["API_KEY_OPENROUTER"] = (
            os.environ.get("API_KEY_OPENROUTER")
            or os.environ.get("OPENAI_API_KEY"))
    os.environ["LLM_MODEL_TRIAGER"] = os.environ.get(
        "SB_ARJUN_MODEL", "openrouter:deepseek/deepseek-v4-flash")
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_PASSWORD"] = os.environ.get("SB_NEO4J_PASSWORD", "polymerhus")
    os.environ["POSTGRES_DSN"] = "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus"
    os.environ["KALI_MCP_URL"] = "http://localhost:8000/mcp"
    os.environ.setdefault("MAX_POD_ITERS", "2")

    import polymerhus.app.config as config_mod
    importlib.reload(config_mod)
    from polymerhus.app.clients import neo4j_client
    importlib.reload(neo4j_client)


def test_e1_arjun_pods_equal_route_clusters_junk_absent():
    if not _stack_reachable():
        pytest.skip("live stack not reachable (neither localhost nor service DNS)")

    _bridge_env_to_localhost()

    import asyncio

    from polymerhus.app.clients import neo4j_client
    from polymerhus.recon.control import job_agent as ja
    from polymerhus.recon.control import pipeline
    from polymerhus.recon.control.jobs import JOBS

    # Fail-fast: the Kali MCP execute_command tool actually runs a command.
    from polymerhus.recon.domain.pod import default_exec_fn
    echo = default_exec_fn("echo arjun-e1", "preflight", 30)
    assert echo.returncode == 0 and "arjun-e1" in echo.stdout, echo

    # Stand up the kali-local query-echo stub (see the target-selection NOTE
    # above): base64-embedded (the established script-shipping pattern),
    # backgrounded with setsid so it survives the exec session, request
    # counter truncated first. Torn down best-effort at the end.
    www_setup = default_exec_fn(
        # NOTE: stale-server cleanup is PORT-based (`fuser -k`), never
        # `pkill -f`: the MCP session wrapper holds this very command line in
        # a parent cmdline, so any `pkill -f` pattern occurring in it
        # SIGTERMs the exec itself (observed: returncode=-15 in ~10ms).
        f"fuser -k {_STUB_PORT}/tcp 2>/dev/null; rm -f /tmp/echo.count && "
        f"echo {_STUB_B64} | base64 -d > /tmp/echo_stub.py && "
        f"(setsid nohup python3 /tmp/echo_stub.py >/tmp/echo.log 2>&1 &) && "
        f"sleep 1 && curl -s 'http://127.0.0.1:{_STUB_PORT}/get'",
        "stub-setup", 60,
    )
    assert www_setup.returncode == 0 and '"path": "/get"' in www_setup.stdout, www_setup

    project_id = f"arjun-e1-{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"

    neo4j_client.ensure_schema()

    # Seed the surface as if the crawlers had produced it: the known paths
    # (one restapi-profiled, so the restapi-first ordering has something to
    # order) plus the dynamic pair plus the junk fragment.
    with neo4j_client._driver.session() as s:
        s.run(
            "MERGE (b:BaseURL {url: $base, project_id: $pid}) "
            "ON CREATE SET b.first_seen = datetime() SET b.last_seen = datetime()",
            base=_ARJUN_BASEURL, pid=project_id,
        )
        for path in _ARJUN_PATHS + [_ARJUN_JUNK_PATH]:
            url = _ARJUN_BASEURL.rstrip("/") + path
            s.run(
                "MERGE (e:Endpoint {url: $url, project_id: $pid}) "
                "SET e.baseurl = $base, e.path = $path "
                "SET e.last_seen = datetime()",
                url=url, base=_ARJUN_BASEURL, path=path, pid=project_id,
            )
        s.run(
            "MATCH (e:Endpoint {project_id: $pid}) WHERE e.path = $p "
            "SET e.profile = 'restapi'",
            pid=project_id, p="/get",
        )

    # NOTE (seam finding, 2026-09-07): `pipeline.run_pipeline(...,
    # job_subset=["arjun"])` is REJECTED by `validate_job_subset` - arjun
    # consumes Endpoint, which no earlier SELECTED job produces. A single-job
    # subset for an Endpoint consumer is invalid by design (the validator is
    # correct: at schedule time nothing guarantees the graph already holds
    # Endpoints), so the live walkthrough drives the COMPILED JOB seam
    # instead: `run_job` with the production collaborators (real
    # `default_preprocess_fn` + real `default_pod_invoke` -> real arjun in
    # Kali, real triager turn, real curator MERGE). The seeded graph is read
    # back through the real `read_assets` seam, so the walkthrough covers
    # read -> derive -> probe -> persist end to end.
    assets = pipeline.read_assets("Endpoint", project_id)
    assert len(assets) == len(_ARJUN_PATHS) + 1, assets

    exports = asyncio.run(
        ja.run_job(
            JOBS["arjun"], assets, run_id=run_id, phase=7,
            extra={"project_id": project_id},
        )
    )

    # 1. Pods == route clusters, not endpoints: the dynamic pair collapsed
    #    (5 read-back assets -> 3 pods) and the junk fragment was excluded
    #    preprocess-side (no pod spent on it). Asserted BEFORE verdicts so a
    #    rerun always reports the dispatch shape even when a pod fails.
    assert len(exports) == _EXPECTED_PODS, [
        (e.input_asset.get("path"), e.verdict) for e in exports]
    probed = sorted(e.input_asset.get("path") or "/" for e in exports)
    assert probed == ["/anything/1", "/get", "/post"], probed
    # 2. Every pod probed successfully (arjun exit 0 within EXEC_TIMEOUT_S).
    assert all(e.verdict == "success" for e in exports), [
        (e.input_asset.get("path"), e.verdict) for e in exports]

    # 3. The anti-vacuous tripwire: the stub counted every request it served
    #    (one full probe issues ~107; three pods measured 321 on 2026-09-08).
    #    A stability-skip issues 3 and can never clear this floor.
    counted = default_exec_fn("wc -c < /tmp/echo.count", "stub-count", 30)
    assert counted.returncode == 0, counted
    assert int(counted.stdout.strip()) >= _MIN_REQUESTS, counted.stdout

    # 4. Best-effort stub teardown (never fails the walkthrough).
    default_exec_fn(f"fuser -k {_STUB_PORT}/tcp", "stub-teardown", 30)
