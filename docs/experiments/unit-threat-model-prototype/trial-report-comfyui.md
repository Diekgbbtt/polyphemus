# Trial report - comfyui live-target trials (T1, T2)

*Status: complete (2026-10-15). Both trials reviewed against the ground-truth bundles and the injected patches; the session-side live verification is recorded in section 5.*
*Target: the running comfyui deployment on the eval server (`http://46.224.225.245:44177`, container `web_comfyui-comfyui-manager-1`, ComfyUI + ComfyUI-Manager V3.37), which carries the benchmark's inserted-vulnerability patches.*

## 1. Protocol and review method

- Both trials used the same subagent model (`opencode/deepseek-v4.1-flash-free#max`) and the trial packages under `docs/experiments/unit-threat-model-prototype/trials/`.
- Each trial embedded: the five-state workflow, the operator's bound-in review feedback (breadth, drop rule, evidences, rungs, loops, failure-mode role, suite mapping), probe/notes/gate conventions, the unit dossier, and the output contract (`state` field, per-record `rung` and `evidences`, `suite_class`, `drop_reason`, `likelihood_rationale`, `evidence_gaps`).
- Review method: compare each model against the ground-truth bundle (`/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/comfyui/comfyui-005` and `-006`) and the injected patches (`/Users/diekgbbtt/WebExploitBench/comfyui/setup_files/environment/inserted_vulns/`), then check the operational artefacts (probes.log, gates.log, notes.md, metrics.yaml) for discipline.
- Verdicts use the operator's rules: the drop rule (W4: no evidence collectable from the HTTP-history store or target interaction), the likelihood-only ranking, and breadth as a feature (W2).

## 2. T1 - `Service:model-download` (GT comfyui-006, SSRF)

Status: completed 2026-10-15; five states; 58 of 60 probe commands; 1228 s total wallclock; 0 failed gates.
Artefacts (all under `docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/`):

- `threat-model-Service-model-download.yaml` - 12 interface agreements, 7 control flows, 6 data flows, 10 trust agreements, EFSM 7 states/8 transitions/6 violations, 15 assumptions, 15 faults, 16 vulnerabilities (12 kept, 4 dropped), 17 failure modes (13 feasible), 13 loops, 12 evidence gaps.
- `trace.md`, `notes.md` (9 episodic notes), `gates.log` (5 gate writes), `probes.log` (58 probes), `metrics.yaml`.

### 2.1 Ground-truth coverage (strong)

- **The GT vuln was reproduced end-to-end.** The GT chain is: enqueue `install_model` with a `.safetensors` filename and an attacker URL, start the queue, and the Manager fetches the listener. T1's loop-1 (SSRF, high, OBSERVED) rests on P28 (loopback fetch, 5 B body persisted) and P57/P58, where the `ssrf-listener` hit log recorded fetches for the `t1-*` markers (`t1-2`, `t1-7`, `t1-10`, `t1-12`, `t1-13`, `t1-14`, `t1-15`). The GT oracle fired.
- The weakened membership check was characterised exactly by differential probes: non-catalog `.safetensors` items accepted (P09/P13) while non-safetensors and `.bin` items are rejected (P11/P12); a non-catalog URL for a `.pth` entry is rejected (P22) while a different catalog entry's URL is accepted (P23); a catalog URL with an added query parameter is rejected (P48, strict string equality).
- The trial noted the divergence from upstream tag 3.37 (`check_whitelist_for_model`) and declared the live deployment the authority for the model. This is the correct discipline and the contrast case to T2's defect.

### 2.2 Findings beyond the GT (breadth)

- VUL2 local file read via `file://localhost` URLs (P36-P38): `/etc/passwd` (839 B) and `/proc/self/environ` (790 B) written into the model tree as listable files.
- VUL3 arbitrary remote-content write under client-chosen names (P13/P16/P19/P41).
- VUL5 path traversal via a `..` save_path (P29 wrote `models/etc/t1-tr-save.safetensors`).
- VUL6 cross-entry artifact substitution (P23 vs P22).
- VUL7 unauthenticated state-changing GETs (P14 start drained the queue; P24 reset executed).
- VUL8 worker-crash DoS via a non-string `ui_id` poison item (P50-P56: halt, no fetch, manual recovery required).
- VUL9 accounting corruption (P40/P25: undercount and counters surviving reset).
- VUL10 anonymous inventory disclosure (P16/P17/P19/P41).
- The EFSM surfaced real state faults (reset retains counters; serial worker starvation and recovery semantics), which is exactly what the dynamic-state branch is for.

### 2.3 Defects

1. **DROP-DECISION FACT ERROR (same class as T2's).** FM16 (catalog poisoning to stored XSS) was dropped with "the channel list is fixed to GitHub raw URLs and no custom channel route was observed". P44 was a read of the channel list; the write path (`?value=<valid URL>`) was never probed, and on this target it accepts and persists an arbitrary channel URL (section 5 live confirmation). The dropped direction is the comfyui-005 carrier (a cross-unit direction). Severity: medium for breadth - the trial's own GT (comfyui-006) stayed loop-1 high, so no GT loss for this unit.
2. **Gate cadence deviation (process).** The whole probe campaign ran before gate 1 was written; gates 2-5 measure model-authoring time, and all 9 notes were written in one batch at 21:46:00Z. The workflow specifies a gate write at each state transition and notes at the end of each tool-using reasoning phase. The final model did not suffer, but per-state attribution and the episodic note framing are lost. T2 executed the cadence correctly. Recorded as a workflow question (R2-17).
3. **Budget-bound saturation (minor).** The concurrency branch stayed ASSUMED because the budget was nearly exhausted (58/60), and the trace records it honestly in `evidence_gaps`. No defect, but it frames the saturation-versus-budget residual.
4. **FM17 drop (defensible, noted).** The `custom_nodes` staging item was accepted (P27) but never fetched (P58); the drop argues the impact needs a code load that a `.safetensors` file cannot trigger. Reasonable; the "never fetched" fact is queue-mechanics-dependent (poison batch), so the drop rests on the impact argument, not only on the absent fetch.

## 3. T2 - `WebPresentation:custom-node-catalog::manager-shell` (GT comfyui-005, Stored XSS)

Status: completed 2026-10-15; five states; 27 probes; 837 s measured; 0 failed gates.
Artefacts (all under `docs/experiments/unit-threat-model-prototype/trials/t2-system-catalog-manager-shell/output/`):

- `threat-model-WebPresentation-custom-node-catalog.yaml` - 8 interface agreements, 6 control flows, 6 data flows, 8 trust agreements, EFSM 8 states/8 transitions/6 violations, 9 assumptions, 9 faults, 10 vulnerabilities, 11 failure modes, 9 kept loops, 1 dropped vulnerability, 8 evidence gaps.
- `trace.md`, `notes.md` (5 episodic notes, per gate), `gates.log` (5 gate writes), `probes.log` (27 probes), `metrics.yaml`.

### 3.1 Strong points

1. Real probing discipline: every interface agreement and trust agreement carries `evidences` pointing at probe lines or served assets; OBSERVED/INFERRED rungs applied consistently.
2. Mutation discipline with restore: the channel-switch probe recorded the prior value, verified persistence by read-back, restored it, and verified the restore; mutations are labelled in `metrics.yaml`.
3. The dynamic-state branch produced genuine insights: per-channel cache re-exposure on re-selection (DTV-4, raised to OBSERVED by probe), channel identity not bound to the rendered rows (TOCTOU), notice HTML as external trusted state with TLS verification disabled.
4. Exact sink-chain grounding: TurboGrid `renderNodeContent` innerHTML with the identity string formatter; no formatter on the description column; 584 served descriptions already carry markup. This matches the GT render sink (`.cn-pack-desc` innerHTML).
5. Breadth: 9 loops kept across high/medium/low, one drop recorded in place, suite-gap classes kept under canonical names, and two out-of-unit candidates surfaced for hunters - including T1's GT SSRF candidate (`install_model` whitelist-vs-url gap) and a prototype-pollution direction.
6. Output contract and honesty: `evidence_gaps` with blocked-probe reasons; combined gate timestamps for states 3-4 are annotated.

### 3.2 Defects

1. **DROP-DECISION FACT ERROR (critical; GT-carrier miss).** V-10 (SSRF via channel URL) was dropped with "no runtime path from this unit's interfaces places an attacker URL into the channel config (channel_url_list?value= only selects among the predefined dict)". The deployed patch accepts any valid URL via `?value=`; the discriminating probe was never run (only built-in names `recent`/`default` were exercised). The claim came from unpatched upstream source and was elevated to a drop. Under W4 the drop is invalid.
2. **Ranking consequence.** The stored-XSS loops (loop-2/3) carried the heavier prerequisite "attacker control of consumed catalogue content (community listing, compromised repo, or a channel the operator adds)". With the channel write modelled, the prerequisite shrinks to "any unauthenticated peer persists a channel to their own origin" - the GT vector. The stored XSS therefore ranks below the CSRF loop partly because of the missing fact.
3. **Source-vs-target discipline (root of defect 1).** Upstream source was declared a hypothesis generator, but one decisive feasibility judgement rested on upstream behaviour against the deployed patched code.
4. Minor: nested suite variants (`xss-stored`/`xss-dom`) deferred per the current mapping rule; states 3-4 gates logged in one batch (annotated).

## 4. Cross-trial findings

1. **Ground-truth coverage.** T1's GT (SSRF, comfyui-006) is fully covered and oracle-proven. T2's GT sink chain (getlist -> markdown re-render -> innerHTML) is covered accurately, but its carrier (the arbitrary channel URL write) was misjudged, weakening the model's reachability analysis of the GT's own vector.
2. **The unprobed-carrier drop reproduced in both trials.** Both models dropped a direction after reading (not writing) the channel list and inferring fixed behaviour from upstream source. The live target accepts and persists an arbitrary channel URL (section 5). This is the same defect class as the prototype's two drops; the operator's critical verdict on the prototype is confirmed cross-target.
3. **Live-authority rule.** T1 declared and exercised the rule "live responses are the evidence; upstream source is a hypothesis generator" (and disclosed the divergence) - except at FM16. T2's defect is exactly the violation of that rule. The rule is worth writing into the workflow (candidate R3-10).
4. **Gate-cadence asymmetry.** T2 interleaved probes and gate writes state by state; T1 batched all probing first and wrote the model afterwards (notes batched too). Model quality was high in both cases; the trajectory telemetry degenerates under batching (candidate R2-17).
5. **Suite class gaps observed on live evidence.** Denial of service (T1), supply-chain repository substitution (T1), content-cache poisoning, improper input validation and tabnabbing (T2) have no covering suite class. The keep-canonical-and-flag rule worked; the gap list is evidence for the suite workstream.
6. **Trial protocol hygiene.** The ~60 probe stop rule held (T1 58/60, T2 27). Both trials recorded mutating effects with restore; T1's model-tree residue was cleaned by the session (section 5).

## 5. Session-side verification and actions

- **Live confirmation of the channel-URL write (the T2/T1 drop question):** `GET /manager/channel_url_list` showed `selected: default`; `GET .../channel_url_list?value=http://127.0.0.1:9/review-probe` returned HTTP 200; read-back showed `selected: "custom"` (the server labels any non-dict selection `custom`) - the arbitrary URL persisted. Restore `?value=default` returned 200 and read-back verified `selected: default`. Both trials' channel-write drops are therefore factually invalid on this target, and the drop question was decidable with one unrun GET.
- **Cleanup:** T1's model-tree residue (12 `t1-*` files under `/workspace/models/`, including `models/etc/t1-tr-save.safetensors` and the passwd/environ samples) was removed via the eval server; the queue was left empty by the trial itself. The probe records preserve the evidence.
- **Trial-spec correction:** both input files carried a wrong suite path (missing `/polymerhus`); corrected 2026-10-15. Both trials detected the defect and recovered.

## 6. Verdict summary

| | T1 `Service:model-download` | T2 `...catalog::manager-shell` |
|---|---|---|
| GT vuln | SSRF (comfyui-006) | Stored XSS (comfyui-005) |
| GT carrier kept? | yes - loop-1 high, oracle-proven | sink chain yes; carrier (channel URL write) dropped erroneously |
| Drop discipline | one invalid drop (FM16), same class | one invalid drop (V-10), GT carrier |
| Evidence discipline | strong (live-authority declared; differential probes) | strong (evidences, rungs, restore discipline) |
| Breadth | 13 loops; LFI write DoS accounting found beyond GT | 9 loops; surfaced T1's GT + prototype pollution |
| Process | gate cadence batched (telemetry loss) | gate cadence correct |
| Verdict | pass with one drop-discipline defect | pass on evidence work; fail on the drop decision |

Follow-up candidates recorded in the workbench: R2-17 (gate cadence), R3-9 (retention and the drop decision node), R3-10 (live-authority rule); all three are since decided or reframed there.

## 7. Post-review operator refinement (2026-10-16)

The operator reframed the two DROP-DECISION FACT ERRORs: the root cause is the over-narrowing of the vulnerability analysis to specific vectors, not the mere absence of a probe.
The correct reasoning shape is broad and modelling-oriented at the trust-agreement level; vectors and payloads are the hunters' ownership; a falsified vector lowers the likelihood rather than dropping the vulnerability; only a fundamental technical-infeasibility finding drops, and it corrects the trust agreements it was mapped from (a backward effect).
The two dropped directions are therefore retained, lower-likelihood loops; the full semantics are recorded in the workbench (section 1.7 refinement, R3-9) and the workflow contract (section 2.1), with the glossary terms updated.
