"""Live E2E: CRAWL-ONLY recon against the lab target, with katana at `-d 3`.

What this test is FOR (spec section 4): after the #196 lease fix, a pod can
finally RESOLVE the reconnaissance tools inside its leased namespace. This test
proves the crawl phase runs for real against `172.28.0.20` with the production
command template at depth 3, and that what the tool emitted is exactly what
landed in the graph - no more, no less - with every delta the curator gate
dropped attributed to the rule that dropped it.

Design decisions taken here (see the handoff prompt, section 8):

* D1 - depth knob: `recon.config.KATANA_DEPTH` (default `"1"`), read into the
  `JOBS["katana"]` template by concatenation at IMPORT time. The env var is set
  at the top of this module, BEFORE `polymerhus.recon.control.jobs` is imported,
  which is the knob's documented contract. A subprocess that imports the same
  catalogue with `KATANA_DEPTH` UNSET gives the production default: the test
  asserts the executed command differs from it in the depth token ALONE.
* D2 - driver: IN-PROCESS (the recommended variant). Project, settings, the
  "no seed" guard and every status/graph read go through the HTTP API on :8080;
  the pipeline itself is driven in this process so the exec seam can be teed and
  the tool log is the SAME single execution the graph was built from (no drift
  between "what we logged" and "what ran"). The orchestrator is the production
  `ReconOrchestratorActor` (`decide_routing=None`), built by a factory that
  wraps the real actor to count its turns.
* D3 - `["httpx","katana"]` is the minimal subset the static validator accepts
  (`katana` alone consumes `BaseURL`), so the crawl phase is preceded by the
  httpx probe that mints its input. Nothing later in the plan is selected.

Cost of the in-process choice, stated plainly: the run is NOT registered in the
agent's module runtime, so `POST /recon/{run_id}/stop` (which cancels the
runtime's task) cannot stop it - the test cancels its own task instead and says
so in the failure message. The process needs the same env the agent has (LLM
keys from `.env`, PG/Neo4j/kali on the published ports).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# Environment, established BEFORE any polymerhus import.
# --------------------------------------------------------------------------
# The target is a bare IP, never a URL: scope.parse_scope() classifies a URL as
# a DOMAIN and mints a garbage apex, which would silently widen the scope.
TARGET = "172.28.0.20"
DEPTH = os.environ.get("E2E_KATANA_DEPTH", "3")
CRAWL_SUBSET = ["httpx", "katana"]
# Every job the plan would schedule AFTER the crawl phase. None of them may
# appear in the run's per-job table: that IS the "crawl-only" assertion.
LATER_PHASE_JOBS = [
    "ffuf", "steel_crawl", "jsluice", "httpx_reprofile", "kiterunner", "arjun",
    "graphql-cop", "subfinder", "whois", "dnsx", "puredns",
    "subdomain_takeover", "naabu", "httpx_services",
]

AGENT_API = os.environ.get("E2E_AGENT_API", "http://localhost:8080")
RUN_TIMEOUT_S = int(os.environ.get("E2E_RUN_TIMEOUT_S", "420"))
ALLOW_SKIP = os.environ.get("E2E_CRAWL_ALLOW_SKIP") == "1"


def _resolve_endpoint(raw: str, override: str | None, default: str, internal_host: str) -> str:
    """Rewrite a compose-network / unit-tier-dummy endpoint to the HOST view.

    Two legitimate sources point somewhere this process cannot reach: the .env
    the agent container uses (`bolt://neo4j:7687`, `@postgres:5432`, `kali:8000`
    - resolvable only INSIDE the compose network) and tests/conftest.py's
    `.invalid` dummies, which exist so the unit tier cannot accidentally touch a
    live database. Both are remapped to the published ports; `E2E_*` overrides
    win, so an in-network runner can point them back at the service DNS names.
    """
    if override:
        return override
    if not raw or ".invalid" in raw or f"://{internal_host}:" in raw:
        return default
    return raw


os.environ["NEO4J_URI"] = _resolve_endpoint(
    os.environ.get("NEO4J_URI", ""), os.environ.get("E2E_NEO4J_URI"),
    "bolt://localhost:7687", "neo4j",
)
os.environ["POSTGRES_DSN"] = _resolve_endpoint(
    os.environ.get("POSTGRES_DSN", ""), os.environ.get("E2E_POSTGRES_DSN"),
    "postgresql://polymerhus:polymerhus@localhost:5432/polymerhus", "postgres",
)
os.environ["KALI_MCP_URL"] = _resolve_endpoint(
    os.environ.get("KALI_MCP_URL", ""), os.environ.get("E2E_KALI_MCP_URL"),
    "http://localhost:8000/mcp", "kali",
)
if (os.environ.get("NEO4J_PASSWORD") or "").startswith("dummy-"):
    os.environ["NEO4J_PASSWORD"] = "polymerhus"
os.environ.setdefault("NEO4J_USER", "neo4j")

MCP_URL = os.environ["KALI_MCP_URL"]
LIVE_POSTGRES_DSN = os.environ["POSTGRES_DSN"]

#: Cap on the stdout bytes written per invocation. Never truncate silently: an
#: over-cap capture is written truncated AND labelled `captured-truncated` with
#: the exact byte count in the tool log and the report.
MAX_CAPTURE_BYTES = 8 * 1024 * 1024

# The knob's contract: `JOBS` is built at import, so the env must be set first.
os.environ["KATANA_DEPTH"] = DEPTH

import polymerhus.recon.domain.pod as pod_module  # noqa: E402
from fastmcp import Client  # noqa: E402
from polymerhus.project_management import repository  # noqa: E402
from polymerhus.recon.control import pipeline  # noqa: E402
from polymerhus.recon.control.jobs import JOBS  # noqa: E402
from polymerhus.recon.control.orchestrator_agent import ReconOrchestratorActor  # noqa: E402
from polymerhus.recon.control.scope import parse_scope  # noqa: E402
from polymerhus.recon.domain import noise_filter  # noqa: E402
from polymerhus.recon.domain.parsers import katana_parser  # noqa: E402


# --------------------------------------------------------------------------
# Small helpers: env, HTTP, artifacts.
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _live_infra_pointers(monkeypatch):
    """Point the config-backed clients at the PUBLISHED ports.

    tests/conftest.py fills `.invalid` dummies so the unit tier can import
    config-backed modules; the live tier has to undo that for Postgres (Neo4j is
    rebound by conftest's own `live_neo4j` fixture, which is auto-applied to
    everything under tests/e2e/). Config mutation, not a logic seam: the same
    code paths run, only the DSN differs from the compose-network one.
    """
    from polymerhus.app.config import config

    # The class attributes were bound from the environment at import time. They
    # already hold the resolved values when this module imported first; the
    # explicit re-alignment covers the case where something else imported
    # `app.config` before this module's env block ran.
    for attr, value in (
        ("POSTGRES_DSN", LIVE_POSTGRES_DSN),
        ("KALI_MCP_URL", MCP_URL),
        ("NEO4J_URI", os.environ["NEO4J_URI"]),
        ("NEO4J_USER", os.environ["NEO4J_USER"]),
        ("NEO4J_PASSWORD", os.environ["NEO4J_PASSWORD"]),
    ):
        if getattr(config, attr, None) != value:
            monkeypatch.setattr(config, attr, value, raising=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable(reason: str) -> None:
    """Zero-skip by default: a down stack FAILS the test, it never skips."""
    if ALLOW_SKIP:
        pytest.skip(reason)
    pytest.fail(reason, pytrace=False)


def _api(method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    """Call the agent API. Returns (status, payload) - errors included."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        AGENT_API + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def _run_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(os.environ.get("E2E_ARTIFACT_DIR", REPO / ".e2e-artifacts"))
    path = root / "recon-crawl-katana-depth" / f"{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


# --------------------------------------------------------------------------
# The exec seam tee: one line per invocation, stdout beside it.
# --------------------------------------------------------------------------
class ToolLog:
    """Wraps the PRODUCTION exec collaborator (`pod.default_exec_fn`).

    Every pod invocation is forwarded verbatim and recorded: the filled command,
    the returncode, the duration, the capture state and the referenced #196 HTTP
    artifacts, with the tool's stdout written to its own file. Nothing is
    interpreted here - the comparison happens afterwards, from the raw bytes.
    """

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.stdout_dir = run_dir / "stdout"
        self.stdout_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = run_dir / "tool-log.jsonl"
        self.calls: list[dict] = []

    def exec_fn(self, command: str, session_id: str, timeout_s: int):
        started = time.monotonic()
        result = pod_module.default_exec_fn(command, session_id, timeout_s)
        wall_ms = int((time.monotonic() - started) * 1000)

        index = len(self.calls) + 1
        tool = (command.split() or [""])[0]
        # `default_pod_invoke` mints session ids as
        # f"{run_id}-{phase}-{job.tool}-{uuid4().hex[:8]}"; the tool name can
        # contain dashes (graphql-cop), so anchor the phase on the known tool.
        match = re.search(r"-(\d+)-" + re.escape(tool) + r"-[0-9a-f]{8}$", session_id)
        phase = int(match.group(1)) if match else None
        target_match = re.search(r"(?:^|\s)-u\s+(\S+)", command)
        asset = target_match.group(1) if target_match else ""

        stdout = result.stdout or ""
        raw = stdout.encode("utf-8")
        capture_state = "captured"
        capture_note = ""
        if not raw:
            capture_state = "omitted"
            capture_note = "empty stdout: the tool produced no output for this pod"
        if len(raw) > MAX_CAPTURE_BYTES:
            capture_state = "captured-truncated"
            capture_note = (
                f"stdout {len(raw)}B exceeds the {MAX_CAPTURE_BYTES}B cap; the file "
                f"holds the first {MAX_CAPTURE_BYTES}B (byte count exact)"
            )
            raw = raw[:MAX_CAPTURE_BYTES]

        stdout_path = self.stdout_dir / f"{index:03d}-{tool}.out"
        stdout_path.write_bytes(raw)

        record = {
            "index": index,
            "ts": _now(),
            "phase": phase,
            "job": tool,
            "asset": asset,
            "session_id": session_id,
            "command": command,
            "returncode": result.returncode,
            "duration_ms": result.duration_ms,
            "wall_ms": wall_ms,
            "stdout_path": str(stdout_path.relative_to(self.run_dir)),
            "stdout_bytes": len(stdout.encode("utf-8")),
            "stdout_lines": stdout.count("\n") + (1 if stdout and not stdout.endswith("\n") else 0),
            "capture_state": capture_state,
            "capture_note": capture_note,
            "http_artifact_refs": list(result.http_artifact_refs or []),
            "capture_warning": result.capture_warning,
            "stderr": (result.stderr or "")[:2000],
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self.calls.append({**record, "stdout": raw.decode("utf-8", "replace")})
        print(
            f"[tool-log] #{index} job={tool} phase={phase} rc={result.returncode} "
            f"duration_ms={result.duration_ms} stdout_bytes={record['stdout_bytes']} "
            f"capture={capture_state}",
            flush=True,
        )
        return result


# --------------------------------------------------------------------------
# Preflight pieces.
# --------------------------------------------------------------------------
def _preflight_health() -> dict:
    try:
        status, payload = _api("GET", "/health", timeout=10)
    except Exception as exc:  # noqa: BLE001 - a dead stack fails, never skips
        _unavailable(f"agent API {AGENT_API}/health is unreachable: {type(exc).__name__}: {exc}")
    if status != 200:
        _unavailable(f"agent /health returned HTTP {status}: {json.dumps(payload)[:400]}")
    checks = payload.get("checks") or {}
    bad = {k: v for k, v in checks.items() if v is not True}
    if bad or payload.get("status") != "ok":
        _unavailable(f"stack not healthy: {json.dumps(payload)[:500]}")
    return payload


def _preflight_llm() -> None:
    """The in-process driver runs the REAL triager/configurator, so the same
    boot-time validation the agent does must pass here too."""
    from polymerhus.app.llm.providers import validate_llm_config

    try:
        validate_llm_config()
    except Exception as exc:  # noqa: BLE001
        _unavailable(
            "LLM configuration invalid for the in-process driver "
            f"({type(exc).__name__}: {exc}). Source the real env first, e.g. "
            "`set -a; . /home/alelxsalc03/Desktop/polyphemus/.env; set +a`."
        )


LEASE_PREFLIGHT_COMMAND = (
    "command -v httpx; command -v katana; "
    "httpx -u " + TARGET + " -sc -title -td -server -silent -json; echo rc=$?"
)


def _lease_preflight(project_id: str, artifacts: Path) -> dict:
    """The §3.7 preflight, through the kali MCP server (which leases a netns).

    Deliberately WITHOUT any `export PATH=...`: the post-fix runner uses a
    non-login shell, so the entrypoint's tools path survives and the export must
    be unnecessary. `/usr/bin/httpx` (the Python CLI - `Error: No such option:
    -u`) or a MISSING katana means the lease fix is not in force and this test
    cannot measure anything: FAIL here, loudly, before burning a run.
    """
    async def _call():
        async with Client(MCP_URL) as client:
            result = await client.call_tool(
                "execute_command",
                {"command": LEASE_PREFLIGHT_COMMAND, "session_id": "crawl-depth-preflight",
                 "project_id": project_id},
            )
        return result.data

    try:
        data = asyncio.run(_call())
    except Exception as exc:  # noqa: BLE001
        _unavailable(f"kali MCP at {MCP_URL} failed the lease preflight: {type(exc).__name__}: {exc}")

    _write_json(artifacts / "lease-preflight.json", data)
    stdout = data.get("stdout") or ""
    lines = stdout.splitlines()
    json_line = next((ln for ln in lines if ln.startswith("{")), "")
    probe = {}
    if json_line:
        with contextlib.suppress(json.JSONDecodeError):
            probe = json.loads(json_line)

    problems = []
    if len(lines) < 2 or lines[0] != "/root/go/bin/httpx":
        problems.append(f"httpx resolved to {lines[0] if lines else 'MISSING'!r}, not /root/go/bin/httpx")
    if len(lines) < 2 or lines[1] != "/root/go/bin/katana":
        problems.append(f"katana resolved to {lines[1] if len(lines) > 1 else 'MISSING'!r}, not /root/go/bin/katana")
    if "redagraph" in stdout:
        problems.append("the login-shell MOTD banner is still present on stdout")
    if probe.get("status_code") != 200:
        problems.append(f"the real httpx call did not report status_code 200: {probe or json_line[:200]!r}")
    if "rc=0" not in lines:
        problems.append("`rc=$?` did not report rc=0")
    if not data.get("http_artifact_refs"):
        problems.append("http_artifact_refs is empty: the #196 capture plane did not record the call")
    if problems:
        _unavailable(
            "lease preflight failed - the kali container is not serving this branch's "
            "fix, or tools/PATH/capture are broken: " + "; ".join(problems)
            + f"\nstdout={stdout[:800]!r}\nstderr={(data.get('stderr') or '')[:400]!r}"
        )
    print(f"[preflight] lease resolved httpx+katana from /root/go/bin, "
          f"status_code={probe.get('status_code')}, refs={len(data['http_artifact_refs'])}",
          flush=True)
    return data


# --------------------------------------------------------------------------
# The command-template comparison (D1's "byte-identical except depth").
# --------------------------------------------------------------------------
_DEPTH_RE = re.compile(r" -d (\d+) ")


def _production_template() -> str:
    """The katana template as the PRODUCTION DEFAULT builds it.

    Read in a subprocess with `KATANA_DEPTH` unset, from the same source tree -
    the honest reference for "every other flag is unchanged", not a copy of the
    string frozen into this test.
    """
    env = {k: v for k, v in os.environ.items() if k != "KATANA_DEPTH"}
    env["PYTHONPATH"] = str(REPO / "src")
    proc = subprocess.run(
        [sys.executable, "-c",
         "from polymerhus.recon.control.jobs import JOBS; print(JOBS['katana'].command_template)"],
        env=env, capture_output=True, text=True, cwd=str(REPO),
    )
    assert proc.returncode == 0, f"could not read the production template: {proc.stderr[-800:]}"
    return proc.stdout.rstrip("\n")


def _assert_katana_command(call: dict, production_template: str) -> dict:
    """The executed command must differ from the production template ONLY by the
    depth token and the `{target}`/`{auth_header}` placeholders."""
    command = call["command"]
    prod_depth = _DEPTH_RE.search(production_template)
    assert prod_depth and prod_depth.group(1) == "1", (
        f"the production default depth is no longer 1: {production_template[:80]!r}"
    )
    exec_depth = _DEPTH_RE.search(command)
    assert exec_depth and exec_depth.group(1) == DEPTH, (
        f"the executed katana command does not carry `-d {DEPTH}`: {command[:200]!r}"
    )
    assert len(_DEPTH_RE.findall(command)) == 1, f"more than one depth token: {command!r}"

    target_match = re.search(r"(?:^|\s)-u\s+(\S+)", command)
    assert target_match, f"no `-u <target>` in the executed command: {command!r}"
    target_used = target_match.group(1)
    assert target_used in {TARGET, f"http://{TARGET}", f"https://{TARGET}"}, (
        f"katana was pointed at {target_used!r}, not at the seeded target {TARGET!r}"
    )

    expected = (
        production_template
        .replace(prod_depth.group(0), f" -d {DEPTH} ")
        .replace("{target}", target_used)
        .replace("{auth_header}", "")
    )
    if command != expected:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(command, expected)) if a != b),
            min(len(command), len(expected)),
        )
        pytest.fail(
            "the executed katana command is not the production template at "
            f"depth {DEPTH} (first difference at char {first_diff}, excluding the "
            f"depth token and the placeholders)\n  executed: {command!r}\n  expected: {expected!r}",
            pytrace=False,
        )
    return {"target_used": target_used, "depth": DEPTH, "production_default_depth": prod_depth.group(1)}


# --------------------------------------------------------------------------
# The delta report: tool log -> parser -> production gate -> graph.
# --------------------------------------------------------------------------
def _drop_rule(delta, scope_domain: str | None) -> str | None:
    """Name the rule `filter_deltas` applies, evaluated in ITS order.

    The gate itself stays the authority for `kept` (it is called for real); this
    only reproduces the predicates so each dropped delta can be attributed. The
    report asserts the two agree, so a rule added to the gate without being
    named here turns into a loud mismatch instead of a silent mis-report.
    """
    if delta.type == "Endpoint":
        path = delta.identity.get("path", "/")
        if noise_filter.is_malformed_concat_path(path):
            return "malformed_concat_path"
        if noise_filter.classify_endpoint(
            path, has_params=noise_filter._endpoint_has_params(delta)
        ) == "static":
            return "static_presentational_endpoint"
    if noise_filter._delta_is_www_redundant(delta):
        return "www_redundant_dedup"
    if scope_domain and noise_filter._delta_out_of_scope(delta, scope_domain):
        return "out_of_scope_host"
    return None


def _delta_key(delta) -> str:
    ident = ",".join(f"{k}={delta.identity[k]!r}" for k in sorted(delta.identity))
    return f"{delta.type}({ident})"


def _gate_positive_control(scope_domain: str) -> dict:
    """Prove the gate is LIVE with this scope before trusting a zero.

    Two synthetic deltas carry exactly the two shapes `filter_deltas` exists to
    drop: a param-less presentational Endpoint, and a BaseURL on a third-party
    origin. If the gate is wired to this scope it must drop both (and my
    attribution helper must name both rules) - only then does "0 drops on the
    real tool log" mean "there was nothing to drop" instead of "the gate never
    ran / the scope was wrong".
    """
    from polymerhus.recon.domain.types import AssetDelta

    samples = [
        AssetDelta(
            type="Endpoint",
            identity={"path": "/assets/app.css", "method": "GET",
                      "baseurl": f"http://{scope_domain}"},
        ),
        AssetDelta(type="BaseURL", identity={"url": "http://cdn.example.net"}),
    ]
    kept = noise_filter.filter_deltas([s.model_copy(deep=True) for s in samples], scope_domain=scope_domain)
    dropped_rules = sorted(
        r for r in (_drop_rule(s, scope_domain) for s in samples) if r
    )
    return {
        "samples": [_delta_key(s) for s in samples],
        "kept": [_delta_key(d) for d in kept],
        "dropped_rules": dropped_rules,
    }


def _node_matches_delta(node: dict, delta) -> bool:
    props = node.get("properties") or {}
    if node.get("type") != delta.type:
        return False
    return all(str(props.get(k)) == str(v) for k, v in delta.identity.items())


def _build_delta_report(run_dir: Path, tool_log: ToolLog, project_id: str, graph: dict) -> dict:
    katana_calls = [c for c in tool_log.calls if c["job"] == "katana"]
    assert katana_calls, "no katana invocation reached the exec seam"
    # Production parses each pod's stdout independently; with the seed IP there
    # is one BaseURL, hence one pod - but keep the per-pod shape so a wider input
    # set stays representable instead of being silently concatenated.
    per_pod = []
    for call in katana_calls:
        per_pod.extend(katana_parser.parse(call["stdout"]))
    delta = per_pod

    scope = parse_scope(TARGET)
    scope_domain = scope["seed_host"]  # exactly what pipeline puts in extra[]

    delta_copy = [d.model_copy(deep=True) for d in delta]
    kept = noise_filter.filter_deltas(delta_copy, scope_domain=scope_domain)
    kept_keys = {id(d) for d in kept}
    dropped = []
    for d in delta_copy:
        if id(d) in kept_keys:
            continue
        dropped.append({"delta": _delta_key(d), "rule": _drop_rule(d, scope_domain) or "UNATTRIBUTED"})
    unattributed = [d for d in dropped if d["rule"] == "UNATTRIBUTED"]

    # What the gate COULD have acted on, measured on this very delta set - so
    # "0 drops" is a statement about the input, not an unexercised gate.
    hosts = sorted({
        h for d in delta_copy for h in noise_filter._referenced_base_hosts(d)
    })
    paths = sorted({d.identity.get("path") for d in delta_copy if d.type == "Endpoint"})
    observed = {
        "hosts": hosts,
        "endpoint_paths": paths,
        "static_classified_endpoints": [
            p for p in paths if noise_filter.classify_endpoint(p, has_params=False) == "static"
        ],
        "www_prefixed_hosts": [h for h in hosts if h.lower().startswith("www.")],
        "malformed_concat_paths": [
            p for p in paths if noise_filter.is_malformed_concat_path(p or "/")
        ],
        "out_of_scope_hosts": [
            h for h in hosts if not noise_filter.host_in_scope(h, scope_domain)
        ],
    }
    control = _gate_positive_control(scope_domain)

    nodes = graph.get("nodes") or []
    collected = [n for n in nodes if (n.get("properties") or {}).get("source") == "katana"]

    unexplained_collected = [
        n for n in collected
        if not any(_node_matches_delta(n, d) for d in kept)
    ]
    unexplained_kept = [
        d for d in kept
        if not any(_node_matches_delta(n, d) for n in nodes)
    ]
    # A drop the gate is allowed to make and that still shows up in the graph
    # would mean the two sides disagree about the gate's own verdict.
    collected_but_dropped = [
        n for n in collected
        if any(_node_matches_delta(n, d) for d in delta_copy if id(d) not in kept_keys)
    ]

    by_rule: dict[str, list[str]] = {}
    for d in dropped:
        by_rule.setdefault(d["rule"], []).append(d["delta"])

    report = {
        "project_id": project_id,
        "target": TARGET,
        "scope_mode": scope["mode"],
        "scope_domain": scope_domain,
        "katana_invocations": len(katana_calls),
        "stdout_bytes_parsed": sum(len(c["stdout"].encode()) for c in katana_calls),
        "delta_total": len(delta),
        "gate_kept": len(kept),
        "gate_dropped": len(dropped),
        "dropped_by_rule": {k: {"count": len(v), "examples": sorted(v)[:10]} for k, v in sorted(by_rule.items())},
        "collected_source_katana": len(collected),
        "collected_by_label": _count_labels(collected),
        "kept_by_label": _count_types(kept),
        "unexplained_collected": [_delta_key_like(n) for n in unexplained_collected],
        "unexplained_kept": [_delta_key(d) for d in unexplained_kept],
        "collected_but_dropped_by_gate": [_delta_key_like(n) for n in collected_but_dropped],
        "unattributed_drops": [d["delta"] for d in unattributed],
        "observed": observed,
        "gate_control": control,
    }
    report["_observed"] = observed
    report["_gate_control"] = control
    report["_kept"] = kept
    report["_dropped"] = dropped
    report["_unexplained_collected"] = unexplained_collected
    report["_unexplained_kept"] = unexplained_kept
    report["_collected_but_dropped"] = collected_but_dropped
    return report


def _count_labels(nodes: list[dict]) -> dict:
    out: dict[str, int] = {}
    for n in nodes:
        out[n.get("type") or "?"] = out.get(n.get("type") or "?", 0) + 1
    return dict(sorted(out.items()))


def _count_types(deltas: list) -> dict:
    out: dict[str, int] = {}
    for d in deltas:
        out[d.type] = out.get(d.type, 0) + 1
    return dict(sorted(out.items()))


def _delta_key_like(node: dict) -> str:
    props = node.get("properties") or {}
    return f"{node.get('type')}(name={props.get('name')},url={props.get('url')},path={props.get('path')})"


def _write_delta_report_md(path: Path, report: dict, expected_render_note: str) -> None:
    lines = [
        "# Delta report - tool log vs collected (katana, crawl-only)",
        "",
        f"- project_id: `{report['project_id']}`",
        f"- target: `{report['target']}` (scope mode `{report['scope_mode']}`, scope domain `{report['scope_domain']}`)",
        f"- katana invocations: {report['katana_invocations']} "
        f"({report['stdout_bytes_parsed']} bytes of stdout parsed)",
        "",
        "## Counts",
        "",
        f"- parsed deltas: {report['delta_total']} {report['kept_by_label']}",
        f"- kept by the gate: {report['gate_kept']}",
        f"- dropped by the gate: {report['gate_dropped']}",
        f"- collected nodes with `source=katana`: {report['collected_source_katana']} {report['collected_by_label']}",
        f"- kept deltas with no node in the graph (unexplained): {len(report['unexplained_kept'])}",
        f"- `source=katana` nodes absent from the tool log (unexplained): {len(report['unexplained_collected'])}",
        f"- `source=katana` nodes the gate itself dropped: {len(report['collected_but_dropped_by_gate'])}",
        f"- drops with no attributable rule: {len(report['unattributed_drops'])}",
        "",
        "## Drops, by rule (every drop is listed)",
        "",
    ]
    if report["dropped_by_rule"]:
        for rule, info in report["dropped_by_rule"].items():
            lines.append(f"- **{rule}**: {info['count']}")
            lines += [f"  - `{ex}`" for ex in info["examples"]]
            if info["count"] > len(info["examples"]):
                lines.append(f"  - ... {info['count'] - len(info['examples'])} more")
    else:
        lines.append(
            "- **no drops**: the tool log produced nothing the gate is designed to "
            "catch. Not a null result - it is the expected render for this target."
        )
    obs = report["observed"]
    ctrl = report["gate_control"]
    lines += [
        "",
        "## Observed inventory (what the gate saw)",
        "",
        f"- hosts in the delta set: `{obs['hosts']}`",
        f"- endpoint paths: `{obs['endpoint_paths']}`",
        f"- static-classified endpoints: `{obs['static_classified_endpoints']}`",
        f"- `www.`-prefixed hosts: `{obs['www_prefixed_hosts']}`",
        f"- malformed concat paths: `{obs['malformed_concat_paths']}`",
        f"- out-of-scope hosts: `{obs['out_of_scope_hosts']}`",
        "",
        "## Gate control (a measured zero, not an unexercised gate)",
        "",
        f"- synthetic samples the gate must drop: `{ctrl['samples']}`",
        f"- kept by the gate (must be empty): `{ctrl['kept']}`",
        f"- rules that fired: `{ctrl['dropped_rules']}`",
        "",
        "## Expected render",
        "",
        expected_render_note,
        "",
        "## Unexplained",
        "",
        f"- kept-but-not-collected: `{report['unexplained_kept']}`",
        f"- collected-but-not-in-log: `{[_delta_key_like(n) for n in report['_unexplained_collected']]}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


EXPECTED_RENDER = (
    "`172.28.0.20` is a deterministic local target that serves a 5-line "
    "`text/plain` body: no links, no forms, no JS, no cookies required. Depth 1 "
    "and depth 4 therefore render the SAME set - the proof of the depth is the "
    "command that ran and its clean termination, not the yield. A near-empty "
    "delta is the CORRECT result; a rich one would mean the crawler reached "
    "something that is not this target."
)


# --------------------------------------------------------------------------
# The test.
# --------------------------------------------------------------------------
def test_recon_crawl_only_with_katana_depth(tmp_path, monkeypatch):
    run_dir = _run_dir()
    print(f"[artifacts] {run_dir}", flush=True)

    # --- A. Preflight ------------------------------------------------------
    health = _preflight_health()
    _preflight_llm()

    project_name = f"e2e-crawl-{uuid.uuid4().hex[:8]}"
    project_id = _api("POST", "/projects", {"name": project_name})[1]["project_id"]
    print(f"[project] {project_name} -> {project_id}", flush=True)

    # The lease fix must be in force BEFORE anything else is measured - and the
    # preflight runs with the project this run actually uses.
    lease = _lease_preflight(project_id, run_dir)

    # --- B. Seed + the launch guards ---------------------------------------
    # The seed is a bare host/IP by contract: a URL would be classified as a
    # domain and mint a garbage apex. Assert that on the value we send.
    assert "://" not in TARGET and ":" not in TARGET, "the seed must be a bare host/IP, never a URL"
    assert parse_scope(TARGET)["mode"] == "host"
    status, payload = _api(
        "PUT", f"/projects/{project_id}/settings", {"recon": {"target_seed": TARGET}}
    )
    assert (status, payload) == (200, {"ok": True}), (status, payload)

    # A launch without a seed must be refused (proves the guard is alive).
    bare_project = _api("POST", "/projects", {"name": f"e2e-noseed-{uuid.uuid4().hex[:8]}"})[1]["project_id"]
    status, payload = _api("POST", f"/projects/{bare_project}/recon", {"jobs": CRAWL_SUBSET, "with_analysis": False})
    assert status == 400 and "no target_seed" in json.dumps(payload), (status, payload)

    # IPv6 seeding is designed-not-built: refused at launch.
    v6_project = _api("POST", "/projects", {"name": f"e2e-ipv6-{uuid.uuid4().hex[:8]}"})[1]["project_id"]
    _api("PUT", f"/projects/{v6_project}/settings", {"recon": {"target_seed": "2001:db8::1"}})
    status, payload = _api("POST", f"/projects/{v6_project}/recon", {"jobs": CRAWL_SUBSET, "with_analysis": False})
    assert status == 400 and "IPv6" in json.dumps(payload), (status, payload)

    # Unknown job, and a structurally incoherent subset (katana alone consumes a
    # BaseURL nobody produces) - both 400, both before any run row exists.
    status, payload = _api("POST", f"/projects/{project_id}/recon", {"jobs": ["httpx", "nope"], "with_analysis": False})
    assert status == 400 and "unknown job" in json.dumps(payload), (status, payload)
    status, payload = _api("POST", f"/projects/{project_id}/recon", {"jobs": ["katana"], "with_analysis": False})
    assert status == 400, (status, payload)

    # --- C. The crawl-only run ---------------------------------------------
    run_id = repository.open_run(project_id)
    status, run = _api("GET", f"/projects/{project_id}/recon/{run_id}")
    assert status == 200 and run["status"] in {"running", "pending", "queued"}, run

    tool_log = ToolLog(run_dir)
    tee_graph = pod_module.build_pod_graph(
        exec_fn=tool_log.exec_fn,
        # Same collaborators the production `pod_graph` is built with, so only
        # the exec call is intercepted (the tee forwards to the real one).
        curate_fn=pod_module.curate,
        triage_fn=pod_module.default_triage_fn,
        configure_fn=pod_module.default_configure_fn,
        resource_sink=pod_module.default_evidence_sink,
    )
    monkeypatch.setattr(pod_module, "pod_graph", tee_graph)

    # The orchestrator is the PRODUCTION actor (`decide_routing=None`); the
    # factory only wraps the real instance to count its turns. With Langfuse
    # unconfigured (this environment) the reasoning is not traced, so a turn
    # count is the only external evidence available - this is what it measures.
    actors: list = []
    turns: list[dict] = []

    def orchestrator_factory(run_id_for_actor: str):
        actor = ReconOrchestratorActor(run_id=run_id_for_actor)
        actors.append(actor)
        original = actor.decide_routing

        async def counted(signals, phase_jobs):
            turns.append({"signals": len(signals), "phase_jobs": list(phase_jobs)})
            return await original(signals, phase_jobs)

        monkeypatch.setattr(actor, "decide_routing", counted, raising=False)
        return actor

    signal_reads: list[int] = []

    def read_signals(project_id_for_read: str):
        signals = pipeline.read_steering_signals(project_id_for_read)
        signal_reads.append(len(signals))
        return signals

    async def _drive() -> bool:
        task = asyncio.create_task(
            pipeline.run_pipeline(
                project_id,
                run_id=run_id,
                job_subset=CRAWL_SUBSET,
                with_analysis=False,          # recon-only dispatch
                orchestrator_factory=orchestrator_factory,
                read_steering_signals=read_signals,
            )
        )
        done, _pending = await asyncio.wait({task}, timeout=RUN_TIMEOUT_S)
        if task in done:
            task.result()                     # surface a pipeline exception
            return True
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
        return False

    started = time.monotonic()
    completed = asyncio.run(_drive())
    wall_s = round(time.monotonic() - started, 1)

    if not completed:
        # The in-process driver is not registered in the agent's module runtime,
        # so the API stop route cannot reach it (it would 404). Report what the
        # route said, cancel (already done), and fail with the cause.
        stop_status, stop_payload = _api("POST", f"/projects/{project_id}/recon/{run_id}/stop")
        pytest.fail(
            f"the crawl run did not reach a terminal state within {RUN_TIMEOUT_S}s "
            f"(wall {wall_s}s). POST /recon/{{run_id}}/stop -> HTTP {stop_status} "
            f"{json.dumps(stop_payload)[:200]} (expected 404: this in-process run is "
            "not in the module runtime); the task was cancelled instead. "
            f"tool log: {tool_log.log_path}",
            pytrace=False,
        )

    # --- Status, per-job table, no analysis ---------------------------------
    _status_code, run = _api("GET", f"/projects/{project_id}/recon/{run_id}")
    per_job = run.get("per_job") or []
    jobs_seen = [j["job"] for j in per_job]
    summary = {
        "project_id": project_id,
        "project_name": project_name,
        "run_id": run_id,
        "target": TARGET,
        "scope": parse_scope(TARGET),
        "depth": DEPTH,
        "wall_s": wall_s,
        "health": health,
        "lease_preflight": {
            "command": LEASE_PREFLIGHT_COMMAND,
            "returncode": lease.get("returncode"),
            "http_artifact_refs": lease.get("http_artifact_refs"),
            "capture_warning": lease.get("capture_warning"),
        },
        "run": {k: v for k, v in run.items() if k != "per_job"},
        "per_job": per_job,
        "tool_calls": [{k: v for k, v in c.items() if k != "stdout"} for c in tool_log.calls],
        "orchestrator": {
            "actors_built": len(actors),
            "turns": turns,
            "steering_signal_reads": signal_reads,
            "session_thread_resolved": [a._address is not None for a in actors],
        },
    }

    assert run["status"] == "complete", f"run status is {run['status']!r}: {json.dumps(run)[:600]}"

    # Exactly the crawl subset - and nothing from any later phase.
    assert sorted(jobs_seen) == sorted(CRAWL_SUBSET), f"per_job={jobs_seen}"
    for later in LATER_PHASE_JOBS:
        assert later not in jobs_seen, f"job {later!r} ran although only the crawl phase was selected"

    # The §2.1 symptom (degraded/skipped) is a FAILURE of the fix, not an outcome.
    for job in per_job:
        assert job["status"] not in {"degraded", "skipped", "failed"}, (
            f"{job['job']} came back {job['status']!r} - the lease/tool resolution is "
            f"still broken. error={job.get('error')!r} stats={json.dumps(job.get('stats') or {})[:400]}"
        )
        assert job["status"] == "success", job

    # No analysis was started for this run: no row, and the API route 404s.
    analysis_status, analysis_payload = _api("GET", f"/projects/{project_id}/analysis/{run_id}")
    assert analysis_status == 404, (analysis_status, analysis_payload)
    import psycopg

    with psycopg.connect(LIVE_POSTGRES_DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analysis_runs WHERE run_id = %s", (run_id,))
        analysis_rows = cur.fetchone()[0]
    assert analysis_rows == 0, f"{analysis_rows} analysis_runs rows exist for a recon-only dispatch"
    summary["analysis_runs_rows"] = analysis_rows

    # --- The katana command, byte-compared against production ----------------
    katana_calls = [c for c in tool_log.calls if c["job"] == "katana"]
    assert katana_calls, "the katana pod never invoked the exec seam"
    command_evidence = _assert_katana_command(katana_calls[0], _production_template())
    summary["katana_command"] = {
        **command_evidence,
        "command": katana_calls[0]["command"],
        "returncode": katana_calls[0]["returncode"],
        "duration_ms": katana_calls[0]["duration_ms"],
        "capture_state": katana_calls[0]["capture_state"],
        "http_artifact_refs": katana_calls[0]["http_artifact_refs"],
    }
    for call in tool_log.calls:
        assert call["returncode"] == 0, (
            f"{call['job']} exited {call['returncode']}: {call['stderr'][:300]!r}"
        )
        assert call["duration_ms"] < 300_000, f"{call['job']} took {call['duration_ms']}ms"

    # --- D/E. Tool log vs collected -----------------------------------------
    graph_status, graph = _api("GET", f"/projects/{project_id}/graph")
    assert graph_status == 200, (graph_status, graph)
    report = _build_delta_report(run_dir, tool_log, project_id, graph)
    summary["delta_report"] = {k: v for k, v in report.items() if not k.startswith("_")}

    # PG cross-check: the persisted per-job stats must agree with what we logged
    # and parsed. A divergence is a failure WITH the numbers, never a warning.
    katana_stats = next(j for j in per_job if j["job"] == "katana")["stats"] or {}
    stats_check = {
        "pods": katana_stats.get("pods"),
        "consumed": katana_stats.get("consumed"),
        "produced_assets": katana_stats.get("produced_assets"),
        "exec_seconds": katana_stats.get("exec_seconds"),
        "commands_match_tool_log": katana_stats.get("commands") == [c["command"] for c in katana_calls],
        "parsed_kept_deltas": report["gate_kept"],
    }
    summary["katana_pg_stats"] = stats_check

    _write_json(run_dir / "collected.json", {
        "collected_source_katana": report["collected_source_katana"],
        "collected_by_label": report["collected_by_label"],
        "kept_by_label": report["kept_by_label"],
        "nodes_total": len(graph.get("nodes") or []),
        "collected_nodes": [
            {"type": n.get("type"), "name": n.get("name"), "properties": n.get("properties")}
            for n in (graph.get("nodes") or [])
            if (n.get("properties") or {}).get("source") == "katana"
        ],
    })
    _write_delta_report_md(run_dir / "delta-report.md", report, EXPECTED_RENDER)
    _write_json(run_dir / "run-summary.json", summary)

    assert not report["unattributed_drops"], (
        f"the gate dropped deltas no rule here can explain: {report['unattributed_drops']}"
    )
    # The gate is proven live on THIS scope by a positive control before the
    # zero-drop verdict is trusted (see the report's "Gate control" section).
    control = report["gate_control"]
    assert control["kept"] == [], (
        "the curator gate kept the known-droppable control deltas, so its verdict on "
        f"the real tool log cannot be trusted: {control}"
    )
    assert control["dropped_rules"] == ["out_of_scope_host", "static_presentational_endpoint"], control
    if report["gate_dropped"] == 0:
        observed = report["observed"]
        assert not observed["static_classified_endpoints"], observed
        assert not observed["out_of_scope_hosts"], observed
        assert not observed["www_prefixed_hosts"], observed
        assert not observed["malformed_concat_paths"], observed
    assert not report["unexplained_collected"], (
        f"nodes carry source=katana with no provenance in the tool log: "
        f"{[_delta_key_like(n) for n in report['_unexplained_collected']]}"
    )
    assert not report["unexplained_kept"], (
        f"the gate kept deltas that never reached the graph: {report['unexplained_kept']}"
    )
    assert not report["collected_but_dropped_by_gate"], (
        "nodes appear in the graph although the gate dropped the matching delta: "
        f"{[_delta_key_like(n) for n in report['_collected_but_dropped']]}"
    )
    assert report["delta_total"] >= 2, (
        f"the tool log parsed to {report['delta_total']} deltas - a crawl of a live "
        "target must at least mint a BaseURL and the root Endpoint"
    )
    assert stats_check["commands_match_tool_log"], (
        f"recon_jobs.stats.commands disagrees with the tool log: {katana_stats.get('commands')!r}"
    )
    assert stats_check["produced_assets"] == report["gate_kept"], (
        f"katana's persisted produced_assets={stats_check['produced_assets']} but "
        f"{report['gate_kept']} deltas passed the gate: {stats_check}"
    )
    assert stats_check["pods"] == len(katana_calls), stats_check
    assert (stats_check["exec_seconds"] or 0) > 0, stats_check

    # --- Orchestrator: constructed, and how many steering turns it took ------
    assert len(actors) == 1, f"{len(actors)} orchestrator actors were built for one run"
    assert actors[0]._run_id == run_id
    # On this target there are NO WAF steering signals, so the gate upstream of
    # the actor (`if not signals: return {}`) short-circuits: the actor is built
    # but never receives a turn. The reasoning is NOT traced (Langfuse is
    # unconfigured here), so this is stated as exactly what it is.
    assert all(count == 0 for count in signal_reads), (
        f"steering signals were observed on a target with no WAF observations: {signal_reads}"
    )
    assert turns == [], f"the orchestrator took {len(turns)} steering turns: {turns}"
    assert actors[0]._address is None, (
        "the actor resolved its session thread, so it did more than get constructed"
    )
    summary["orchestrator"]["verdict"] = (
        "started, no steering signal to act on"
    )
    _write_json(run_dir / "run-summary.json", summary)

    print("\n=== crawl-only E2E summary ===", flush=True)
    print(f"project={project_id} run={run_id} wall={wall_s}s", flush=True)
    print(f"jobs={[(j['job'], j['status'], j['phase']) for j in per_job]}", flush=True)
    print(f"katana command: {katana_calls[0]['command']}", flush=True)
    print(f"delta: total={report['delta_total']} kept={report['gate_kept']} "
          f"dropped={report['gate_dropped']} collected={report['collected_source_katana']} "
          f"unexplained={len(report['unexplained_kept']) + len(report['unexplained_collected'])}", flush=True)
    print(f"gate control: kept={control['kept']} rules_fired={control['dropped_rules']}", flush=True)
    print(f"orchestrator: actor built={len(actors)} turns={len(turns)} "
          f"steering_signal_reads={signal_reads}", flush=True)
    print(f"artifacts: {run_dir}", flush=True)
