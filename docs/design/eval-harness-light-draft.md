# Eval Harness Light Draft: agent-as-orchestrator-and-oracle toolkit

*Light design draft (temporary, strategic). Supersedes `docs/design/eval-harness-design.md` as the IMMEDIATE implementation path.
The full design doc stays the target end-state; this draft is the minimal system that gets an evaluation running NOW, before the hunting pipeline wiring (spec #169) lands.
Status: draft (contract), NOT implementation.*

---

## 1. The goal, restated

The evaluation system is "fine" as soon as an agent, instructed with the harness primitives, operates as BOTH the orchestrator (bring up target, drive the polymerhus pipeline, collect evidence) and the oracle function (judge, from the evidence, which ground-truth vulnerabilities the pipeline identified).
Everything beyond that is deliberately non-optimal and temporary.

## 2. The minimal system

Two pieces:

1. A tiny toolkit under `tools/eval/`: four small files plus one static mapping table.
2. One agent-facing playbook (`tools/eval/PLAYBOOK.md`): the workflow, the judgment protocol, and the verdict schema.

The agent (driven through opencode, or a dispatched subagent) executes the playbook using the toolkit.
There is no orchestration engine, no oracle code, no judge service, no dashboard, no CAGE integration.

## 3. The primitives

### 3.1 Target lifecycle: reuse WebExploitBench `scripts/targetctl` as-is

The WebExploitBench checkout already ships `targetctl` (list / build / up / ps / down).
The playbook instructs the agent to use it directly: `targetctl up <challenge>`, read the published URL, `targetctl down` after the trial.
Zero new code. Down-after-trial also solves the machine-space constraint for the bundled 5 targets.

### 3.2 `tools/eval/gt.py` - ground truth table

One small script: given a challenge directory, prints the vuln table `{vuln_id, Location, Vulnerability Type}` from `challenge.json` + `vulnerability/*/metadata.json`.
Removes parsing variance from the agent's judgment input. ~40 lines.

### 3.3 `tools/eval/ph.py` - the polymerhus API client

The one substantial primitive. Thin subcommand client over the polymerhus REST surface, encoding the payloads and polling semantics so the agent never guesses API shapes:

- `ph.py project create <name>` -> project_id
- `ph.py settings put <project> --target-seed URL --operator-kb FILE [--toggle key=value ...]`
- `ph.py bootstrap <project>`
- `ph.py recon launch <project> [--jobs ...] [--with-analysis]` -> run_id
- `ph.py recon poll <project> <run> --until terminal` (with the liveness gate: terminal status + job counts)
- `ph.py hunting launch <project>` -> hunting_run_id (the whole-pipeline launch, unchanged shape pre- and post-wiring)
- `ph.py hunting poll <project> <run> --until terminal`
- `ph.py graph get <project> --out FILE`

~200 lines. The operator KB is written by the agent per target, derived from the challenge's neutral `agent_input`, never leaking the vuln list.

### 3.4 `tools/eval/ev.py` - the evidence bundle collector

Assembles ONE self-contained bundle directory per trial: the graph JSON, the hunt-store trail for the run, the per-project memory, the pod artifact tree (when present), the hunting run status, timestamps.
The bundle is the oracle's only input, and it is the migration seam: the full design's deterministic oracle later replays the same bundles. ~80 lines.

### 3.5 `tools/eval/cwes.yaml` - the Vulnerability Type -> CWE mapping

Static table mapping WebExploitBench's `Vulnerability Type` vocabulary onto CWE ids through the fault-KB (SQL Injection -> CWE-89, SSRF -> CWE-918, Arbitrary File Read -> CWE-22, XSS -> CWE-79, weak credentials -> CWE-1392/CWE-521, ...).
The agent consults it during judgment so the fault-class conjunct is consistent across trials. ~30 lines.

### 3.6 `tools/eval/PLAYBOOK.md` - the instructions

The playbook is the harness interface. It contains:

1. The per-trial workflow (bring up target -> ground truth -> fresh project -> settings -> bootstrap -> recon+analysis -> hunting -> poll to terminal -> evidence bundle -> judge -> verdicts + trial record -> teardown), and the pass@k repetition rule (fresh target + fresh project per attempt).
2. The judgment protocol (section 4).
3. The verdict schema and the trial record format.
4. The integrity gates: a recon run that "completes" without job output is a failed run, not an empty finding; the hunting run status is recorded so "pipeline failed" is never read as "vuln not found".

## 4. The judgment protocol (the oracle instructions)

For each ground-truth vuln `(Location L, Vulnerability Type T)`:

1. **Fault-class conjunct**: a hunt config or pod spec whose semantic id carries a fault matching `cwes.yaml[T]` (the wired ids make this a filename read: `config_id = <unit_id>_<CWE_ID>_<fault_class>`, `spec_id = <fault>_<strategy>`).
2. **Locus conjunct**: the spec's `target_identity` or the probe URLs in its raw observations resolve to `L` (the L1 unit covering `L` via `AGGREGATES`, read from the graph bundle).
3. **Symptom conjunct**: a pod run whose `PodExport` verdict is `successful` with `terminal_reason = symptom-confirmed`, whose experiment-log interpretations and `experiment_summary` correspond to `T`'s observable symptom. Symptom-confirmed IS the sufficient assertion of the vulnerability being exercised.
4. **Verdict**: identified only when all three conjuncts hold. A symptom confirmed at the wrong locus or for the wrong fault class is a false positive, recorded as `partial` at most.
5. **Degraded trail** (pre-wiring, when no pod artifacts exist): grade on the hunt-store configs (fault + unit from the id), the per-project notes, and the L1 graph. `identified` requires the config's unit to cover `L` AND a corroborating note or observation; otherwise `partial` or `missed`.

Output per vuln: `{vuln_id, type, location, verdict: identified|partial|missed, evidence_refs, confidence, notes}` written as `verdicts.yaml` into the bundle.

## 5. Pairing with the wired hunting pipeline (spec #169)

The temporary harness is forward-compatible by construction:

- **Same REST surface**: whole-pipeline launch is the existing `POST /hunting`, unchanged shape.
- **Semantic ids are the oracle's friend**: the produced/consumed memory families (`hunt-configs`, `test-specs`, `experiment-logs`) carry semantic filenames, so the fault-class and unit conjuncts are filename reads, not NL parsing.
- **Session ids map to traces**: `hunting:<run_id>:pod:<config_id>:<spec_id>` names the Langfuse pod trace the judgment can cite.
- **The wiring stubs the verdict workflow** ("consume and record, no re-evaluation"), so the harness - the agent - IS the verdict interpreter, now and after the wiring lands. Nothing in the harness changes.
- **One live hunting run per project**: fresh project per trial already guarantees it.

## 6. Deliberately dropped, with the reintroduce trigger

| Dropped (from the full design) | Reintroduce when |
|---|---|
| CAGE integration (serve mode, ServeClient) | results need the CAGE audit trail and `.cage_serve` persistence |
| Setup-pipeline web API | the machine cannot hold the target set and on-demand pull/build is required |
| Deterministic oracle as code | trials grow and verdicts must be machine-comparable without an LLM |
| Separate judge agent | trial volume outgrows one agent's judgment throughput |
| Dashboard / pass@k aggregator | repeated runs exist and the operator wants tables |

## 7. What the toolkit is NOT

- Not a replacement for `analysis/evaluation.py`'s `run_matrix`/`compare`: those measure agent CONFIGURATIONS; this measures END-TO-END vulnerability discovery against benchmark ground truth. They coexist.
- Not a change to polymerhus: the pipeline runs unchanged; the harness only reads its outputs.

## 8. Effort

Four small files + one doc: 1-2 focused sessions to implement and smoke-test one trial on `comfyui`.
The playbook is the largest single artifact and the highest-leverage one: the judgment protocol's precision determines the evaluation's meaning.

## 9. Open choices for the operator

1. Whether the playbook should also define the neutral per-target `operator_kb` content, or the agent derives it from `agent_input` freely. (Freely, with the no-vuln-leak rule, recommended.)
2. Which challenge seeds the first smoke trial. (comfyui, recommended: bundled, deterministic seeds, evaluator already included.)