# Recon Pipeline - Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the recon-pod substrate so one real recon job (httpx HTTP probe) runs end-to-end - deterministic configurator -> `execute_command` -> returncode gate -> deterministic parser -> LLM triager -> deterministic curator - and writes typed Layer-0 assets to Neo4j.

**Architecture:** A LangGraph pod subgraph parameterised by a `JobSpec`. Deterministic nodes (configurator template-fill, gate, parser, curator) plus one LLM node (triager) that only adds observations. Tool output is parsed into `AssetDelta`s by vendored-from-Redamon per-tool parsers; a single generic curator MERGEs them. LLM roles resolve through a provider registry over OpenAI-compatible endpoints with fail-fast bootstrap validation.

**Tech Stack:** Python 3.11 (base image `redamon-agent`), LangGraph, `langchain-openai==1.3.2` (`ChatOpenAI` over OpenAI-compatible base URLs), `langchain-mcp-adapters` (kali `execute_command`), `neo4j` driver, pytest 8.3.4.

## Global Constraints

- Target the `redamon-agent` base image's Python 3.11; do not add new heavy deps - `langchain-openai`, `openai`, `langchain-core`, `langgraph`, `langchain-mcp-adapters`, `neo4j`, `pydantic` are already present.
- Neo4j identity keys carry `project_id`, never `user_id` (Phase-1 constraints in `db/neo4j/schema.py` already drop `user_id`). Every node gets `project_id`, `first_seen`, `last_seen`; `first_seen` only `ON CREATE`.
- All graph writes are parameterised `MERGE` via `agent/app/clients/neo4j_client.py::merge`. No f-string interpolation of values into Cypher.
- LLM config is env-driven: per role `LLM_MODEL_<ROLE>` = `"<provider>:<model>"`; keys are `API_KEY_<PROVIDER>` (uppercased provider). Bootstrap MUST tear down the app if any referenced provider is unknown or its key is missing.
- Providers are OpenAI-compatible; known base URLs: `openai` -> `https://api.openai.com/v1`, `openrouter` -> `https://openrouter.ai/api/v1`, `swissai` -> `https://api.swissai.svc.cscs.ch/v1` (verify exact path at build via the swissai docs; keep it in one registry constant).
- `execute_command(command, session_id, timeout_s=300) -> {stdout, stderr, returncode, duration_ms}`; timeout maps to `returncode==124`. Never re-derive this contract.
- Configurator is deterministic on iteration 1 (template placeholder fill only); an LLM configurator is out of scope for foundation. Pod loop bounded by `MAX_POD_ITERS` (default 3).
- Tests run from repo root with `pytest`; unit tests must not require live Neo4j/Kali (mock the clients). Package dirs need `__init__.py`.

---

### Task 1: LLM provider layer + fail-fast bootstrap validation

**Files:**
- Create: `agent/app/llm/__init__.py`
- Create: `agent/app/llm/providers.py`
- Create: `agent/app/llm/roles.py`
- Modify: `agent/app/main.py` (call `validate_llm_config()` in `_startup`, before returning)
- Test: `tests/test_llm_providers.py`

**Interfaces:**
- Produces:
  - `PROVIDERS: dict[str, str]` - provider name -> base URL.
  - `build_chat_model(provider: str, model: str, *, temperature: float = 0) -> ChatOpenAI`
  - `ROLES: tuple[str, ...] = ("configurator", "triager", "job_orchestrator")`
  - `resolve_role(role: str) -> tuple[str, str]` - reads `LLM_MODEL_<ROLE>`, returns `(provider, model)`.
  - `validate_llm_config() -> None` - raises `LLMConfigError` if any role's provider is unknown or `API_KEY_<PROVIDER>` is unset.
  - `class LLMConfigError(RuntimeError)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers.py
import pytest
from agent.app.llm import providers as P

def test_known_providers_have_base_urls():
    assert P.PROVIDERS["openai"].startswith("https://")
    assert "openrouter" in P.PROVIDERS
    assert "swissai" in P.PROVIDERS

def test_resolve_role_parses_provider_and_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:anthropic/claude-3.5-sonnet")
    assert P.resolve_role("triager") == ("openrouter", "anthropic/claude-3.5-sonnet")

def test_validate_raises_when_key_missing(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")
    monkeypatch.setenv("LLM_MODEL_CONFIGURATOR", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_JOB_ORCHESTRATOR", "openai:gpt-4o")
    monkeypatch.delenv("API_KEY_OPENROUTER", raising=False)
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config()
    assert "OPENROUTER" in str(e.value)

def test_validate_raises_on_unknown_provider(monkeypatch):
    for r in ("TRIAGER", "CONFIGURATOR", "JOB_ORCHESTRATOR"):
        monkeypatch.setenv(f"LLM_MODEL_{r}", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "bogus:model")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError):
        P.validate_llm_config()

def test_validate_passes_when_all_present(monkeypatch):
    for r in ("TRIAGER", "CONFIGURATOR", "JOB_ORCHESTRATOR"):
        monkeypatch.setenv(f"LLM_MODEL_{r}", "swissai:meta-llama/Llama-3.3-70B-Instruct")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # no raise

def test_build_chat_model_sets_base_url_and_key(monkeypatch):
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "meta-llama/Llama-3.3-70B-Instruct")
    assert str(m.openai_api_base) == P.PROVIDERS["swissai"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_llm_providers.py -v`
Expected: FAIL (module `agent.app.llm.providers` not found).

- [ ] **Step 3: Implement the provider layer**

```python
# agent/app/llm/providers.py
import os
from langchain_openai import ChatOpenAI

class LLMConfigError(RuntimeError):
    """Raised at bootstrap when an agent role references a provider/model
    whose base URL or API key is absent from the system context."""

PROVIDERS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "swissai":    "https://api.swissai.svc.cscs.ch/v1",
}

ROLES: tuple[str, ...] = ("configurator", "triager", "job_orchestrator")

def _key_env(provider: str) -> str:
    return f"API_KEY_{provider.upper()}"

def resolve_role(role: str) -> tuple[str, str]:
    raw = os.environ.get(f"LLM_MODEL_{role.upper()}")
    if not raw or ":" not in raw:
        raise LLMConfigError(
            f"LLM_MODEL_{role.upper()} must be set to '<provider>:<model>' (got {raw!r})"
        )
    provider, model = raw.split(":", 1)
    return provider.strip(), model.strip()

def build_chat_model(provider: str, model: str, *, temperature: float = 0) -> ChatOpenAI:
    if provider not in PROVIDERS:
        raise LLMConfigError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    api_key = os.environ.get(_key_env(provider))
    if not api_key:
        raise LLMConfigError(f"missing {_key_env(provider)} for provider {provider!r}")
    return ChatOpenAI(model=model, api_key=api_key,
                      base_url=PROVIDERS[provider], temperature=temperature)

def validate_llm_config() -> None:
    """Fail fast: every configured role must name a known provider with a present key."""
    problems: list[str] = []
    for role in ROLES:
        try:
            provider, _model = resolve_role(role)
        except LLMConfigError as e:
            problems.append(str(e)); continue
        if provider not in PROVIDERS:
            problems.append(f"role {role}: unknown provider {provider!r}")
        elif not os.environ.get(_key_env(provider)):
            problems.append(f"role {role}: missing {_key_env(provider)}")
    if problems:
        raise LLMConfigError("LLM configuration invalid:\n  - " + "\n  - ".join(problems))
```

```python
# agent/app/llm/roles.py
from agent.app.llm.providers import resolve_role, build_chat_model

def chat_model_for(role: str, *, temperature: float = 0):
    """Build the ChatOpenAI configured for an agent role (configurator/triager/job_orchestrator)."""
    provider, model = resolve_role(role)
    return build_chat_model(provider, model, temperature=temperature)
```

```python
# agent/app/llm/__init__.py
from agent.app.llm.providers import (  # noqa: F401
    PROVIDERS, ROLES, LLMConfigError,
    resolve_role, build_chat_model, validate_llm_config,
)
```

- [ ] **Step 4: Wire fail-fast into startup**

Modify `agent/app/main.py` `_startup` to add, after the existing setup calls:

```python
from agent.app.llm import validate_llm_config
# inside _startup(), after neo4j_client.ensure_schema():
    validate_llm_config()
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_llm_providers.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add agent/app/llm tests/test_llm_providers.py agent/app/main.py
git commit -m "feat(recon): LLM provider layer + fail-fast bootstrap validation"
```

---

### Task 2: Core recon types (state + payload contracts)

**Files:**
- Create: `agent/recon/__init__.py`
- Create: `agent/recon/types.py`
- Test: `tests/recon/__init__.py`, `tests/recon/test_types.py`

**Interfaces:**
- Produces (all `pydantic.BaseModel` unless noted; these are the contracts every later task consumes):
  - `Edge(rel: str, dir: Literal["in","out"], node_type: str, node_identity: dict)`
  - `AssetDelta(type: str, identity: dict, props: dict = {}, edges: list[Edge] = [])`
  - `Observation(macro_kind: str, severity: str, evidence: str, rationale: str, anchor: dict, source_job: str, source_tool: str)` - `anchor` = `{"type": str, "identity": dict}`
  - `ExecResult(stdout: str, stderr: str, returncode: int, duration_ms: int)`
  - `ToolInvocation(command: str, session_id: str)`
  - `JobSpec(tool: str, skill: str, command_template: str, produces: list[str], consumes: str, use_auth: bool = False, configurator_mode: Literal["deterministic","agent"] = "deterministic", eval_criteria: str = "returncode_zero_nonempty")`
  - `PodExport(input_asset: dict, verdict: Literal["success","failed"], assets_merged: int, observations_merged: int, iterations: int, error: str | None = None)`
  - `PodState(TypedDict, total=False)` and `ReconState(TypedDict, total=False)` per design §10.1, with `pod_exports: Annotated[list[PodExport], operator.add]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/recon/test_types.py
from agent.recon.types import AssetDelta, Edge, Observation, JobSpec, ExecResult

def test_asset_delta_with_edge_roundtrips():
    d = AssetDelta(
        type="Endpoint",
        identity={"path": "/api/v1/users", "method": "GET", "baseurl": "https://app.example.com"},
        props={"status_code": 200},
        edges=[Edge(rel="HAS_ENDPOINT", dir="in", node_type="BaseURL",
                    node_identity={"url": "https://app.example.com"})],
    )
    assert d.type == "Endpoint"
    assert d.edges[0].node_type == "BaseURL"

def test_jobspec_defaults():
    j = JobSpec(tool="httpx", skill="http_probe",
                command_template="httpx -u {target} -j", produces=["BaseURL","Endpoint"],
                consumes="Subdomain")
    assert j.use_auth is False
    assert j.configurator_mode == "deterministic"

def test_exec_result_fields():
    r = ExecResult(stdout="x", stderr="", returncode=0, duration_ms=5)
    assert r.returncode == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/recon/test_types.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `agent/recon/types.py`**

```python
# agent/recon/types.py
import operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field

class Edge(BaseModel):
    rel: str
    dir: Literal["in", "out"]
    node_type: str
    node_identity: dict

class AssetDelta(BaseModel):
    type: str
    identity: dict
    props: dict = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

class Observation(BaseModel):
    macro_kind: str
    severity: str
    evidence: str
    rationale: str
    anchor: dict            # {"type": str, "identity": dict}
    source_job: str
    source_tool: str

class ExecResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int = 0

class ToolInvocation(BaseModel):
    command: str
    session_id: str

class JobSpec(BaseModel):
    tool: str
    skill: str
    command_template: str
    produces: list[str]
    consumes: str
    use_auth: bool = False
    configurator_mode: Literal["deterministic", "agent"] = "deterministic"
    eval_criteria: str = "returncode_zero_nonempty"

class PodExport(BaseModel):
    input_asset: dict
    verdict: Literal["success", "failed"]
    assets_merged: int = 0
    observations_merged: int = 0
    iterations: int = 0
    error: str | None = None

class PodState(TypedDict, total=False):
    job: JobSpec
    input_asset: dict
    asset_context: str
    extra: dict
    session_id: str
    invocation: ToolInvocation
    exec_result: ExecResult
    iteration: int
    assets: list[AssetDelta]
    observations: list[Observation]
    export: PodExport

class ReconState(TypedDict, total=False):
    run_id: str
    project_id: str
    settings: dict
    phase_plan: list[dict]
    current_phase: int
    pod_exports: Annotated[list[PodExport], operator.add]
    status: str
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/recon/test_types.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/recon/__init__.py agent/recon/types.py tests/recon/
git commit -m "feat(recon): core state + payload contract types"
```

---

### Task 3: Generic curator (AssetDelta + Observation -> Neo4j MERGE)

**Files:**
- Create: `agent/recon/curator.py`
- Test: `tests/recon/test_curator.py`

**Interfaces:**
- Consumes: `AssetDelta`, `Edge`, `Observation` (Task 2); `agent/app/clients/neo4j_client.py::merge(cypher, params)`.
- Produces:
  - `build_asset_cypher(delta: AssetDelta) -> tuple[str, dict]` - pure; returns parameterised MERGE + params (adds `project_id`; `first_seen` ON CREATE, `last_seen` always; edges MERGE by identity).
  - `build_observation_cypher(obs: Observation) -> tuple[str, dict]` - pure; MERGE anchor + Observation with generated `id`, `observed_at`, `project_id`.
  - `curate(assets: list[AssetDelta], observations: list[Observation], project_id: str, *, merge_fn=neo4j_client.merge) -> tuple[int, int]` - executes each; returns `(assets_merged, observations_merged)`; a single delta rejection logs and continues (per §10.6).

**Design notes for the implementer:**
- Identity props form the MERGE key; `props` go into `SET n += $props`. Keep identity keys and `project_id` in the MERGE pattern, everything else in `+= $props`.
- Build the node label and identity Cypher from `delta.type` and `sorted(delta.identity)` deterministically. Validate `delta.type` against the allowed label set (import node labels from `db/neo4j/schema.py` if it exposes them; otherwise define `ALLOWED_LABELS` here matching design §10.3) and raise `ValueError` for unknown labels so `curate` can skip+log.
- For each edge, MERGE the far node by its `node_identity` (+ `project_id`) as a thin node of `node_type`, then MERGE the relationship in the stated direction.
- Observation anchors are restricted to the broad-anchor allowlist `{"Domain","Subdomain","BaseURL","IP","Service"}`; reject others.
- `id` for an Observation is deterministic: `sha1(f"{macro_kind}|{evidence}|{anchor}|{source_tool}")` hex, so re-runs are idempotent.

- [ ] **Step 1: Write the failing tests**

```python
# tests/recon/test_curator.py
from agent.recon.types import AssetDelta, Edge, Observation
from agent.recon import curator

def test_asset_cypher_merges_on_identity_plus_project():
    d = AssetDelta(type="Endpoint",
                   identity={"path": "/x", "method": "GET", "baseurl": "https://a"},
                   props={"status_code": 200})
    cy, params = curator.build_asset_cypher(d)
    assert "MERGE" in cy and ":Endpoint" in cy
    assert "first_seen" in cy and "last_seen" in cy
    assert params["project_id"]  # injected by caller path; see curate()
    assert params["status_code"] == 200

def test_unknown_label_rejected():
    import pytest
    d = AssetDelta(type="Bogus", identity={"x": 1})
    with pytest.raises(ValueError):
        curator.build_asset_cypher(d)

def test_observation_anchor_allowlist_enforced():
    import pytest
    o = Observation(macro_kind="auth_surface", severity="info", evidence="e",
                    rationale="r", anchor={"type": "Parameter", "identity": {"name": "q"}},
                    source_job="j", source_tool="t")
    with pytest.raises(ValueError):
        curator.build_observation_cypher(o)

def test_curate_counts_and_skips_bad_delta():
    calls = []
    def fake_merge(cy, params): calls.append((cy, params))
    good = AssetDelta(type="BaseURL", identity={"url": "https://a"})
    bad = AssetDelta(type="Nope", identity={"x": 1})
    a, o = curator.curate([good, bad], [], "proj1", merge_fn=fake_merge)
    assert a == 1 and o == 0
    assert len(calls) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/recon/test_curator.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `agent/recon/curator.py`**

Implement per the design notes above. `build_asset_cypher`/`build_observation_cypher` are pure and take `project_id` via a param dict the caller fills; in `curate`, inject `project_id` into every params dict before calling `merge_fn`. Log rejections with `logging.getLogger(__name__)` and continue. Use `datetime()` in Cypher for `first_seen`/`last_seen`/`observed_at`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/recon/test_curator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/recon/curator.py tests/recon/test_curator.py
git commit -m "feat(recon): generic AssetDelta/Observation curator (parameterised MERGE, no user_id)"
```

---

### Task 4: Reference parser - httpx stdout -> AssetDeltas

**Files:**
- Create: `agent/recon/parsers/__init__.py`
- Create: `agent/recon/parsers/httpx_parser.py`
- Create: `tests/recon/fixtures/httpx_probe.jsonl`
- Test: `tests/recon/test_httpx_parser.py`

**Interfaces:**
- Consumes: `AssetDelta`, `Edge` (Task 2).
- Produces:
  - `agent/recon/parsers/httpx_parser.py::parse(stdout: str) -> list[AssetDelta]`
  - `agent/recon/parsers/__init__.py::PARSERS: dict[str, Callable[[str], list[AssetDelta]]]` with `"httpx"` registered, and `get_parser(tool: str)`.

**Port source (read before implementing):** `redamon-recon:/app/recon/main_recon_modules/http_probe.py::parse_httpx_output` (and its header-normalisation helper `_annotate_ai_http_signals` for field names). Extract the field mapping only; drop all Docker/execution/AI-annotation code. Preserve the exception handling: skip malformed JSONL lines, tolerate missing keys.

**Mapping (httpx `-json` line -> deltas):**
- `BaseURL` identity `{url}` from the probed `url`/`input`; props `scheme, host, status_code (status_code), title, content_type (content_type), final_url (final_url|url), server (webserver)`.
- One `Endpoint` identity `{path, method:"GET", baseurl}` with edge `HAS_ENDPOINT` dir `in` from `BaseURL {url}`; props `status_code, content_type, content_length, title, server, source:"http_probe"`.
- For each `tech` in httpx `tech`/`technologies`: `Technology` identity `{name, version}` (version may be `""`) with edge `USES_TECHNOLOGY` dir `in` from `BaseURL`.
- If a TLS block is present (`tls.subject_cn`): `Certificate` identity `{subject_cn}` with `issuer, san, not_before, not_after`; edge `HAS_CERTIFICATE` dir `in` from `BaseURL`.

- [ ] **Step 1: Create the fixture** `tests/recon/fixtures/httpx_probe.jsonl` (two real httpx `-json` lines):

```json
{"timestamp":"2026-07-03T10:00:00Z","url":"https://app.example.com","input":"app.example.com","status_code":200,"title":"Example App","webserver":"nginx","content_type":"text/html","content_length":1024,"final_url":"https://app.example.com/","scheme":"https","host":"93.184.216.34","tech":["nginx","React"],"tls":{"subject_cn":"app.example.com","issuer_dn":"CN=R3","not_before":"2026-01-01T00:00:00Z","not_after":"2026-04-01T00:00:00Z","subject_an":["app.example.com"]}}
{"timestamp":"2026-07-03T10:00:01Z","url":"https://api.example.com","input":"api.example.com","status_code":403,"title":"","webserver":"cloudflare","content_type":"application/json","content_length":57,"final_url":"https://api.example.com","scheme":"https","host":"104.16.0.1","tech":["cloudflare"]}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/recon/test_httpx_parser.py
from pathlib import Path
from agent.recon.parsers import get_parser
from agent.recon.parsers.httpx_parser import parse

FIX = Path(__file__).parent / "fixtures" / "httpx_probe.jsonl"

def test_registry_exposes_httpx():
    assert get_parser("httpx") is parse

def test_parse_emits_baseurl_endpoint_tech_cert():
    deltas = parse(FIX.read_text())
    types = [d.type for d in deltas]
    assert types.count("BaseURL") == 2
    assert "Endpoint" in types
    tech = [d for d in deltas if d.type == "Technology"]
    assert {("nginx"), ("React"), ("cloudflare")} <= {d.identity["name"] for d in tech}
    cert = [d for d in deltas if d.type == "Certificate"]
    assert cert and cert[0].identity["subject_cn"] == "app.example.com"

def test_endpoint_has_incoming_baseurl_edge():
    deltas = parse(FIX.read_text())
    ep = next(d for d in deltas if d.type == "Endpoint")
    assert any(e.rel == "HAS_ENDPOINT" and e.node_type == "BaseURL" for e in ep.edges)

def test_malformed_line_skipped():
    deltas = parse('{"url":"https://a","status_code":200}\nNOT JSON\n')
    assert any(d.type == "BaseURL" for d in deltas)
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/recon/test_httpx_parser.py -v`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement `httpx_parser.py` + `parsers/__init__.py`**

Port the field mapping from the source function; iterate JSONL lines with a per-line `try/except json.JSONDecodeError: continue`. Build deltas per the mapping table above. Register in `PARSERS = {"httpx": parse}` with `def get_parser(tool): return PARSERS[tool]`.

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/recon/test_httpx_parser.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/recon/parsers tests/recon/test_httpx_parser.py tests/recon/fixtures/httpx_probe.jsonl
git commit -m "feat(recon): httpx parser (stdout -> AssetDeltas) + parser registry"
```

---

### Task 5: Recon pod subgraph (end-to-end for the httpx job)

**Files:**
- Create: `agent/recon/pod.py`
- Create: `agent/recon/config.py` (pod-loop settings from env)
- Test: `tests/recon/test_pod.py`

**Interfaces:**
- Consumes: `JobSpec`, `PodState`, `ExecResult`, `ToolInvocation`, `AssetDelta`, `Observation`, `PodExport` (Task 2); `get_parser` (Task 4); `curate` (Task 3); `chat_model_for` (Task 1); kali client `execute_command`.
- Produces:
  - `agent/recon/config.py::MAX_POD_ITERS: int` (env `MAX_POD_ITERS`, default 3), `EXEC_TIMEOUT_S: int` (env, default 300).
  - `agent/recon/pod.py::build_pod_graph(*, exec_fn, curate_fn, triage_fn) -> CompiledGraph` - dependency-injected for testability; a `default_exec_fn`, `default_triage_fn` wire the real kali client and triager LLM.
  - `agent/recon/pod.py::fill_template(command_template: str, input_asset: dict, extra: dict) -> str` - deterministic placeholder fill (`{target}`, `{domain}`, `{baseurl}`, `{auth_header}`; `{auth_header}` empty unless `extra["auth_context"]` present and `job.use_auth`).

**Node behaviour (per design §3 / §10.1):**
- `configurator` (deterministic): `invocation = ToolInvocation(command=fill_template(...), session_id=state["session_id"])`; bump `iteration`.
- `execute`: `exec_result = exec_fn(invocation.command, invocation.session_id, EXEC_TIMEOUT_S)`.
- gate (conditional edge): `returncode==0 and stdout.strip()` -> `"parse"`; `returncode!=0 and iteration<MAX_POD_ITERS` -> `"configurator"`; else -> `"fail"`.
- `parser` (deterministic): `assets = get_parser(job.tool)(exec_result.stdout)`.
- `triager` (LLM): `observations = triage_fn(exec_result, assets, job)`; must return `list[Observation]` (may be empty).
- `curator` (deterministic): `merged = curate_fn(assets, observations, project_id)`; set `export = PodExport(verdict="success", ...)`.
- `fail`: `export = PodExport(verdict="failed", assets_merged=0, ..., error=...)`.

- [ ] **Step 1: Write the failing test** (fully mocked - no live services)

```python
# tests/recon/test_pod.py
from agent.recon.types import JobSpec, ExecResult, Observation
from agent.recon import pod

HTTPX_JOB = JobSpec(tool="httpx", skill="http_probe",
                    command_template="httpx -u {target} -json -silent",
                    produces=["BaseURL", "Endpoint"], consumes="Subdomain")

FIX_LINE = '{"url":"https://app.example.com","input":"app.example.com","status_code":200,"scheme":"https","host":"1.2.3.4","tech":["nginx"]}'

def test_fill_template_substitutes_target():
    cmd = pod.fill_template("httpx -u {target} -json", {"name": "app.example.com"}, {})
    assert "app.example.com" in cmd

def test_pod_happy_path_success():
    captured = {}
    def exec_fn(cmd, sid, t): return ExecResult(stdout=FIX_LINE, stderr="", returncode=0, duration_ms=3)
    def curate_fn(assets, obs, pid): captured["n"] = len(assets); return (len(assets), len(obs))
    def triage_fn(er, assets, job): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "app.example.com"},
                    "asset_context": "", "extra": {}, "session_id": "run-pod1",
                    "iteration": 0, "project_id": "proj1"})
    assert out["export"].verdict == "success"
    assert captured["n"] >= 1

def test_pod_retries_then_fails_on_nonzero():
    attempts = {"n": 0}
    def exec_fn(cmd, sid, t):
        attempts["n"] += 1
        return ExecResult(stdout="", stderr="boom", returncode=1, duration_ms=1)
    def curate_fn(a, o, p): return (0, 0)
    def triage_fn(er, a, j): return []
    g = pod.build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=triage_fn)
    out = g.invoke({"job": HTTPX_JOB, "input_asset": {"name": "x"}, "asset_context": "",
                    "extra": {}, "session_id": "s", "iteration": 0, "project_id": "p"})
    assert out["export"].verdict == "failed"
    assert attempts["n"] >= 2  # retried
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/recon/test_pod.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `agent/recon/config.py` and `agent/recon/pod.py`**

Build the subgraph with `langgraph.graph.StateGraph(PodState)`. Nodes and the conditional gate as specified. `build_pod_graph` takes `exec_fn`, `curate_fn`, `triage_fn` for injection and returns `graph.compile()`. Provide module-level `default_exec_fn` (calls kali `execute_command` via `langchain_mcp_adapters`), `default_triage_fn` (uses `chat_model_for("triager")` with structured output to `list[Observation]`), and a `pod_graph` built from defaults. Guard the loop with `iteration` and `MAX_POD_ITERS`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/recon/test_pod.py -v`
Expected: PASS.

- [ ] **Step 5: Full foundation test sweep + commit**

Run: `pytest tests/test_llm_providers.py tests/recon -v`
Expected: all PASS.

```bash
git add agent/recon/pod.py agent/recon/config.py tests/recon/test_pod.py
git commit -m "feat(recon): pod subgraph - deterministic configurator/gate/parser/curator + triager, httpx end-to-end"
```

---

## Self-Review (author checklist, completed)

- **Spec coverage:** LLM fail-fast (Q5) -> Task 1; AssetDelta/curator split (D4) -> Tasks 2-3; deterministic-first configurator (Q2) -> Task 5 `fill_template`; one parser vendored faithfully (D4) -> Task 4. Parser fleet, orchestration, agentic crawl, on-demand nuclei are explicitly deferred to sub-plans 2-5.
- **Placeholder scan:** port task (4) names the exact source function + a concrete fixture + expected deltas rather than inlining Redamon's code verbatim; curator task (3) gives design notes + full tests. No "TBD"/"handle edge cases" left.
- **Type consistency:** `AssetDelta`, `Edge`, `Observation`, `JobSpec`, `ExecResult`, `PodExport`, `PodState` defined in Task 2 and consumed with the same names/signatures in Tasks 3-5; `curate(assets, observations, project_id, merge_fn=...)`, `get_parser(tool)`, `chat_model_for(role)`, `build_pod_graph(exec_fn, curate_fn, triage_fn)` referenced consistently.
