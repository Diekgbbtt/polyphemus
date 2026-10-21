# Quality Attribution: ComfyUI Canary

## Summary

The canary's 0 of 6 discovery result was not primarily a model-capability failure.
The pipeline produced a sharp model and an exact ratified spec for two ground-truth vulnerabilities (comfyui-001 and comfyui-002), but the pod delivery layer consumed those specs and never re-dispatched them after the provider pause.
The single largest primary cause is therefore the **pod delivery/mover layer: 2 of 6 cases**.
The next largest is the **run intake and progressive risk halt: 2 of 6 cases** (comfyui-005 and comfyui-006), with one additional contributing case (comfyui-004).
One case is a **hunter terminal-set failure** (comfyui-003): the hunter wrote the correct `/view` SVG draft but never ratified it.
One case is a **threat-modeller fault-binding failure** (comfyui-004): the model closed path traversal on literal-only probes.
The analysis/recon layer contributed to four cases through missing L0 route families and unlinked L1 service units, but it is not the primary cause of any single miss.
The runner and triager are not the primary cause of any ground-truth miss: no ground-truth spec reached a runner, while three non-ground-truth pods ran deeply and were confirmed.

## Method and evidence

The assessment reconstructs one chain per ground-truth vulnerability:
L0/L1 graph, unit intake order, threat-model loop, hunter spec status, pod directory/export, and the observability trace.

The evidence sources are:

- The graph API at `http://localhost:8080/projects/65f63a5a-1406-4635-9bba-92e23aa86d3d/graph` (2,112 nodes, 2,246 links, 22 L1 Services).
- The hunting run row `8e94cafc-4c77-41f7-856c-72f399fb4265`, including `intake_order`, `halt`, `risk_total`, and `risk_threshold`.
- The consumed threat model at `hunting/threat_modeller/consumed/RESTApi-core-http/`.
- The hunter specs at `hunting/hunter/test-specs/`.
- The pod directories and exports at `hunting/test-executor-pod/`.
- Langfuse: 8,267 observations, 1,519 traces, 55 sessions, and 740 generations in `2026-10-20T22:56:24Z..2026-10-21T01:05:01Z`.
- The official verdicts and diagnoses in the trial directory.
- The measurement report at `/opt/polymerhus-dev/eval/runs-utm-20261020/comfyui-1/comfyui-1-20261021T002730-1fc05262/measurements.md`.

The Langfuse trace is used for tool-call counts, error rates, session roles, and the hunter/pod history.
The artifacts are used for the authoritative spec status, consumed/produced location, and pod export.
The trace is weaker than the artifacts for the hunter tool calls: 406 hunter-tool spans lose both their tool type and their loop session.
That observability defect is recorded separately and does not change the artifact-based attribution.

### Langfuse evidence used in the reconstruction

| Signal | Value | Use in this assessment |
|---|---|---|
| Observations / traces / sessions / generations | 8,267 / 1,519 / 55 / 740 | Confirms the full pipeline history is present and attributable by role. |
| ERROR observations | 66 (0.8%) | 43 empty status messages, 18 `<object object at 0x...>` reprs, 3 provider 429s, 1 LightRAG timeout, 1 schema validation failure. |
| Hunter tool spans | 406 | `notes` 118, `search_http_history` 73, `graph_view` 72, `exec` 50, `hunts_store` 30, `skill_load` 20, `kb_query` 18, `get_http_artifact` 14, `skill_list` 9, `record_skill_lesson` 2. |
| KB queries | 18 total, 9 degraded | Nine returned the deterministic checklist fallback; no spec records the gap. |
| Skill loads / lessons | 20 / 2 | The hunter used the skill pair and recorded two valid lessons. |
| Modeller first generation | `cb4142758d701abd` | Confirms the modeller session started at 23:32:19. |
| Hunter first generation | `cd0a1562671c0f87` | Confirms the hunter loop-1 session started at 23:57:00. |
| Pod runner first generation | `9163d32e72c5c692` | Confirms the pod runner session for `no-quota-accounting_upload-store-growth`. |
| Pod triager first generation | `ba45524908f35851` | Confirms the triager session and the 429-degraded path. |
| Notes rejection | `0fdc82ba5f626d92` | The modeller `notes` call missing `cmd`; a tool-contract teaching rejection. |
| Trial provider failure | 00:27:30Z | The pause that exposed the consumed-spec delivery bug. |
| Post-terminal hunt tail | 01:05:04Z | The run completed after the trial record failed; the 528,690 capped-token tail is real. |

The Langfuse trace confirms the phase history and the tool usage.
It does not contain a hunter tool-call type or loop session for the 406 spans, so the artifact tree remains the authority for loop-to-spec-to-pod identity.
The 66 error observations also lose the provider failure detail, which is why the trial recorded `provider unavailable (no status)`.

## The layers

This assessment distinguishes seven layers:

1. **Recon/L0**: did the target's route families enter the graph?
2. **Analysis/L1**: did the expected service unit exist, resolve, and link to its exposed RESTApi?
3. **Run intake**: was the unit in the frozen intake order, and at what position?
4. **Threat modeller**: did it model the unit, and did it write a loop that names the vulnerability's interface and variant?
5. **Hunter**: did it write and ratify a test spec whose procedure covers the specific variant?
6. **Pod delivery/mover**: did the ratified spec reach a pod directory and produce an export?
7. **Pod runner/triager**: did the runner execute deeply enough, and did the triager judge the specified symptom correctly?

The trial harness and the provider are cross-cutting conditions, not research layers.
They matter here because the provider pause triggered the pod-delivery loss.

## Chain reconstruction

| Vulnerability | Expected unit | L0/L1 state | Intake position | Loop | Ratified spec | Pod | Primary cause | Contributing cause |
|---|---|---|---|---|---|---|---|---|
| comfyui-001 | `Service:user-data-file` (`workflow-library`) | Service exists; 0 links; `/userdata` absent | 32 | loop-5, exact `GET /userdata/ComfyUI-Manager%2Fconfig.ini` | `shared-store-namespace_manager-config-read`, ratified | None; consumed at 00:18:20, no directory/export | Pod delivery/mover | L0 `/userdata` gap; unit not linked; provider pause |
| comfyui-002 | `Service:user-data-file` (`workflow-library`) | Service exists; 0 links; `/userdata` absent | 32 | loop-3, stored XSS on user-store reads | 3 specs, ratified | None; consumed at 00:27:02, no directory/export | Pod delivery/mover | L0 `/userdata` gap; unit not linked; provider pause |
| comfyui-003 | `Service:image-upload` (`asset-upload`) | Service exists and links; `/upload/image` and `/view` present | 14 | loop-3 is scoped to `/userdata`, not the upload/view SVG route; IA-10 probed `.png/.html/.log`, not `.svg` | `artifact-extension-media-type_uploaded-svg-view` is only `hypothesised` | None; draft never ratified | Hunter terminal set | Modeller loop scope and false IA-10 conclusion |
| comfyui-004 | `Service:image-viewing` (`artefact-serving`) | Service exists and links; `/view` present | 13 | No loop; model explicitly declined traversal after literal/single-encoded probes | None | None | Threat-modeller fault binding | Run risk halt blocked `artefact-serving`; path-traversal skill not loaded |
| comfyui-005 | `Service:manager-preferences` (`extension-manager-configuration`) | Service exists; 0 links; `RESTApi:manager-http` is a bare scaffold; `/manager` absent | 28 (manager-http at 24) | No loop; core-http treated manager config as a read/write surface, not a channel-render chain | None | None | Run intake and progressive risk halt | L1 service unlinked; manager-http bare; L0 `/manager` gap |
| comfyui-006 | `Service:model-download` (`model-installation`) | Service exists; 0 links; `RESTApi:manager-http` is a bare scaffold; `/manager` absent | 29 (manager-http at 24) | No loop; core-http explicitly declined SSRF on a false premise | None | None | Run intake and progressive risk halt | Modeller SSRF decline; L1 service unlinked; L0 `/manager` gap |

## Detailed attribution

### comfyui-001 and comfyui-002: the correct research, lost at delivery

The model bound the exact ground-truth reads.
VUL-6 and loop-5 bind the restricted read to fault F-4, and the ratified spec asks for exactly `GET /userdata/ComfyUI-Manager%2Fconfig.ini` with an absence clause.
The stored-XSS loop-3 and its three specs bind the user-store read transition and carry the disposition, nosniff, and CSP checks.
These are not generic or wrong research directions.

The failure occurs after ratification.
`DispatchFeedback.ADMITTED` moves the spec to `to_move`, and `consume_spec` renames it into `consumed/` at admission.
`mover._spec_items` re-reads only `produced/`, so the consumed specs are never re-dispatched.
The provider pause at 00:27:30 cancelled the pod sessions, and the resume path did not reconcile `consumed/` against terminal exports.
The trial's terminal failure did not stop the project, so the run later completed without the specs.

Primary layer: pod delivery/mover.
Contributing layers: the L0 `/userdata` gap and the unlinked `workflow-library` unit weakened the graph grounding, but the model still found the route through live probes.
The provider pause is the trigger, not the root cause.

### comfyui-003: the correct draft was never ratified

The ground truth is an SVG uploaded through `/api/upload/image` and fetched through `/api/view`.
The analysis layer is adequate: `asset-upload` and `artefact-serving` both resolve and link, and both paths exist in L0.

The threat model's loop-3 is scoped to the user-store route, not the upload/view route.
Its IA-10 response-construction agreement probed `/view` `.png`, `.html`, and `.log`, but not `.svg`.
It concluded that the artefact route degrades active content to `application/octet-stream`.
That is true for `.html` and false for `.svg`, because the forced-download set does not include `image/svg+xml`.
This is a real modeller steering error: the loop did not direct the hunter to the upload/view SVG variant.

The hunter partly recovered the direction.
Its loop-3 grounding note records `/view posture for .svg unchecked`.
Its discriminate note defines slot 5, "artefact route with uploaded svg", as a separate sub-slice.
It wrote `artifact-extension-media-type_uploaded-svg-view` at 00:10:24.
That draft is `hypothesised`; it was never `ratified`, so the mover never dispatched it.
The terminal loop-3 write at 00:27:02 persisted only the three `/userdata` XSS specs, while the well-formedness note claimed coverage of `/userdata`, `/api/userdata`, and `/view`.

Primary layer: hunter terminal-set discipline.
Contributing layer: the modeller's loop scope and false IA-10 conclusion.
The runner is not implicated; the correct draft never reached it.

### comfyui-004: the modeller closed the class on incomplete evidence

The ground truth is a double-decoding bypass on `/view`.
The target validates `subfolder` with `os.path.normpath` and `os.path.commonpath`, then applies `urllib.parse.unquote` a second time to build the served directory.
A double-encoded `../` sequence passes validation and escapes the output root.

The analysis layer is adequate: `/view` exists, and `artefact-serving` resolves and links.
The core-http model's IA-3 probed `/view?filename=../../etc/passwd`, `/view?subfolder=../../../../etc`, and `/internal/files/..%2F..%2Fetc`.
All were literal or single-encoded forms.
The model's vulnerabilities note explicitly declined path traversal.
The path-traversal suite skill prescribes single and double URL encoding, mixed case, overlong forms, normalization tests, and repeated decoding; the model did not load it.
The fault KB already carries CWE-22 and binds it to RESTApi, so this is a procedure failure, not a KB gap.

Primary layer: threat-modeller fault binding.
Contributing layer: the progressive risk halt blocked `artefact-serving` at position 13, so the only model that considered traversal was the core-http model.
The hunter and runner were never engaged.

### comfyui-005 and comfyui-006: the halt stops the research before the manager surface

Both vulnerabilities live on the manager surface.
`comfyui-005` is the channel-URL stored XSS on `/manager/channel_url_list`.
`comfyui-006` is the model-download SSRF on `/manager/queue/install_model`.

The L1 graph contains both owning services:
`Service:extension-manager-configuration` and `Service:model-installation`.
Both resolve through their corpus aliases.
However, both have zero links, and `RESTApi:manager-http` is a bare scaffold node with no properties and no links.

The intake order contains `RESTApi:manager-http` at position 24, `Service:extension-manager-configuration` at 28, and `Service:model-installation` at 29.
The run halts after the first unit: `halt=true`, `intake_position=1`, `crossing_unit=RESTApi:core-http`, `blocked_unit=ReverseProxy`, `risk_total=44`, `risk_threshold=12`.
`RESTApi:core-http` is the only modelled unit.
No manager-http model, loop, spec, or pod exists.

The core-http model did observe the manager config through `/userdata`.
VUL-6 and AS-4 record the readable and writable config surface.
The model did not connect that surface to the manager's channel-selection and node-list render chain.
It also explicitly declined SSRF on the false premise that the only fetch primitive is the vendor-backed api-node path.
Those are real modeller errors, but they are errors inside the one unit the halt allowed.
The manager units were never given a chance.

Primary layer: run intake and progressive risk halt.
Contributing layers: the unlinked manager L1 services and the bare `RESTApi:manager-http`; the missing `/manager` L0 family; the modeller's config-surface and SSRF declines.
The halt is an accepted design decision, but it is incompatible with the eval's coverage goal.
It should be treated as a coverage defect for this experiment, not as a neutral design property.

## Aggregate breakdown

### Primary layer

| Layer | Cases | Share | Cases |
|---|---:|---:|---|
| Pod delivery/mover | 2 | 33% | comfyui-001, comfyui-002 |
| Run intake and progressive risk halt | 2 | 33% | comfyui-005, comfyui-006 |
| Threat-modeller fault binding | 1 | 17% | comfyui-004 |
| Hunter terminal-set discipline | 1 | 17% | comfyui-003 |
| Analysis/recon unit specification | 0 | 0% | none |
| Pod runner/triager | 0 | 0% | none |

### Contributing layers

| Layer | Cases | Cases |
|---|---:|---|
| Analysis/recon L0/L1 | 4 | 001, 002, 005, 006 |
| Threat-modeller loop or fault steering | 4 | 003, 004, 005, 006 |
| Pod delivery/mover | 2 | 001, 002 |
| Hunter terminal set | 1 | 003 |
| Trial harness/provider | 2 | 001, 002 as the pause trigger |
| Pod runner/triager | 0 ground-truth cases | none; one non-ground-truth triage degradation |

### Counterfactual repair

The primary-layer claim is a least-change counterfactual:

- Fix the mover's consumed-spec reconciliation: comfyui-001 and comfyui-002 should execute, because their specs are exact.
- Ratify the existing `/view` SVG draft: comfyui-003 should execute, because the procedure is already authored.
- Test double-encoded traversal and load the path-traversal skill: comfyui-004 should produce a loop and spec, because the endpoint and unit are linked and present.
- Remove or calibrate the risk halt and prioritise the manager-http unit: comfyui-005 and comfyui-006 should reach a manager model, though the modeller's config-surface and SSRF declines still need correction.
- Fix the analysis link gaps and L0 route families: this improves grounding and priority for four cases, but it does not by itself recover any case whose primary gate is elsewhere.

## Hypothesis verdicts

### H1: The analysis/recon layer did not specify the impacted unit, so it was not prioritised

**Verdict: partially supported, not primary.**

The units are specified.
All six expected service units resolve through their corpus aliases.
The failing part is linkage and route coverage:
`workflow-library`, `extension-manager-configuration`, and `model-installation` have zero links.
`RESTApi:manager-http` is a bare scaffold.
L0 has zero `/userdata` and zero `/manager` endpoints.

The priority effect is real but indirect.
The units sit at positions 28, 29, and 32; `manager-http` sits at 24.
The risk halt stops after position 1.
Even a perfectly linked manager service would still be blocked by the halt.
The analysis layer therefore contributes to the low rank, but the halt is the primary prioritisation mechanism.

### H2: Upstream lacked modelled loops that direct research toward the vulnerability

**Verdict: supported for comfyui-004, contributing for comfyui-003, comfyui-005, and comfyui-006, not for comfyui-001 and comfyui-002.**

The model wrote 18 loops.
Loop-5 and loop-3 are sharp and exact for comfyui-001 and comfyui-002.
There is no loop for the path-traversal variant, the upload/view SVG variant, the manager channel-render variant, or the manager SSRF variant.
The loop layer is therefore mixed: it succeeds on the user-store family and fails on the encoding, artefact-route, and manager families.
The manager failures are partly downstream of the halt, not independent loop-generation failures.

### H3: The hunter did not specify a procedure covering the specific variant

**Verdict: not supported for comfyui-001 and comfyui-002; supported for comfyui-003; not reachable for comfyui-004, comfyui-005, and comfyui-006.**

The comfyui-001 spec carries the exact request, four symptoms, an absence clause, and all seven procedure fields.
The comfyui-002 specs carry disposition, nosniff, and CSP checks and a second-principal reader.
The comfyui-003 draft also carries the variant procedure, but it was never ratified.
For 004 to 006 there was no loop, so the hunter had no direction to engineer.
The hunter procedure is not the general failure; the ratification/terminal-set discipline is the one hunter failure.

### H4: The runner could not execute deeply or the triager could not judge the symptom

**Verdict: not supported for any ground-truth miss.**

No ground-truth spec reached a runner.
The runner executed three non-ground-truth pods deeply:
the execution-queue pod used 49 concurrent submissions and a latency control;
the upload-store pod used admit-versus-effect, a 25-request burst, a 12-way parallel burst, and a 413 boundary sweep;
the identity-provisioning pod used an exhaustive verb matrix, an X-HTTP-Method-Override replay, and a duplicate-username existence oracle.
The triager confirmed three symptoms.
The only triager degradation is a provider 429 on the non-ground-truth `no-quota-accounting_userdata-store-growth` pod, which was exported as `no-symptom-evidence`.
That is a triage infrastructure defect, not a ground-truth miss.
The runner layer is therefore downstream of every ground-truth failure, not its cause.

### H5: The provider failure is the root cause

**Verdict: trigger, not root cause.**

The provider 429 paused the run at 00:27:30.
The pause exposed the mover's admission-based durability bug.
The mover had already marked the specs consumed; the resume path did not reconcile them.
The provider failure is therefore the trigger for comfyui-001 and comfyui-002, but the durable defect is in the mover's lifecycle semantics.
The trial-client failure and the missing app-side budget owner are separate harness defects.

## Critical review of the original diagnoses

The official diagnoses are mostly correct on mechanism and incomplete on layer aggregation.

- The comfyui-001 and comfyui-002 diagnoses correctly identify the mover path and the consumed-spec loss.
  They are the strongest diagnoses.
- The comfyui-003 diagnosis correctly identifies the unratified `/view` draft.
  It understates the modeller's IA-10 false conclusion, which is the upstream steering error that made the draft necessary and then easy to drop.
- The comfyui-004 diagnosis correctly identifies literal-only traversal probes.
  It should name the risk halt as a contributing coverage cause: `artefact-serving` was never modelled.
- The comfyui-005 and comfyui-006 diagnoses correctly identify the halt.
  They describe the halt as an accepted design property, but for this eval it is a coverage defect.
  The diagnosis should also name the unlinked `extension-manager-configuration` and `model-installation` services and the bare `RESTApi:manager-http` scaffold.
- The measurement report's first deterministic base zeroed the loop/spec/pod counts.
  The corrected base now reports 17 materialized loop files, 81 specs, 15 pods, 5 of 6 class-level candidates, and 0 of 6 unit-level candidates.
  The 2 of 6 manual binding is a reviewer credit, not an automatic pipeline success.

The central correction is the distinction between **research direction** and **delivery**.
For two of six vulnerabilities the research direction was correct and the delivery failed.
A layer-only "model quality" score hides that.

## Formal conclusion

The defective research is not explained by one layer.

The primary breakdown is:

- **Pod delivery/mover: 2 of 6 (33%)**.
- **Run intake and progressive risk halt: 2 of 6 (33%)**.
- **Threat-modeller fault binding: 1 of 6 (17%)**.
- **Hunter terminal-set discipline: 1 of 6 (17%)**.

The analysis/recon layer is the largest **contributing** layer (4 of 6) but the primary cause of none.
It specified the units but failed to link three of them and failed to ingest the `/userdata` and `/manager` route families.
Those gaps lowered the units' rank and weakened the model's grounding.
The run's risk halt then made rank decisive.

The hunter procedure is not a general failure.
It produced exact specs for the two user-store vulnerabilities and a correct draft for the artefact-route XSS.
The failure is that the draft was not ratified and the terminal set claimed coverage it did not carry.

The runner and triager are not the primary cause of any ground-truth miss.
No ground-truth test reached them.
The pods that ran executed deeply and produced three confirmed non-ground-truth symptoms.

The provider failure is a trigger for the two delivery losses, not the root cause.
The root cause is the mover's admission-based consumed-spec lifecycle and the resume path's failure to reconcile consumed specs against terminal exports.

## Recommendations

1. Fix the mover's consumed-spec reconciliation before any rerun.
   Re-dispatch every consumed spec with no terminal export, and add a regression test that pauses after admission.
2. Replace the "halt after the first unit" behaviour, or add a coverage floor over every service kind.
   The eval's purpose is coverage; a single high-risk system unit must not consume the whole modelling budget.
3. Link the service units to their exposed RESTApis at analysis time.
   `workflow-library`, `extension-manager-configuration`, and `model-installation` should not be zero-link nodes.
4. Ingest the `/userdata` and `/manager` route families, or seed the target's route inventory into L0.
5. Make the hunter's terminal write preserve every declared sub-slice.
   A draft that the hunter itself calls necessary must be ratified or explicitly dropped with a reason.
6. Require the modeller to load the class skill before it closes a fault class.
   Double-encoded traversal is a skill-prescribed probe, not an optional extra.
7. Keep the corrected measurement axes:
   artifact totals, class-level candidates, unit-level candidates, and the manual binding.
8. Do not treat the runner or triager as the cause of these six misses.
   The delivery path is upstream of them.

## Open questions

- Whether fixing the mover alone recovers comfyui-001 and comfyui-002, or whether the benchmark's unit binding still fails the verdict.
- Whether the manager units would produce loops once the halt is removed, or whether the bare `manager-http` scaffold still blocks them.
- Whether the 2 of 6 class-level units that were correctly bound by body would be accepted by the benchmark if the unit identity were normalised.
- Whether the provider 429 and the empty provider status are independent observability bugs or the same lost-detail path.
