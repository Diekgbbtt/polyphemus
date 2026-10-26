# L1 projection and prompt fixes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the truncated JSON projection with a coherent Markdown renderer, respecify the threat modeller's spatial axis toward data contracts, and teach the mechanism typist to read status codes canonically before it withholds an L1 link.

**Architecture:** The projection reader gains typed header and parameter slots. A pure renderer turns one `UnitProjection` into a Markdown tree with services, endpoints, parameters, and a separate per-baseURL header list. The modeller prompt uses that renderer without a character cap. The two prompt fixes are text-only and pinned by prompt-contract tests.

**Tech Stack:** Python 3.11, pytest, dataclasses, Neo4j read seam, Markdown prompt files.

---

## Worktree

- Base: `be15666f` (`hunt-enhancement-trunk`).
- Branch: `fix/l1-projection-prompt-fixes`.
- Worktree: `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/l1-projection-prompt-fixes`.
- Do not merge or push without the operator's approval.

## File map

| File | Responsibility |
|---|---|
| `src/polymerhus/attack/hunting/unit_projection.py` | Read the projection, headers, and parameters. |
| `src/polymerhus/attack/hunting/unit_projection_render.py` | New pure Markdown renderer. |
| `src/polymerhus/attack/hunting/llm.py` | Use the renderer for the modeller projection. |
| `src/polymerhus/attack/hunting/prompts/threat-modeller.md` | Replace the spatial-axis bullets. |
| `src/polymerhus/analysis/prompts/technical-system.md` | Add the status-code and reconciliation rules. |
| `tests/attack/test_unit_projection.py` | Header and parameter read tests. |
| `tests/attack/test_unit_projection_render.py` | Renderer tests. |
| `tests/attack/test_hunting_llm.py` | Modeller prompt wiring test. |
| `tests/attack/test_threat_modeller_prompt.py` | Spatial-axis prompt test. |
| `tests/analysis/test_technical_system_prompt.py` | Typist prompt test. |

---

## Task 0: Record the diagnosis

**Files:**
- Create: `docs/experiments/iteration-b-white-jotter-2026-10-25/ROOT-CAUSE-UNIT-DIFF.md`

- [x] **Step 0.1: Write the root-cause report**

The report is written. It contains the red loop, the recon auth-context evidence, the A1 typist edge table, the falsified hypotheses, the inferred limitations, and the fix direction.

- [ ] **Step 0.2: Commit the report**

```bash
git add docs/experiments/iteration-b-white-jotter-2026-10-25/ROOT-CAUSE-UNIT-DIFF.md
git commit -m "docs(experiments): diagnose the RESTApi unit-model divergence"
```

---

## Task 1: Create the fix worktree

**Files:** none.

- [ ] **Step 1.1: Create the worktree**

```bash
cd /Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/utm-hunt-enhancement
git worktree add ../l1-projection-prompt-fixes -b fix/l1-projection-prompt-fixes be15666f
```

- [ ] **Step 1.2: Move the session to the fix worktree**

Call `tools.opencode.session_move` with `directory: "/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/l1-projection-prompt-fixes"`.

- [ ] **Step 1.3: Confirm the baseline**

```bash
pytest tests/attack/test_unit_projection.py tests/attack/test_hunting_llm.py tests/attack/test_threat_modeller_prompt.py tests/analysis/test_technical_system_prompt.py -q
```

Expected: PASS. If the baseline fails, stop and record the failure before any edit.

---

## Task 2: Add typed header and parameter slots to the projection

**Files:**
- Modify: `src/polymerhus/attack/hunting/unit_projection.py`
- Test: `tests/attack/test_unit_projection.py`

- [ ] **Step 2.1: Write the failing header test**

Add to `tests/attack/test_unit_projection.py`:

```python
def test_build_projection_reads_unique_baseurl_headers():
    fake = FakeL1({
        "System:api": {
            "labels": ["L1System"],
            "props": {"kind": "RESTApi", "discriminator": "api"},
            "edges": [],
            "aggregated": [
                {"props": {"method": "GET", "path": "/api/a",
                           "baseurl": "http://t", "slug": "svc"}},
                {"props": {"method": "GET", "path": "/api/b",
                           "baseurl": "http://t", "slug": "svc"}},
            ],
            "headers": [
                {"baseurl": "http://t", "name": "server", "value": "nginx",
                 "direction": "response"},
                {"baseurl": "http://t", "name": "server", "value": "nginx",
                 "direction": "response"},
                {"baseurl": "http://t", "name": "vary", "value": "accept-encoding",
                 "direction": "response"},
            ],
            "params": [],
        },
    })

    projection = _projection("System:api", fake)

    assert projection.baseurl_headers == {
        "http://t": (
            HeaderInfo(name="server", value="nginx", direction="response"),
            HeaderInfo(name="vary", value="accept-encoding", direction="response"),
        ),
    }
```

Add the `HeaderInfo` import.

- [ ] **Step 2.2: Run the test to verify it fails**

```bash
pytest tests/attack/test_unit_projection.py::test_build_projection_reads_unique_baseurl_headers -q
```

Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 2.3: Write the failing parameter test**

Add to `tests/attack/test_unit_projection.py`:

```python
def test_build_projection_reads_endpoint_parameters():
    fake = FakeL1({
        "Service:svc": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "svc"},
            "edges": [],
            "aggregated": [
                {"props": {"method": "GET", "path": "/api/a",
                           "baseurl": "http://t"}},
            ],
            "headers": [],
            "params": [
                {"baseurl": "http://t", "path": "/api/a", "method": "GET",
                 "name": "q", "position": "query"},
            ],
        },
    })

    projection = _projection("Service:svc", fake)

    assert projection.aggregated_endpoints[0].parameters == (
        ParameterInfo(name="q", position="query"),
    )
```

- [ ] **Step 2.4: Run the test to verify it fails**

```bash
pytest tests/attack/test_unit_projection.py::test_build_projection_reads_endpoint_parameters -q
```

Expected: FAIL with `ImportError` or `AttributeError`.

- [ ] **Step 2.5: Add the data structures**

In `src/polymerhus/attack/hunting/unit_projection.py`, add:

```python
@dataclass(frozen=True)
class HeaderInfo:
    """One unique L0 header linked to a BaseURL, deduplicated by name/value/direction."""

    name: str | None = None
    value: str | None = None
    direction: str | None = None


@dataclass(frozen=True)
class ParameterInfo:
    """One L0 Parameter linked to an Endpoint."""

    name: str | None = None
    position: str | None = None
```

Add `parameters: tuple[ParameterInfo, ...] = ()` to `AggregatedEndpoint`.
Add `baseurl_headers: Mapping[str, tuple[HeaderInfo, ...]] = field(default_factory=dict)` to `UnitProjection`.

- [ ] **Step 2.6: Extend the fake read seam**

In `FakeL1.read`, add these branches before the unit read:

```python
if "HAS_HEADER" in cypher:
    return self._header_rows(params)
if "HAS_PARAMETER" in cypher:
    return self._param_rows(params)
```

Add:

```python
def _header_rows(self, params):
    unit_id = f"{params['kind']}:{params['key']}"
    return (self.units.get(unit_id) or {}).get("headers", [])

def _param_rows(self, params):
    unit_id = f"{params['kind']}:{params['key']}"
    return (self.units.get(unit_id) or {}).get("params", [])
```

- [ ] **Step 2.7: Read headers and parameters**

In `build_projection`, after the aggregated endpoints are sorted, add:

```python
baseurls = sorted({e.baseurl for e in aggregated_endpoints if e.baseurl})
params_by_endpoint: dict[tuple, list[ParameterInfo]] = {}
if baseurls:
    try:
        param_rows = read_fn(
            "MATCH (e:Endpoint {project_id:$project_id})-[:HAS_PARAMETER]->(p:Parameter) "
            "WHERE e.baseurl IN $baseurls "
            "RETURN e.baseurl AS baseurl, e.path AS path, e.method AS method, "
            "p.name AS name, p.position AS position "
            "ORDER BY baseurl, path, method, name, position",
            {"project_id": project_id, "baseurls": baseurls},
        )
        for row in param_rows:
            key = (row.get("baseurl"), row.get("path"), row.get("method"))
            params_by_endpoint.setdefault(key, []).append(
                ParameterInfo(name=row.get("name"), position=row.get("position")))
    except Exception as exc:  # noqa: BLE001 - degrade only this slot
        diagnostics.append(f"parameters read degraded: {exc}")

aggregated_endpoints = [
    replace(e, parameters=tuple(params_by_endpoint.get(
        (e.baseurl, e.path, e.method), ())))
    for e in aggregated_endpoints
]
```

Use `from dataclasses import replace`.

Add the header read:

```python
baseurl_headers: dict[str, list[HeaderInfo]] = {}
if baseurls:
    try:
        header_rows = read_fn(
            "MATCH (b:BaseURL {project_id:$project_id})-[:HAS_HEADER]->(h:Header) "
            "WHERE b.url IN $baseurls "
            "RETURN b.url AS baseurl, h.name AS name, h.value AS value, "
            "h.direction AS direction "
            "UNION "
            "MATCH (e:Endpoint {project_id:$project_id})-[:HAS_HEADER]->(h:Header) "
            "WHERE e.baseurl IN $baseurls "
            "RETURN e.baseurl AS baseurl, h.name AS name, h.value AS value, "
            "h.direction AS direction",
            {"project_id": project_id, "baseurls": baseurls},
        )
        seen: set[tuple] = set()
        for row in header_rows:
            key = (row.get("baseurl"), row.get("name"), row.get("value"),
                   row.get("direction"))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            baseurl_headers.setdefault(key[0], []).append(
                HeaderInfo(name=key[1], value=key[2], direction=key[3]))
        for rows in baseurl_headers.values():
            rows.sort(key=lambda h: (h.name or "", h.value or "", h.direction or ""))
    except Exception as exc:  # noqa: BLE001 - degrade only this slot
        diagnostics.append(f"baseurl headers read degraded: {exc}")
```

Pass `baseurl_headers=baseurl_headers` into `UnitProjection`.

- [ ] **Step 2.8: Run the two tests**

```bash
pytest tests/attack/test_unit_projection.py::test_build_projection_reads_unique_baseurl_headers tests/attack/test_unit_projection.py::test_build_projection_reads_endpoint_parameters -q
```

Expected: PASS.

- [ ] **Step 2.9: Run the whole projection test file**

```bash
pytest tests/attack/test_unit_projection.py -q
```

Expected: PASS.

- [ ] **Step 2.10: Commit**

```bash
git add src/polymerhus/attack/hunting/unit_projection.py tests/attack/test_unit_projection.py
git commit -m "feat(hunting): read headers and parameters into the unit projection"
```

---

## Task 3: Add the Markdown renderer

**Files:**
- Create: `src/polymerhus/attack/hunting/unit_projection_render.py`
- Test: `tests/attack/test_unit_projection_render.py`

- [ ] **Step 3.1: Write the renderer test**

Create `tests/attack/test_unit_projection_render.py`:

```python
"""Unit tier: the coherent Markdown renderer for one unit projection.

The renderer shows every analysis unit, every endpoint under its service, every
parameter under its endpoint, and one deduplicated header list per baseURL. It
never cuts an endpoint.
"""
from polymerhus.attack.hunting.unit_projection import (
    AggregatedEndpoint,
    HeaderInfo,
    ParameterInfo,
    SystemInfo,
    UnitProjection,
)
from polymerhus.attack.hunting.unit_projection_render import render_unit_projection


def _system(slug, contract):
    return SystemInfo(
        kind="Service",
        discriminator=slug,
        exposure="public",
        description=None,
        props={"business_function_slug": slug, "service_contract": contract},
    )


def test_render_puts_endpoints_under_their_service_and_headers_under_the_baseurl():
    projection = UnitProjection(
        unit_id="RESTApi:api",
        kind="RESTApi",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        cooperating_systems={
            "EXPOSED_VIA": (
                _system("library-catalog", "Owns the public catalogue."),
                _system("user-administration", "Administers the account roster."),
            ),
        },
        aggregated_endpoints=(
            AggregatedEndpoint(method="GET", path="/api/library",
                               baseurl="http://t", service_slug="library-catalog"),
            AggregatedEndpoint(method="GET", path="/api/admin/user",
                               baseurl="http://t", service_slug="user-administration",
                               parameters=(ParameterInfo(name="username",
                                                         position="body"),)),
        ),
        baseurl_headers={
            "http://t": (
                HeaderInfo(name="server", value="nginx", direction="response"),
                HeaderInfo(name="vary", value="accept-encoding",
                           direction="response"),
            ),
        },
    )

    rendered = render_unit_projection(projection)

    assert "### Service: library-catalog" in rendered
    assert "Owns the public catalogue." in rendered
    assert "GET /api/library" in rendered
    assert "### Service: user-administration" in rendered
    assert "GET /api/admin/user" in rendered
    assert "username (body)" in rendered
    assert "### BaseURL http://t" in rendered
    assert rendered.count("server: nginx") == 1
    assert "vary: accept-encoding" in rendered


def test_render_never_cuts_an_endpoint():
    endpoints = tuple(
        AggregatedEndpoint(method="GET", path=f"/api/{i}", baseurl="http://t",
                           service_slug="svc")
        for i in range(60)
    )
    projection = UnitProjection(
        unit_id="Service:svc",
        kind="Service",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        aggregated_endpoints=endpoints,
    )

    rendered = render_unit_projection(projection)

    assert "GET /api/0" in rendered
    assert "GET /api/59" in rendered
    assert "..." not in rendered


def test_render_says_none_observed_when_parameters_are_absent():
    projection = UnitProjection(
        unit_id="Service:svc",
        kind="Service",
        spine={},
        edges={},
        data_edges={},
        data_rel_kinds=frozenset(),
        aggregated_endpoints=(
            AggregatedEndpoint(method="GET", path="/api/a", baseurl="http://t"),
        ),
    )

    rendered = render_unit_projection(projection)

    assert "Parameters: none observed" in rendered
```

- [ ] **Step 3.2: Run the test to verify it fails**

```bash
pytest tests/attack/test_unit_projection_render.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement the renderer**

Create `src/polymerhus/attack/hunting/unit_projection_render.py`:

```python
"""Pure Markdown renderer for one unit projection.

The renderer is the modeller's grounding view. It keeps the analysis unit
coherent: each cooperating Service carries its contract and its aggregated
endpoints, each endpoint carries its parameters, and each baseURL carries its
deduplicated headers. It never truncates an endpoint.
"""
from __future__ import annotations

from .unit_projection import UnitProjection


def _contract(system) -> str:
    props = system.props or {}
    return str(props.get("service_contract") or system.description or "")


def _render_endpoint(endpoint, lines: list[str], indent: str) -> None:
    method = endpoint.method or "GET"
    path = endpoint.path or "/"
    lines.append(f"{indent}- {method} {path}")
    if endpoint.parameters:
        for parameter in endpoint.parameters:
            position = parameter.position or "unknown"
            lines.append(f"{indent}  - parameter: {parameter.name} ({position})")
    else:
        lines.append(f"{indent}  - Parameters: none observed")


def render_unit_projection(projection: UnitProjection) -> str:
    lines = [f"## Unit: {projection.unit_id} ({projection.kind})"]

    services = []
    for systems in (projection.cooperating_systems or {}).values():
        for system in systems:
            if system.kind == "Service":
                services.append(system)
    services.sort(key=lambda s: (s.discriminator or ""))

    for service in services:
        slug = service.discriminator or "(unknown)"
        lines.append(f"### Service: {slug}")
        contract = _contract(service)
        if contract:
            lines.append(f"Contract: {contract}")
        endpoints = [
            e for e in projection.aggregated_endpoints
            if e.service_slug == slug
        ]
        endpoints.sort(key=lambda e: (e.baseurl or "", e.path or "", e.method or ""))
        if endpoints:
            for endpoint in endpoints:
                _render_endpoint(endpoint, lines, "  ")
        else:
            lines.append("  - endpoints: none observed")

    if projection.kind == "Service" or not services:
        endpoints = sorted(
            projection.aggregated_endpoints,
            key=lambda e: (e.baseurl or "", e.path or "", e.method or ""),
        )
        if endpoints:
            lines.append("### Endpoints")
            for endpoint in endpoints:
                _render_endpoint(endpoint, lines, "  ")

    if projection.baseurl_headers:
        lines.append("### BaseURLs and headers")
        for baseurl in sorted(projection.baseurl_headers):
            lines.append(f"#### BaseURL {baseurl}")
            for header in projection.baseurl_headers[baseurl]:
                direction = header.direction or "response"
                lines.append(f"- [{direction}] {header.name}: {header.value}")

    return "\n".join(lines)
```

- [ ] **Step 3.4: Run the renderer test**

```bash
pytest tests/attack/test_unit_projection_render.py -q
```

Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/polymerhus/attack/hunting/unit_projection_render.py tests/attack/test_unit_projection_render.py
git commit -m "feat(hunting): render the unit projection as a coherent Markdown tree"
```

---

## Task 4: Wire the renderer into the modeller prompt

**Files:**
- Modify: `src/polymerhus/attack/hunting/llm.py`
- Test: `tests/attack/test_hunting_llm.py`

- [ ] **Step 4.1: Write the failing wiring test**

Add to `tests/attack/test_hunting_llm.py`:

```python
def test_compose_modeller_prompt_renders_the_projection_tree():
    from polymerhus.attack.hunting.llm import _compose_modeller_prompt
    from polymerhus.attack.hunting.threat_modeller import ModellerTurnInput
    from polymerhus.attack.hunting.unit_projection import (
        AggregatedEndpoint,
        SystemInfo,
        UnitProjection,
    )

    turn = ModellerTurnInput(
        unit_id="RESTApi:api",
        state="UNIT_TECHNICAL_SHARP",
        sections=("technical_sharpening",),
        instruction="model it",
        projection=UnitProjection(
            unit_id="RESTApi:api",
            kind="RESTApi",
            spine={},
            edges={},
            data_edges={},
            data_rel_kinds=frozenset(),
            cooperating_systems={
                "EXPOSED_VIA": (
                    SystemInfo(
                        kind="Service",
                        discriminator="library-catalog",
                        props={"service_contract": "Owns the catalogue."},
                    ),
                ),
            },
            aggregated_endpoints=(
                AggregatedEndpoint(method="GET", path="/api/library",
                                   baseurl="http://t",
                                   service_slug="library-catalog"),
            ),
        ),
    )

    prompt = _compose_modeller_prompt(turn)

    assert "### Service: library-catalog" in prompt
    assert "GET /api/library" in prompt
    assert "Owns the catalogue." in prompt
```

- [ ] **Step 4.2: Run the test to verify it fails**

```bash
pytest tests/attack/test_hunting_llm.py::test_compose_modeller_prompt_renders_the_projection_tree -q
```

Expected: FAIL. The prompt currently contains JSON, not the Markdown tree.

- [ ] **Step 4.3: Use the renderer**

In `src/polymerhus/attack/hunting/llm.py`, import the renderer lazily in `_compose_modeller_prompt`:

```python
from .unit_projection import UnitProjection  # noqa: PLC0415
from .unit_projection_render import render_unit_projection  # noqa: PLC0415
projection = getattr(turn, "projection", None)
projection_text = (
    render_unit_projection(projection)
    if isinstance(projection, UnitProjection)
    else _render_grounding(projection)
)
```

Use `projection_text` in the "Unit projection: " line.

- [ ] **Step 4.4: Run the wiring test**

```bash
pytest tests/attack/test_hunting_llm.py::test_compose_modeller_prompt_renders_the_projection_tree -q
```

Expected: PASS.

- [ ] **Step 4.5: Run the full hunting LLM test file**

```bash
pytest tests/attack/test_hunting_llm.py -q
```

Expected: PASS.

- [ ] **Step 4.6: Commit**

```bash
git add src/polymerhus/attack/hunting/llm.py tests/attack/test_hunting_llm.py
git commit -m "feat(hunting): use the coherent projection renderer in the modeller turn"
```

---

## Task 5: Respecify the spatial axis

**Files:**
- Modify: `src/polymerhus/attack/hunting/prompts/threat-modeller.md`
- Test: `tests/attack/test_threat_modeller_prompt.py`

- [ ] **Step 5.1: Write the failing prompt test**

Add to `tests/attack/test_threat_modeller_prompt.py`:

```python
def test_the_spatial_axis_reads_the_data_contract_not_only_the_http_carrier():
    prompt = _modeller_skill()

    assert "data attributes of the data contracts" in prompt
    assert "application contexts" in prompt
    assert "every attribute of every data type as written" in prompt
    assert "HTTP headers, URL schemes, hosts, ports, paths, fragments" not in prompt
    assert "cookies, request-body fields, multipart fields, resource identifiers" not in prompt
```

- [ ] **Step 5.2: Run the test to verify it fails**

```bash
pytest tests/attack/test_threat_modeller_prompt.py::test_the_spatial_axis_reads_the_data_contract_not_only_the_http_carrier -q
```

Expected: FAIL.

- [ ] **Step 5.3: Replace the spatial-axis bullets**

In `src/polymerhus/attack/hunting/prompts/threat-modeller.md`, replace the three bullets with:

```markdown
Read the data attributes of the data contracts and the application contexts they cross: the fields, identifiers, selectors, and state each contract carries; the principal and privilege each context establishes; and the origin, transformation, and persistence of every value.
Treat every attribute of every data type as written, including the request and response attributes that carry it, the cookies and body fields that transport it, and the middleware and downstream transformations that rewrite it.
```

Keep the following paragraph, changing "those variables" to "those attributes".

- [ ] **Step 5.4: Run the test**

```bash
pytest tests/attack/test_threat_modeller_prompt.py::test_the_spatial_axis_reads_the_data_contract_not_only_the_http_carrier -q
```

Expected: PASS.

- [ ] **Step 5.5: Run the full prompt test file**

```bash
pytest tests/attack/test_threat_modeller_prompt.py -q
```

Expected: PASS.

- [ ] **Step 5.6: Commit**

```bash
git add src/polymerhus/attack/hunting/prompts/threat-modeller.md tests/attack/test_threat_modeller_prompt.py
git commit -m "docs(hunting): lean the spatial axis toward data contracts and application contexts"
```

---

## Task 6: Teach the typist the canonical status-code meaning

**Files:**
- Modify: `src/polymerhus/analysis/prompts/technical-system.md`
- Test: `tests/analysis/test_technical_system_prompt.py`

- [ ] **Step 6.1: Write the failing status-code test**

Add to `tests/analysis/test_technical_system_prompt.py`:

```python
def test_prompt_reads_status_codes_canonically_before_withholding_a_link() -> None:
    prompt = _load_skill()

    assert "404 means the request shape is wrong" in prompt
    assert "A `400` means the request shape is wrong at the parser" in prompt
    assert "`401` or `403` means the route exists" in prompt
    assert "`5xx` means the handler exists and failed" in prompt
    assert "query the HTTP history" in prompt
    assert "replay that shape" in prompt
    assert "Never collapse a `404`" in prompt
```

- [ ] **Step 6.2: Run the test to verify it fails**

```bash
pytest tests/analysis/test_technical_system_prompt.py::test_prompt_reads_status_codes_canonically_before_withholding_a_link -q
```

Expected: FAIL.

- [ ] **Step 6.3: Add the status-code bullet**

In `src/polymerhus/analysis/prompts/technical-system.md`, after the `search_http_history`/`get_http_artifact` bullet in "Ground each hypothesis with the tools", add:

```markdown
- **Read the status code with its canonical meaning before you infer absence.** A `404` means the request shape is wrong: the path, method, or media type is not the one the handler maps. Query the HTTP history for a recorded request to the same route family, recover the canonical shape, and replay that shape with the bounded `exec` probe before you conclude the route does not exist. A `400` means the request shape is wrong at the parser; `401` or `403` means the route exists behind an authentication or authorization boundary; `5xx` means the handler exists and failed. Never collapse a `404`, `400`, `401`, `403`, or `5xx` into "no surface" or "no mechanism".
```

- [ ] **Step 6.4: Add the reconciliation rule**

In the "Link each System to its Services" section, add:

```markdown
Before you emit, reconcile the edge set against the existing Service list.
A Service whose contract names an operation reachable through the API must be linked to that API System.
A `404` on its route is not absence: recover the canonical request shape and replay it.
If you still withhold the link, name the exact status code and request shape that justified the omission.
```

- [ ] **Step 6.5: Add the reconciliation test**

Add to `tests/analysis/test_technical_system_prompt.py`:

```python
def test_prompt_reconciles_every_api_backed_service_before_emitting() -> None:
    prompt = _load_skill()

    assert "reconcile the edge set against the existing Service list" in prompt
    assert "A Service whose contract names an operation reachable through the API" in prompt
    assert "must be linked to that API System" in prompt
    assert "If you still withhold the link" in prompt
```

- [ ] **Step 6.6: Run the status-code and reconciliation tests**

```bash
pytest tests/analysis/test_technical_system_prompt.py -q
```

Expected: PASS.

- [ ] **Step 6.7: Commit**

```bash
git add src/polymerhus/analysis/prompts/technical-system.md tests/analysis/test_technical_system_prompt.py
git commit -m "docs(analysis): read status codes canonically before withholding an L1 link"
```

---

## Task 7: Offline replay and full verification

**Files:**
- Create: `docs/experiments/iteration-b-white-jotter-2026-10-25/FIX-RESULTS.md`

- [ ] **Step 7.1: Render both live projections**

Run inside the agent container:

```bash
docker exec -i ph-dd131acc-agent-1 python - <<'PY'
from polymerhus.attack.hunting.unit_projection import build_projection
from polymerhus.attack.hunting.unit_projection_render import render_unit_projection

for pid in ["7eb71c29-f28b-4f5f-ad51-7db543ce466b",
            "dda347be-abea-48e4-94e5-4a4039f41858"]:
    projection = build_projection(pid, "RESTApi:api")
    rendered = render_unit_projection(projection)
    open(f"/tmp/{pid}.md", "w").write(rendered)
    print("=====", pid, len(rendered), "chars")
    print(rendered[:2000])
PY
```

Expected:
- The old render contains `library-catalog`, `jotter-reading`, `user-administration`, and all 11 aggregated endpoints.
- The new render contains the 4 services and 5 endpoints. It cannot contain the lost services because the graph lacks them.
- Neither render contains `None` for a header or parameter name.

- [ ] **Step 7.2: Run the targeted suites**

```bash
pytest tests/attack/test_unit_projection.py tests/attack/test_unit_projection_render.py tests/attack/test_hunting_llm.py tests/attack/test_threat_modeller_prompt.py tests/analysis/test_technical_system_prompt.py -q
```

Expected: PASS.

- [ ] **Step 7.3: Run the wider suites**

```bash
pytest tests/attack -q
pytest tests/analysis -q
pytest tests/eval -q
```

Expected: PASS.

- [ ] **Step 7.4: Run static checks**

```bash
python -m compileall -q src/polymerhus/attack/hunting/unit_projection.py \
  src/polymerhus/attack/hunting/unit_projection_render.py \
  src/polymerhus/attack/hunting/llm.py
git diff --check
```

Expected: clean.

- [ ] **Step 7.5: Write the fix results**

Create `docs/experiments/iteration-b-white-jotter-2026-10-25/FIX-RESULTS.md` with:
- The renderer before/after character counts.
- The old and new rendered service/endpoint counts.
- The targeted and wider test counts.
- The status-code and reconciliation prompt rules.
- The remaining limitation: the new graph still lacks the three edges; a new trial is required to prove the typist behavior change.

- [ ] **Step 7.6: Commit the results**

```bash
git add docs/experiments/iteration-b-white-jotter-2026-10-25/FIX-RESULTS.md
git commit -m "docs(experiments): record the projection and prompt fix results"
```

---

## Task 8: Optional validation run

**Files:** none.

- [ ] **Step 8.1: Ask the operator before starting a new trial**

A new white-jotter run is the only way to prove the typist behavior change.
Do not start it without the operator's approval.
The run must use a fresh project and the same arm values as iteration B.

---

## Verification checklist

- [ ] The projection reader returns unique headers per baseURL.
- [ ] The projection reader returns parameters per endpoint.
- [ ] The renderer puts endpoints under their service.
- [ ] The renderer puts parameters under their endpoint.
- [ ] The renderer puts unique headers under their baseURL.
- [ ] The renderer never cuts an endpoint.
- [ ] The renderer says "Parameters: none observed" when absent.
- [ ] The modeller prompt uses the renderer, not the 4000-character JSON cap.
- [ ] The spatial axis names data contracts and application contexts.
- [ ] The typist prompt reads 404, 400, 401, 403, and 5xx canonically.
- [ ] The typist prompt reconciles every API-backed service before emitting.
- [ ] The targeted suites pass.
- [ ] `tests/attack`, `tests/analysis`, and `tests/eval` pass.
- [ ] The fix results record the remaining new-graph limitation.
