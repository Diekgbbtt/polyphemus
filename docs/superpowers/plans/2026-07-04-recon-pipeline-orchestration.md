# Recon Pipeline - Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the recon pod + parser fleet into a runnable two-level pipeline driven by a REST API: `POST /recon` loads project settings (incl. auth), walks a produces/consumes phase DAG rooted at subdomain discovery, fans one pod per input asset per job (LLM-preprocessed, `Send`-bounded), triages findings into Observations, writes the Layer-0 graph, and reports status from a Postgres registry.

**Architecture:** Three layers. (1) **Pod subgraph** (from Foundation) - one tool run per input asset. (2) **Per-job orchestrator** - a compiled `StateGraph(JobState)`: an LLM `preprocess` node cleans + distributes the job's consumed assets into ≤`MAX_PODS` pod inputs, a conditional edge emits `Send("pod_runner", …)` per input, `pod_runner` invokes the pod subgraph, and `pod_exports` are collected via an `operator.add` reducer (this is the design's "2-level nesting"; checkpointed with `thread_id=run_id`, `checkpoint_ns="{phase}/{job}"`). (3) **Pipeline orchestrator** - plain async Python that loads settings, builds the phase plan, runs each phase's jobs concurrently behind a barrier, and writes the `recon_runs`/`recon_jobs` registry. Durability = registry (phase/job progress) + LangGraph checkpoints (pod progress).

**Tech Stack:** Python 3.11, LangGraph 1.2.5 (`StateGraph`, `Send`, `AsyncPostgresSaver`), langchain-openai (LLM roles from Foundation), FastAPI, psycopg, the Foundation pod (`agent/recon/pod.py`) + curator + 16-parser fleet.

## Global Constraints

- Reuse Foundation/fleet primitives; do not reimplement: `agent/recon/pod.py` (`build_pod_graph`, `default_exec_fn`, `default_triage_fn`, `pod_graph`), `agent/recon/curator.py` (`curate`), `agent/recon/parsers` (`PARSERS`, `get_parser`, and `parse_findings` on graphql/takeover modules), `agent/recon/types.py` (all state/contract types), `agent/app/llm/roles.py` (`chat_model_for`), `agent/app/clients/pg.py` + `neo4j_client.py`.
- **`JobSpec.tool` MUST byte-match a `PARSERS` key exactly** (note hyphen `"graphql-cop"` vs underscore `"subdomain_takeover"`). A job whose tool has no parser is a config error caught by a test.
- **Command templates honor the fleet's `-json` assumptions:** amass = `amass enum -json -d {domain}`; dnsx must emit `-json`; every template's structured-output flags match what its parser expects (§4 of `recon-mvp-design.md` + the parser docstrings).
- Phase barrier: phase `i+1` starts only after every phase-`i` job's pods have terminated (success or error). Best-effort: a pod/job error degrades the graph, never aborts the run (design §10.6).
- Auth channel end-to-end: `PUT /settings` stores `recon.auth_context` → pipeline loads it into `ReconState.settings` → per-job `extra.auth_context` → `PodState.extra` → `{auth_header}` (Foundation `fill_template` already handles the placeholder). Only `use_auth` jobs inject it.
- Fan-out bounded to `MAX_PODS` (env, default from Foundation config). The LLM `preprocess` distributes N consumed assets into at most `MAX_PODS` pod inputs.
- All graph writes still go through the curator; the orchestrator never writes Neo4j directly. All Postgres writes are parameterised.
- Tests run from repo root with `.venv/bin/pytest`; unit/integration tests must not need live Kali/Neo4j/LLM (inject fakes / mock clients). New package dirs need `__init__.py`.

---

### Task 1: Job registry + phase DAG

**Files:** Create `agent/recon/jobs.py`; Test `tests/recon/test_jobs.py`.

**Interfaces - Produces:**
- `JOBS: dict[str, JobSpec]` - one `JobSpec` per fleet tool that participates in the default pipeline (all 16 except the agentic-crawl/steel variant, which is sub-plan 4, and nuclei, sub-plan 5). Each with `tool` (== PARSERS key), `skill`, `command_template`, `produces` (node types), `consumes` (the input asset node type), `use_auth`, `configurator_mode="deterministic"`, `eval_criteria`.
- `PHASES: list[list[str]]` - job names grouped into ordered phases by their consumes/produces dependencies, rooted at subdomain discovery. E.g. `[["subfinder","amass"], ["dnsx","puredns"], ["whois"], ["naabu"], ["httpx"], ["katana","gau","paramspider"], ["arjun","ffuf","kiterunner","jsluice"], ["graphql-cop","subdomain_takeover"]]` (refine to actual consumes deps).
- `build_phase_plan(job_subset: list[str] | None = None) -> list[list[str]]` - returns `PHASES` (or a validated subset preserving consumes deps).
- `validate_job_subset(subset: list[str]) -> None` - raises `ValueError` if a selected job's `consumes` type is produced by no earlier selected job (design §10.5 "jobs subset breaking a consumes dependency → 400").

**Command templates (put in each JobSpec):** subfinder `subfinder -d {domain} -all -json -silent`; amass `amass enum -json -d {domain}`; dnsx `dnsx -l {infile} -json -a -aaaa -cname -silent` (or `-d {domain}` form - match the parser); puredns `puredns resolve {infile} -r /resolvers/resolvers.txt -q`; whois `whois {domain}`; naabu `naabu -host {target} -top-ports 100 -json`; httpx `httpx -u {target} -sc -title -server -td -fr -silent -json {auth_header}`; katana `katana -u {target} -d 3 -jc -kf robotstxt -c 10 -rl 50 -ef png,jpg,gif,css,woff,woff2,ttf -silent -jsonl {auth_header}`; gau `gau {domain}`; paramspider `paramspider -d {domain}`; arjun `arjun -u {target} -oJ /work/{session}/arjun.json {auth_header} && cat /work/{session}/arjun.json`; ffuf `ffuf -u {target}/FUZZ -w /usr/share/seclists/Discovery/Web-Content/common.txt -mc 200,403 -of json {auth_header}`; kiterunner `kr scan {target} -w /opt/localbin/routes-small.kite`; jsluice `jsluice urls -R {baseurl} {js_input}`; graphql-cop `graphql-cop -t {target} -o json`; subdomain_takeover `<subjack/takeover tool> -json` (match the parser's expected shape).

- [ ] **Step 1:** Write `tests/recon/test_jobs.py`: assert every `JobSpec.tool in PARSERS`; assert amass template contains `enum -json` and dnsx template contains `-json`; assert `PHASES[0]` is subdomain discovery and consumes deps are respected (each job's `consumes` type appears in an earlier phase's `produces`); assert `validate_job_subset(["httpx"])` raises (httpx consumes Subdomain, not produced) and `validate_job_subset(["subfinder","dnsx"])` passes; assert `build_phase_plan()` returns the full ordered plan.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/recon/test_jobs.py -v` → FAIL.
- [ ] **Step 3:** Implement `agent/recon/jobs.py` (the JOBS dict, PHASES, build_phase_plan, validate_job_subset). Derive consumes/produces from §10.3 node types (subfinder consumes Domain produces Subdomain; naabu consumes Subdomain/IP produces IP/Port/Service; httpx consumes Subdomain produces BaseURL/Endpoint; etc.).
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): job registry + phase DAG (tool<->parser locked, -json templates)"`.

---

### Task 2: Triager finding contract + pod findings integration

**Files:** Create `agent/recon/findings.py`; Modify `agent/recon/pod.py` (triager node consumes `parse_findings` for findings-tools); Test `tests/recon/test_findings.py`, extend `tests/recon/test_pod.py`.

**Interfaces - Produces:**
- `agent/recon/findings.py::normalize_severity(raw: str | None) -> str` - maps graphql-cop UPPER (`"HIGH"/"MEDIUM"/"LOW"/"INFO"`) and takeover lower to a canonical lowercase set `{"critical","high","medium","low","info"}` (default `"info"`).
- `agent/recon/findings.py::finding_to_observation(finding: dict, *, source_job: str, source_tool: str) -> Observation` - a finding dict `{title, severity, evidence, anchor?}` → `Observation` (macro_kind=title, severity=normalize_severity, evidence, rationale=evidence or title, anchor, source_job, source_tool). If `anchor` missing, default to a job-appropriate anchor or skip (log).
- Pod change: the triager node, for a job whose tool module exposes `parse_findings` (graphql-cop, subdomain_takeover), calls it on `exec_result.stdout` and converts findings → Observations (via `finding_to_observation`), MERGED with the LLM-added observations. For non-findings tools, behavior is unchanged (LLM triager only).

- [ ] **Step 1:** Write `tests/recon/test_findings.py`: `normalize_severity("HIGH")=="high"`, `normalize_severity(None)=="info"`; `finding_to_observation({"title":"potential_subdomain_takeover","severity":"high","evidence":"e","anchor":{"type":"Subdomain","identity":{"name":"x"}}}, source_job="subdomain_takeover", source_tool="subdomain_takeover")` yields an `Observation` with `macro_kind`, lowercase severity, and the anchor preserved. Extend `test_pod.py`: a pod running a `subdomain_takeover` job (fake exec returning a takeover JSON with one vulnerable entry, fake LLM triager returning []) produces at least one Observation from `parse_findings` reaching the curator.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `findings.py`; wire the triager node in `pod.py` to call `parse_findings` when the module exposes it (import guarded: `getattr(parser_module, "parse_findings", None)`). Keep the deterministic-vs-LLM split intact.
- [ ] **Step 4:** Run → PASS (full `.venv/bin/pytest tests/recon -v` green).
- [ ] **Step 5:** `git commit -m "feat(recon): triager finding contract - parse_findings -> Observations (uniform, normalized severity)"`.

---

### Task 3: Per-job orchestrator agent

**Files:** Create `agent/recon/job_agent.py`; Test `tests/recon/test_job_agent.py`.

**Interfaces - Produces:**
- `class JobState(TypedDict, total=False)`: `job: JobSpec`, `input_assets: list[dict]`, `asset_context: str`, `extra: dict`, `run_id: str`, `phase: int`, `pod_inputs: list[dict]`, `pod_exports: Annotated[list[PodExport], operator.add]`.
- `build_job_agent(*, pod_invoke, preprocess_fn) -> CompiledGraph` - `preprocess` node (LLM: distributes `input_assets` into ≤`MAX_PODS` `pod_inputs`, each `{input_asset, asset_context, extra}`) → conditional edge `fan_out` returns `[Send("pod_runner", pi) for pi in pod_inputs]` → `pod_runner` node calls `pod_invoke(pi, job, run_id, phase)` returning `{"pod_exports": [export]}` → `END`. `pod_invoke`/`preprocess_fn` injected for tests; provide `default_pod_invoke` (wraps Foundation `pod_graph`) and `default_preprocess_fn` (uses `chat_model_for("job_orchestrator")`; a deterministic fallback that 1:1 maps assets→pod_inputs capped at MAX_PODS when no cleaning needed).
- `run_job(job: JobSpec, input_assets: list[dict], *, run_id, phase, extra, agent=None) -> list[PodExport]` - convenience async wrapper that invokes the compiled agent and returns `pod_exports`.

**Design notes:** `default_preprocess_fn` must be import-safe (no LLM call at import). For MVP the deterministic fallback (asset→pod_input 1:1, capped at MAX_PODS, auth from `extra`) is acceptable when `configurator_mode=="deterministic"`; the LLM cleaning path is used when the job declares it needs it (keep simple: default to the deterministic mapping, structure the seam for the LLM path). `pod_runner` must translate a pod's terminal state into a `PodExport` (the pod already writes `export`).

- [ ] **Step 1:** Write `tests/recon/test_job_agent.py` (fully mocked): `pod_invoke` fake returns a `PodExport(verdict="success", ...)` per input; feed a job + 3 input_assets with `MAX_PODS`=2 → assert fan-out produced 2 pod inputs (capped) and `pod_exports` collected for them; assert a fake `pod_invoke` raising for one input doesn't abort the others (job continues, that pod → failed export). Assert auth `extra` is threaded into pod inputs for a `use_auth` job.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `job_agent.py` (JobState, build_job_agent, defaults, run_job). Use `Send` for fan-out; `operator.add` reducer on `pod_exports`; cap pod_inputs at MAX_PODS.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): per-job orchestrator agent (LLM preprocess + Send fan-out to pods)"`.

---

### Task 4: Pipeline orchestrator + registry

**Files:** Create `agent/recon/pipeline.py`; Modify `agent/app/clients/pg.py` (registry read/write helpers); Test `tests/recon/test_pipeline.py`, `tests/test_pipeline_registry.py`.

**Interfaces - Produces:**
- `pg.py`: `create_run(run_id, project_id) -> None`; `set_run_status(run_id, status, current_phase=None) -> None`; `upsert_job(run_id, phase, job, status, stats=None, error=None) -> None`; `get_run(run_id) -> dict` (status, current_phase); `get_run_jobs(run_id) -> list[dict]`; `load_settings(project_id) -> dict` (the `settings.recon` JSONB). All parameterised.
- `pipeline.py::run_pipeline(project_id: str, *, run_id: str, job_subset: list[str] | None = None, run_job=None, load_settings=None, registry=None) -> None` (async): loads settings (incl `auth_context`), `validate_job_subset` if subset, builds phase plan, then per phase: for each job, resolve `input_assets` (phase 0 seeds from the project domain/placeholder; later phases read the produced assets - for MVP, read consumed assets from Neo4j via a `read_assets(consumes_type, run scope)` helper OR pass forward the prior phase's produced assets), build `extra` (auth for use_auth jobs), `await run_job(...)` concurrently across the phase's jobs, `upsert_job` status from pod_exports (success/degraded/failed), barrier, `set_run_status`. Best-effort: a job error marks it degraded and the pipeline advances. Injected `run_job`/`load_settings`/`registry` for tests.
- `pipeline.py::seed_assets(settings) -> list[dict]` - the phase-0 root input: `[{"name": domain}]` from `settings["target_domain"]` or a placeholder.

**Design notes:** Asset flow between phases - for MVP, after each job's pods run, collect the `assets_merged` node identities from pod_exports (or re-query Neo4j for the produced node types scoped to project_id) to feed the next phase's `consumes`. Keep it simple and deterministic: a `read_assets(node_type, project_id)` Neo4j helper returning `[{identity}...]`. Auth: `extra = {"auth_context": settings["recon"]["auth_context"]}` when the job `use_auth`.

- [ ] **Step 1:** Write `tests/test_pipeline_registry.py` (mock psycopg like existing db tests) for the pg helpers, and `tests/recon/test_pipeline.py` (inject fake `run_job` returning canned `PodExport`s, fake `load_settings`, fake `registry` capturing calls): assert phases run in order with a barrier (phase 2 jobs' run_job not called until phase 1's returned); assert a job whose pods all fail is marked `degraded` and the pipeline still advances; assert auth `extra` passed only to `use_auth` jobs; assert `set_run_status` ends `"complete"`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `pg.py` helpers + `pipeline.py`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): pipeline orchestrator + Postgres registry (phase barrier, auth channel, best-effort)"`.

---

### Task 5: graphql URL threading + anchor (deferred SP2 F1)

**Files:** Modify `agent/recon/parsers/graphql_parser.py` (accept an optional target URL; drop reliance on the curl_verify regex when provided; `parse_findings` emits an Endpoint anchor); Modify `agent/recon/jobs.py`/`pod.py` seam so the graphql job threads its `{target}` into the parser; Test extend `tests/recon/test_graphql_parser.py`.

**Interfaces:**
- `graphql_parser.parse(stdout, *, target_url: str | None = None) -> list[AssetDelta]` - when `target_url` given, use it for BaseURL/Endpoint identity (deterministic); else fall back to the existing curl_verify regex.
- `graphql_parser.parse_findings(stdout, *, target_url: str | None = None) -> list[dict]` - each failed check's finding now includes `anchor: {"type":"Endpoint","identity":{"path":..,"method":"POST","baseurl":..}}` derived from `target_url` (or the regex fallback), so the triager anchors graphql Observations uniformly with takeover.
- The pod triager passes the job's resolved target into `parse`/`parse_findings` for the graphql tool (thread via `PodState` - the configurator already knows the target; store it where the triager can read it, e.g. `state["input_asset"]`'s url).

- [ ] **Step 1:** Extend `tests/recon/test_graphql_parser.py`: `parse(stdout, target_url="https://api.example.com/graphql")` yields an Endpoint with that exact baseurl/path (not regex-derived); `parse_findings(..., target_url=...)` findings each carry an `anchor` of type Endpoint. Keep the existing no-target regex-fallback tests passing.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the optional `target_url` params + anchor; thread the target through the pod triager for the graphql job.
- [ ] **Step 4:** Run → PASS (full `.venv/bin/pytest tests/recon -v` green).
- [ ] **Step 5:** `git commit -m "feat(recon): graphql target-URL threading + Endpoint-anchored findings (SP2 F1)"`.

---

### Task 6: REST API wiring

**Files:** Create `agent/app/routes.py`; Modify `agent/app/main.py` (include the router); Test `tests/test_rest_api.py`.

**Interfaces (design §10.5):**
- `POST /projects` `{name}` → `{project_id}` (insert into `projects`).
- `PUT /projects/{id}/settings` `{recon:{max_pods?, auth_context?, target_domain?}}` → `{ok}` (upsert `settings.recon`; validate `auth_context` shape → 400 on malformed).
- `POST /projects/{id}/recon` `{jobs?, settings?}` → `{run_id}` (unknown project → 404; unknown job → 400; subset breaking consumes → 400; else create run, launch `run_pipeline` as a background task, return run_id immediately).
- `GET /projects/{id}/recon/{run_id}` → `{status, current_phase, per_job:[…], pod_exports?:[…]}` (from the registry).
- Use FastAPI `BackgroundTasks` (or `asyncio.create_task`) to run the pipeline; the endpoint returns `run_id` without blocking.

- [ ] **Step 1:** Write `tests/test_rest_api.py` using `fastapi.testclient.TestClient` with the DB layer + `run_pipeline` mocked (monkeypatch the pg helpers + a fake pipeline that records the launch): `POST /projects` returns a project_id; `PUT settings` with a malformed auth_context → 400; `POST recon` on unknown project → 404; `POST recon` with an invalid job → 400; `POST recon` valid → 200 `{run_id}` and the pipeline launch was scheduled; `GET recon/{run_id}` returns the registry status.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `routes.py` + include in `main.py`. Reuse `validate_job_subset` (Task 1) for the 400s.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): REST API - projects/settings/recon launch+status"`.

---

### Task 7: End-to-end pipeline integration test

**Files:** Test `tests/recon/test_pipeline_e2e.py`.

**Goal:** One integration test wiring the REAL per-job agent + REAL pod graph + REAL parsers + REAL curator (with a captured fake Neo4j `merge_fn`) + REAL pipeline, with ONLY the two true externals faked: `exec_fn` (returns canned tool stdout per tool) and the LLM nodes (fake preprocess=1:1 map, fake triager=[]). Drive a 2-3 phase slice (subfinder → dnsx → httpx) from a seed domain and assert: phases ran in order; the curator received MERGE calls for Subdomain/IP/BaseURL/Endpoint; the registry ended `complete` with per-job statuses.

- [ ] **Step 1:** Write `tests/recon/test_pipeline_e2e.py`: build canned stdout for subfinder (2 subdomains), dnsx (A records), httpx (a probe line); wire `run_pipeline` with the real `run_job`/pod/curate (capture merges) and the faked exec/LLM; assert the captured merges include the expected node labels and the registry status transitions.
- [ ] **Step 2:** Run → FAIL (until all prior tasks integrate).
- [ ] **Step 3:** Fix any integration seams surfaced (this task is the integration net; if a seam is wrong, fix the minimal glue).
- [ ] **Step 4:** Run → PASS; full `.venv/bin/pytest -v` green.
- [ ] **Step 5:** `git commit -m "test(recon): end-to-end pipeline integration (subfinder->dnsx->httpx, real seam)"`.

---

## Self-Review (author checklist, completed)

- **Coverage:** job DAG + name-locking + `-json` templates (SP2 deferred 1,5) → T1; triager finding contract + severity normalization (SP2 F1 secondary) → T2; per-job LLM-preprocess + Send fan-out (design §3) → T3; pipeline barrier + registry + auth channel (§3,§10.6) → T4; graphql URL threading + anchor (SP2 F1) → T5; REST (§10.5) → T6; e2e net → T7. Public-suffix upgrade (SP2 deferred 4) intentionally NOT here (needs a dep decision) - remains a tracked forward item.
- **Placeholder scan:** each task has concrete interfaces, command templates, and test assertions; no "TBD"/"similar to".
- **Type consistency:** `JobSpec`/`PodExport`/`Observation` reused from `types.py`; `JobState`/`ReconState` keys consistent; `run_job(job, input_assets, *, run_id, phase, extra)` and `run_pipeline(project_id, *, run_id, job_subset, ...)` signatures consistent across T3/T4/T6/T7; `JobSpec.tool` == `PARSERS` key enforced by a T1 test.
