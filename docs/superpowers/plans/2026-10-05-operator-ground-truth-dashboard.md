# Operator Ground Truth Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user's selected handoff is Worker DeepSeek; do not dispatch subagents automatically.

**Goal:** Show operator-only benchmark ground truth below each Trial verdict and display materialization timestamps in the browser's timezone.

**Architecture:** A separate GET-only operator API reads the configured benchmark checkout and setup mappings through read-only mounts, on a Docker network that the agent does not share. The browser accesses this API through a second SSH forward; ordinary eval routes and their proxy do not expose ground truth. Trial rows join the reference by exact vulnerability ID and label it as current benchmark data.

**Tech Stack:** Python/FastAPI, existing orchestrator setup parser, pytest/httpx ASGI transport, Docker Compose, React/TypeScript, Vitest/Testing Library, Intl.DateTimeFormat.

**Spec:** `docs/superpowers/specs/2026-10-05-operator-ground-truth-dashboard-design.md`

## Global Constraints

- Work in `/tmp/poly-commit`, branch `feat/eval-pipeline-frontend`, after `1a08c6e0` and `0f2740ef`; preserve unrelated files and the existing `frontend/node_modules` symlink.
- Tokens are out of scope. Do not change Trial records, materialization, graphs, inventory, benchmark files, or historical store contents.
- The reference is **current WebExploitBench checkout ground truth**, not an immutable capture from the time of a historical Trial.
- No ground-truth route is added to the shared `eval-api` or dashboard proxy.
- `eval-operator-api` must not join `polymerhus-net` or any network shared with the discovery agent; publish server `127.0.0.1:8091` only.
- Require explicit absolute `EVAL_WEB_DIR_HOST_PATH`; do not create missing source directories. Mount benchmark and eval code/configuration read-only; no Docker socket, agent credentials, or broad `.env` injection.
- `EVAL_OPERATOR_SETUP_FILES` accepts setup basenames under `eval/setups/` only; initially `first.yaml,webexploitbench-chain.yaml`. Resolve target IDs from these files, never from ID suffixes.
- CORS allows one configured origin, default `http://localhost:15173`; no wildcard. The browser operator API base defaults to `http://localhost:18091`.
- API output is limited to `target_id`, `provenance`, and vulnerabilities with `vuln_id`, `location`, `type`, `scoring`; host filesystem paths and raw benchmark blobs are excluded.
- Failures in ground truth must leave verdicts, diagnoses, graphs, and artifacts readable. Use the exact fallback `Ground truth non disponibile`.
- `copied_at` is materialization time. Display `Salvato il`; null/invalid values display `Data non disponibile`.
- Each implementation task has its own meaningful red/green test cycle and commit. No push or server deployment before implementation review and the publication/deployment authorization for that step.

## Review Focus

- A target ID reused with a conflicting setup mapping must never reveal another challenge: Task 2 mapping/conflict tests.
- Symlinked files or excessive source sizes must not escape the benchmark mount or load unrestricted data: Task 2 bounded-reader tests.
- A response arriving after the operator navigates to another target must never attach reference data to its verdicts: Task 5 delayed-response test.
- The second tunnel may be absent while ordinary results work: Task 5 rejected-fetch test and Task 6 browser smoke.
- A service isolated in Compose might still be reachable by IP or host gateway: Task 6 tests from the actual agent container, in addition to Task 4 config tests.

## File responsibilities

- `frontend/src/eval/SavedOn.tsx`: semantic, localized materialization timestamp used by list and detail.
- `eval/operator_api/ground_truth.py`: bounded source reading, setup mapping, safe per-vulnerability projection, path-free errors.
- `eval/operator_api/app.py`: operator HTTP boundary, environment factory, readiness and CORS.
- `eval/docker-compose.dashboard.operator.yml`: opt-in service, separate network, read-only sources and loopback publishing.
- `eval/operator_api/preflight.py`: host-side validation of the explicit absolute benchmark path before the documented Compose startup.
- `frontend/src/eval/operatorGroundTruth.ts`: typed operator client, response checks and request lifecycle hook.
- `frontend/src/eval/TrialResults.tsx`: pure presentation and exact row pairing; no network access.
- `frontend/src/eval/TrialSection.tsx`: activate the operator request for a displayed Trial and pass its state to results.
- Tests mirror these responsibilities; README documents installation and the two-port tunnel.

## Task 1: Localize the existing saved timestamp

**Files:** Create `frontend/src/eval/SavedOn.tsx`, `frontend/src/eval/SavedOn.test.tsx`; modify `frontend/src/eval/TargetPage.tsx`, `frontend/src/eval/TrialSection.tsx`, and their tests only as necessary.

**Interfaces:** Export `SavedOn({ copiedAt }: { copiedAt: string | null }): ReactElement` (`ReactElement` from React). Preserve the named export from `TrialSection.tsx` as a re-export if an existing caller imports it. TargetPage should import directly from the new module.

- [ ] Write `renders_saved_time_in_the_browser_timezone`: a valid offset-bearing ISO input renders one `<time>` with the unchanged `dateTime` attribute; displayed text uses the browser timezone with a timezone indicator. Use a fixed, independently checked timezone/date in this test, not a second call to the production formatter.
- [ ] Write `missing_or_invalid_timestamp_has_no_time_element`: null and a malformed string render `Data non disponibile`; no synthesized date.
- [ ] Run `npm test -- src/eval/SavedOn.test.tsx` in `frontend/`; confirm the tests fail because the new behavior is absent.
- [ ] Move SavedOn into its module; accept valid ISO timestamps with an explicit timezone offset or `Z` and format via `Intl.DateTimeFormat` with date/time fields and `timeZoneName: "short"`, without fixing `timeZone`. Keep `Salvato il` in both callers.
- [ ] Run the new test plus `src/eval/TargetPage.test.tsx` and `src/eval/navigation.test.tsx`; update raw-ISO text assertions to meaningful `<time dateTime>`/fallback checks.
- [ ] Commit only this change: `fix(eval-ui): localize trial materialization timestamps`.

## Task 2: Read and project ground truth safely

**Files:** Create `eval/operator_api/__init__.py`, `eval/operator_api/ground_truth.py`, `tests/eval/test_operator_ground_truth.py`.

**Interfaces:** Define `GroundTruthError(code: str, status_code: int)` and `GroundTruthSource(benchmark_root: Path, setup_root: Path, setup_files: tuple[str, ...])`. Methods: `read(target_id: str) -> dict[str, object]` and `health() -> dict[str, object]`. `read` returns the exact JSON shape in the spec with `provenance="current_benchmark_checkout"`.

- [ ] Write tests with temporary, literal setup/challenge/metadata fixtures: `comfyui-1` maps to `webexploitbench/comfyui`; a nonmatching basename such as `machine-a` also maps correctly; identical duplicate mappings work; conflicting mappings fail with `ground_truth_mapping_ambiguous`; unknown IDs fail with `ground_truth_target_unknown`. Assert exact `vuln_id`, Location, Type and scoring values.
- [ ] Add guard tests for traversal in request IDs, setup basenames and benchmark vulnerability IDs, symlinked directories/files, malformed JSON, duplicate vulnerability IDs, and one absent metadata file alongside one valid sibling. Conflicting duplicate vulnerability entries must not silently choose one reference.
- [ ] Add `preserves_http_locations_without_host_paths`: preserve an HTTP URL and route text; reject filesystem locations such as `/etc/passwd`, `/root/secret.yaml`, UNC paths and traversal. Error JSON must not contain the temporary source root.
- [ ] Add bounded-reader tests: reject files over 1 MiB, challenge lists over 256 vulnerabilities, display strings over 4096 characters, and serialized output over 1 MiB. Invalid individual entries are omitted; invalid top-level source is an unavailable error.
- [ ] Run `python -m pytest -q tests/eval/test_operator_ground_truth.py` with the repository Python environment and confirm intended failures.
- [ ] Implement validated basename/identifier reads under the fixed roots. Read at most the bound plus one byte and reject symlink components. Parse setup YAML with existing `orchestrator.setup.parse_eval_setup`; collect exact target mappings. Catch source/parser exceptions at this boundary and expose stable codes, never exception messages with paths.
- [ ] Follow `eval/gt.py`'s schema for challenge scoring and metadata, using guarded reads rather than calling its unbounded filesystem loader. Accept scoring as a list of bounded string signal names only. Restrict this source to dataset `webexploitbench`; another dataset returns unavailable.
- [ ] Use HTTP status 400 for unsafe identifiers, 404 for unknown target, 409 for ambiguous mapping, 503 for invalid/unavailable top-level source. A healthy source returns only `{"status":"ok"}`; otherwise `{"status":"degraded"}`. Do not list ground truth from health.
- [ ] Run the source tests; confirm valid siblings survive malformed entries and all guard tests pass.
- [ ] Commit: `feat(eval): add bounded operator ground truth source`.

## Task 3: Expose the separate operator HTTP API

**Files:** Create `eval/operator_api/app.py`, `tests/eval/test_operator_api.py`; add a route-absence assertion to `tests/eval/test_read_api_app.py` only if its existing helpers are appropriate.

**Interfaces:** Export `filesystem_source() -> GroundTruthSource`, `create_app(source_factory: Callable[[], GroundTruthSource] | None = None, *, frontend_origin: str | None = None) -> FastAPI`, and `app`. Environment names: `EVAL_OPERATOR_BENCHMARK_ROOT`, `EVAL_OPERATOR_SETUP_ROOT`, `EVAL_OPERATOR_SETUP_FILES` (comma-separated basenames), `EVAL_OPERATOR_FRONTEND_ORIGIN`. Defaults inside the container: `/srv/webexploitbench`, `/srv/eval/setups`, `first.yaml,webexploitbench-chain.yaml`, `http://localhost:15173`.

- [ ] Write HTTP tests using `httpx.AsyncClient(transport=httpx.ASGITransport(app=...))` and `asyncio.run` to avoid the existing thread/socket limitation of sandboxed TestClient. Test GET `/health`, GET `/ground-truth/targets/comfyui-1`, mapped error statuses, and POST rejection.
- [ ] Test that configured origin `http://localhost:15173` receives the CORS header and `https://other.invalid` does not. Reject wildcard or non-loopback origin configuration. Health responses and failure bodies contain no ground truth or host paths.
- [ ] Test shared `read_api.app.create_app` still has no `/ground-truth/targets/{target_id}` route. This is a route-boundary check; do not alter its implementation.
- [ ] Run `python -m pytest -q tests/eval/test_operator_api.py` and observe intended failures.
- [ ] Implement the two GET endpoints with docs/openapi disabled, source errors converted to stable HTTP `detail` codes, and CORS allowing GET only without credentials. Source configuration is read when the source is constructed per request; module import performs no filesystem/network reads.
- [ ] Run Task 2 and Task 3 tests together; confirm source and HTTP behavior agree.
- [ ] Commit: `feat(eval): expose operator-only ground truth API`.

## Task 4: Wire the service on its own Docker network

**Files:** Create `eval/docker-compose.dashboard.operator.yml`, `eval/operator_api/preflight.py`, `tests/eval/test_operator_preflight.py`; modify `tests/eval/test_eval_overlay.py` staging/render helpers to support this fourth opt-in file; modify the relevant dashboard section of `README.md`.

**Interfaces:** Service name `eval-operator-api`, network key `eval-operator-net`, HTTP container/host port 8091. Entrypoint `python -m uvicorn operator_api.app:app --host 0.0.0.0 --port 8091`, using `polymerhus-agent:latest`, working directory `/srv/eval`, `PYTHONPATH=/srv/eval`. Only this service joins the new network.

- [ ] Add render tests asserting: service/network absence without the operator overlay; with it, exactly one added service, network intersection with `agent`, `kali`, `eval-api` and `eval-dashboard` is empty; port publishes only on `127.0.0.1`; restart is `unless-stopped`; no Docker socket, `env_file`, credentials, or ground-truth proxy settings are added elsewhere.
- [ ] Add config tests for required `EVAL_WEB_DIR_HOST_PATH` and the long-form benchmark bind with `read_only: true`, `bind.create_host_path: false`. Check eval source/configuration is also mounted read-only. Missing variable must fail Compose interpolation; a missing directory must fail actual startup preflight, not create it.
- [ ] Write preflight tests invoking `python -m operator_api.preflight`: missing/relative/nonexistent host paths return nonzero without creating directories; an existing absolute benchmark checkout succeeds. Define `main() -> int`; diagnostics contain stable codes, never secret configuration.
- [ ] Run `python -m pytest -q tests/eval/test_eval_overlay.py tests/eval/test_operator_preflight.py` and observe expected failures for the absent overlay and preflight.
- [ ] Implement only the opt-in operator overlay. Set the Task 3 environment values and a healthcheck against `/health`. Use the separate network without connecting to `polymerhus-net`. Keep the real dashboard overlay's existing two-service contract intact.
- [ ] Implement the host preflight and document its required invocation before the four-file Compose command, approved setup list, localhost origins, second forwarded port and absent-tunnel fallback. Document current-checkout provenance and that changing the local forwarded ports requires matching browser base/CORS configuration.
- [ ] Run the complete overlay and preflight test files; inspect rendered service mounts and network memberships.
- [ ] Commit: `ops(eval): isolate operator ground truth service`.

## Task 5: Add ground truth to each displayed Trial result

**Files:** Create `frontend/src/eval/operatorGroundTruth.ts`, `frontend/src/eval/operatorGroundTruth.test.ts`, `frontend/src/eval/operatorGroundTruthHook.test.tsx`; modify `frontend/src/eval/TrialSection.tsx`, `frontend/src/eval/TrialResults.tsx`, `frontend/src/eval/TrialResults.test.tsx`, `frontend/src/eval/TargetPage.test.tsx`, and `frontend/src/eval/eval.css`. Update existing Trial page fetch fixtures only where this new request is mounted.

**Interfaces:** Export `GroundTruthEntry { vuln_id: string; location: string; type: string; scoring: string[] }`, `OperatorGroundTruth { target_id: string; provenance: "current_benchmark_checkout"; vulnerabilities: GroundTruthEntry[] }`, `getOperatorGroundTruth(targetId: string, signal?: AbortSignal): Promise<OperatorGroundTruth>`, and `useOperatorGroundTruth(targetId: string, enabled: boolean): GroundTruthState`. State is a discriminated union: `disabled`, `loading`, `unavailable`, or `ready` with `data: OperatorGroundTruth`.

- [ ] Write client tests for a request to `http://localhost:18091/ground-truth/targets/<encoded-id>`, AbortSignal forwarding, explicit loopback base override through `VITE_OPERATOR_GT_API_BASE_URL`, rejected non-loopback override, HTTP/network failure, malformed payload, response target mismatch, and duplicate conflicting vulnerability IDs. Never fall back to the shared eval or agent API.
- [ ] Write hook tests for one request on mount, no request when disabled, cleanup/abort on identity change, and a delayed old response arriving after a new target response. The old target's entries must never appear in the new state.
- [ ] Write row presentation tests: exact `vuln_id` pairing, two repeated verdict rows receive the same matching reference without collapse, missing entry and unavailable API show `Ground truth non disponibile`, and metadata is beneath the match cards and above Evidence. Test normal verdict and diagnosis content remains visible on rejection.
- [ ] Update the Target index test to assert no operator ground-truth request alongside its existing no-graph/no-inventory assertions. Assert the ordinary verdict artifact view does not initiate operator requests.
- [ ] Run the named tests and observe expected failures for the missing behavior.
- [ ] Implement the separate client/hook. Default base is `http://localhost:18091`; accepted overrides use http(s) and a loopback hostname, without embedded credentials, query or fragment. Validate response shape, requested target identity and unique reference IDs before accepting it. On a target change, do not return a prior ready state even in the render before effect cleanup. Do not surface raw HTTP bodies or filesystem details.
- [ ] In `TrialSection`, call the hook with `enabled = trial.verdicts.length > 0`; pass state into `TrialResults`. Extend `TrialResults`/`VerdictList` with optional ground-truth state so existing pure/artifact callers remain valid. They must not fetch themselves. Render `Ground truth (current benchmark)` and escaped text fields Location, Vulnerability type, Scoring signals. Loading may show `Loading ground truth…`; unavailable or absent row uses the exact agreed fallback.
- [ ] Add compact `.trial-ground-truth` styling using existing site tokens and responsive wrapping; no new cards for the Target index. Empty scoring array displays an em dash.
- [ ] Run the focused client/hook/results/Target/navigation tests, then `npm test`, `npx tsc --noEmit`, and `npm run build` in `frontend/`. Run the new backend source/API and overlay tests together. Report any failure by name, distinguishing existing environment blockers from this change.
- [ ] Review the complete implementation diff against the approved spec and commit: `feat(eval-ui): show operator ground truth per verdict`.

## Task 6: Review, authorized publication and server verification

**Files:** No application change required. Record deployment evidence in `docs/superpowers/plans/2026-10-05-operator-ground-truth-dashboard.md` after verification.

**Interfaces:** Deployment checkout `/opt/polymerhus-dashboard`, Compose project `ph-dd131acc`, agent service from its existing Compose project, server `46.224.225.245`. Preserve all Trial data and discovery services.

- [ ] Review Task 1-5 commits, source validation, browser requests and full Compose configuration. Confirm no proxy route or source mount makes ground truth reachable through existing agent/eval/dashboard containers.
- [ ] Prepare the exact deploy diff and commands. Obtain publication/deployment approval if not already explicitly granted for this feature; the approved design and plan alone do not authorize a live rollout.
- [ ] After authorization, push the branch and fast-forward only a clean server checkout. Verify the absolute WebExploitBench path and configured setup files exist on the server; do not assume the local developer fixture path.
- [ ] Start/recreate only `eval-operator-api` and `eval-dashboard` with the existing Compose files plus the new operator overlay. No `down`, volume deletion, orphan cleanup, Docker daemon restart, or discovery-stack restart.
- [ ] Inspect actual port binding, read-only mounts, restart policy, service health, and network membership; confirm no shared network with the agent. Verify host-loopback health and current ground truth for the known `comfyui-1` and `jetlinks-1` targets, with path-free response bodies.
- [ ] From inside the actual agent container, attempt HTTP access using the operator service name, its inspected container IP, and the agent's host-gateway IP at port 8091. All must fail; testing `127.0.0.1` inside the agent alone is insufficient. If any attempt succeeds, stop the operator service, report the failed isolation check and resolve the boundary before marking deployment complete; do not apply broad host firewall changes without a reviewed scope.
- [ ] Open the documented two-port SSH tunnel and check an actual Trial page: correct reference attached to each matching verdict, localized saved timestamp, and working results/graph/artifacts. Remove the second forward and check only ground truth becomes unavailable.
- [ ] Record server SHA, health, tunnel smoke and isolation evidence. Close temporary tunnels/sessions. Report implementation and deployment separately if live verification remains unavailable.

## Execution handoff

Pass the spec and this plan to Worker DeepSeek. Execute one task at a time, showing each meaningful failing test before implementation and committing only that task's paths. The completed implementation is reviewed before publication and server rollout. Ground truth from a changing benchmark checkout must retain its explicit current-reference label throughout the UI.
