# Iteration B run state

*Status: complete 2026-10-26T03:11:21Z. The app run stopped at the 7M cap; the trial record says `failed` because the stop POST timed out.*

## Identity

| Attribute | Value |
|---|---|
| Branch commit | `81522a71f3f5fbb0dcd9f9bb3c71d59a5e2b9002` |
| Eval instance | `eval-server-1` |
| Compose project | `ph-dd131acc` |
| Target | `webexploitbench/white-jotter` |
| Target id | `white-jotter-1` |
| Target run id | `iterb-white-jotter` |
| Project id | `dda347be-abea-48e4-94e5-4a4039f41858` |
| Hunting run id | `12d15890-47b2-43c2-bbe3-14c9626a2fdb` |
| Trial record | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/white-jotter-1/white-jotter-1-20261026T031121-1618c524/` |
| Project data | `/opt/polymerhus-dev/eval/instances/data/eval-server-1/dda347be-abea-48e4-94e5-4a4039f41858/` |
| Monitor log | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/monitor.jsonl` |
| Trial log | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/trial.log` |
| Post-run log | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/post.log` |

## Arm values

| Setting | Value |
|---|---|
| Token budget | 7,000,000 capped |
| Risk threshold | `HUNT_RISK_THRESHOLD=110` |
| SkillEvolution | `SKILL_EVOLUTION_ENABLED=0` |
| Pipeline sync | `batched` (the code default) |
| Threat modeller | `opencode-go:deepseek-v4.1-flash`, `xhigh` |
| Hunter | `opencode-go:deepseek-v4.1-flash`, `xhigh` |
| Compaction threshold | `0.4` |
| Recon jobs | `httpx, httpx_reprofile, katana, jsluice, arjun` |

## Final outcome

| Metric | Value |
|---|---:|
| Capped tokens, trial snapshot | 7,017,453 |
| Capped tokens, live usage | 7,022,363 |
| Budget overshoot | 17,453 (0.25%) |
| Calls | 2,459 |
| Recon | complete |
| Analysis | drained |
| Hunting | stopped at the cap; trial record `failed` on the stop POST timeout |
| Units modelled | 3 of 27 |
| Stored threats | 26 |
| Specs | 104 |
| Pod directories | 86 |
| Pod exports | 66 |
| Successful pods | 4 |
| Watchdog envelopes | 58 |
| Pod directories without an export | 20 |
| Official discovery | 0 identified, 1 partial, 6 missed |
| Identification rate | 0.0 |

The app's hunting run finished `stopped` after crossing the capped-token budget.
The trial's `POST /projects/{id}/execution/stop` confirmation timed out, so the trial record says `failed` and records `spend_overshoot: null`.
The spend is 17,453 capped tokens over the cap.

## Failed attempts before this run

All three were configuration-layer failures, not branch defects.

1. The instance path `skills/target-specific-procedure` had been replaced with the tracked directory, so the authn placement check could not see the Docker volume.
2. Replacing the path with a symlink to the volume made the container see the host symlink instead of the named volume, so `SkillStore` refused to create the bundle.
3. The host path was then bind-mounted from the volume, but the orchestrator still read `skills_root` from the canonical `/opt/polymerhus-dev/skills` directory, so the authn check still missed the file.

The repair is configuration-only:

- the host path is a bind mount of `ph-dd131acc_skills-procedures`;
- the container sees a real directory with the same data;
- the trial passes `--skills-root /opt/polymerhus-dev/eval/instances/eval-server-1/skills`.

No branch code changed for these failures.

## Monitoring

The probe read `/projects/{project_id}/usage` and the project data directory every 120 seconds.
It recorded capped tokens, total tokens, calls, the per-agent capped split, threat-file count, spec-file count, and pod-directory count.
The checkpoints caught the modeller halt, the spec depth, the pod budget wave, and the first confirmed symptoms.

## Measurement

The post-run watcher waited for the trial, ran the monitor to convergence, close-verify, store materialize, and `eval/measure_trial.sh`.
The deterministic metrics are in `artifacts/metrics.yaml`.
The measurement report is `artifacts/measurements.md`.
The official verdicts and diagnoses are `artifacts/verdicts.yaml` and `artifacts/diagnoses.yaml`.
The final results are in `RESULTS.md`.
