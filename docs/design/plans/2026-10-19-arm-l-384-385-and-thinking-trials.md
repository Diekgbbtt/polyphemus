# Arm L plan - #384 and #385 fixes, then two white-jotter trials (thinking high vs max)

Status: executing. Owner: implementation session, 2026-10-19.
Worktree: `~/.local/share/opencode/worktree/7b3bba/fix-384-385-arml` (branch `fix/384-385-arml` off `dev`).

## 0. Approach assessment (recorded before implementation)

### 0.1 #384 - the two sketched fixes, assessed

Facts from the diagnosis (`docs/experiments/2026-10-18-arm-k-384-385-diagnosis-and-overview-workflow.md`) and the recon for this plan:

- The white-jotter bootstrap artifact `auth/credentials.yaml` carries the bootstrap deployment's
  public address (`login_url: http://46.224.225.245:35493/api/login`, `domain: 46.224.225.245`).
  Every trial publishes the target on a new host port (this run: 48373).
- The project already carries the run-stable canonical origin: `settings.recon.target_seed`
  (`t-1618c524.target`), which the recon pipeline probes and the eval front routes
  (`ph-eval-front` on host :80; the front is deliberately port-free - "a port-bearing front URL
  would break the gate", `eval/orchestrator/front.py`).
- The only *placed* artifact that ever carried a deployment origin is `auth/credentials.yaml`.
  `auth/overview.yaml` uses paths; the authn skill scripts take `BASE` as a parameter; the
  operator KB carries no URL. The other environment-interacting agents (mechanism typist's
  bounded exec, hunt-orchestrator, hunter, pod runner/triager) build URLs from run-time sources
  (L0 anchors, the graph view, the HTTP history, authored specs whose `target_identity.url` is
  authored from the projected surface).
- Tracked, non-placed review artifacts also cite the stale origin: `l1-surface.yaml` (`base_url:`),
  `surface-map.md`, `research-notes.md`, for every target under `eval/data/webexploitbench/`.

**Variant A (placeholder parametrization at the prompt rendering layer across six agents).**
Requires: a placeholder syntax + a render-time resolver in six message builders (typist,
assigner, recon-orchestrator, hunt-orchestrator, hunter, pod runner/triager); the Overview
renderer (`overview_message`, pure) and its 250-word budget; the auth tool contract text; and
per-role tests. Blast radius: all prompt surfaces; benefit over the alternative: none for
correctness (four of the six already read live URLs from run-time sources).

**Variant B (holistic: consistent domain bounding at the data plane).** Adopted.
- B1. Artifacts carry no deployment origin: `credentials.login_url` -> path only; `domain`
  removed; `l1-surface.yaml.base_url` removed; `surface-map.md` / `research-notes.md` de-originated.
- B2. The app resolves a relative auth `login_url` (and back-fills `domain`) at the auth read
  seam from the project's canonical origin. Origin helper: reuse `recon.control.scope`'s
  `resolve_seed` + `seed_probe_target`; a seed without a scheme resolves to `http://<seed>`
  (the eval front's scheme; a production seed may carry its own scheme and is preserved).
- B3. The data-dependency validator refuses the two poison shapes (an absolute `login_url`,
  a `base_url` key in `l1-surface.yaml`) so the class cannot regress.
- Blast radius: the auth read path (both views), the validator, the artifact files. This is
  "the domain bounding of each target consistent across deployments": the data plane never
  names a deployment; the deployment's canonical origin is injected from the project config.

### 0.2 #385 - the mechanism and the fix shape

- The pinned model declares `reasoning_efforts: [low, high, max]`, `supports_structured_output:
  false`, `supports_forced_tool_choice: false`; the structured rung is `voluntary_function_calling`
  (ToolStrategy).
- In the final white-jotter pass the model returned the `L1DeltaBatch` payload as assistant
  **text** (4 of 4 structured calls). `_to_turn` reads only `structured_response`, so the turn's
  content was None. `stateful_turn` then read "empty content + reasoning" as the T2 blackloop
  signature and fired the blackloop recovery re-ask - which is what produced the duplicate calls,
  with an instruction about "unbounded thinking loops" that does not apply. The second text answer
  was then swallowed by the typist body's `or L1DeltaBatch()`.
- Fix shape (both, per the operator's instruction):
  - a brief prompt line naming the `L1DeltaBatch` tool at the structured steps (attention
    allocation - not done before: `L1DeltaBatch` appears in no prompt today);
  - a control-plane catch at `stateful_turn`'s structured-miss branch: when a structured turn's
    last assistant message carries a payload that uniquely validates against the schema, do NOT
    route to the blackloop recovery; instead re-ask ONCE with a corrective message that names the
    tool ("you returned the payload as text; call the `<Schema>` tool"). If the re-ask still drifts,
    accept the parsed payload fail-open with a loud warning (never silently lose a valid batch).
    If the text is not uniquely parsable, fall back to today's behaviour (fail-open, loud).

## 1. Feedback loops (red-capable first)

- **L1 (384)**: unit test - a stored path-only `login_url` renders as `http://<seed>/api/login`
  from the project's target seed (red today: renders the bare path); validator tests reject an
  absolute `login_url` and a `l1-surface.yaml` `base_url` (red today).
- **L2 (385)**: session-seam test - a stubbed structured turn whose answer arrives as text JSON
  (a) triggers the corrective re-ask naming the tool, (b) is NOT routed to the blackloop
  recovery, (c) preserves the payload (red today: blackloop recovery, then None/empty batch).
- **Live**: trial L1's auth gateway must reach the target with the canonical origin (the arm K
  failure was visible as refused connections), and the typist must write typed edges beyond
  `library-catalog`.

## 2. Work items

- **W0** worktree + this plan.
- **W1** #384: artifact sanitization (all targets' tracked KB roots; the eval host's placed
  artifacts for white-jotter) + the app-side origin resolution at the auth seam + the validator
  rules; unit tests; lint.
- **W2** #385: the prompt line + the seam correction; unit tests; lint.
- **W3** full unit sweep of the touched packages, merge to `dev`, push.
- **W4** eval alignment: update the stack checkout to the pushed tip, recreate/reload the agent
  container, verify health + mount, re-publish/repair the sanitized white-jotter data dependency
  on the host.
- **W5** trial **L1** - white-jotter, as-is thinking (declared `medium` -> wire `high`),
  budget 4,000,000 (arm K conventions, same pinned model), new run id.
- **W6** trial **L2** - same, with `providers.py` edited in place on the eval stack: the
  declared thinking of `assigner` and `mechanism_typist` raised to `max` (wire `max`; the model
  offers it exactly). Verify the live remount inside the container before launch; run; then
  `git stash` the edit.
- **W7** measurement: GT well-formedness per unit + the C1-C5 evidence set for both trials,
  compared with arm K white-jotter (0.38) and arm J formal (0.66); results-doc rows; report.

## 3. Stop conditions

Ask the operator if: the staging source of `credentials.yaml` cannot be located and the host
copy cannot be repaired safely; the seam correction needs a wider refactor than the bounded
branch; a trial shows a new blocking degradation; or a decision changes a public contract.
