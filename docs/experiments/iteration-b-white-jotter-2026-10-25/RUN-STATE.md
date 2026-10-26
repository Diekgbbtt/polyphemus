# Iteration B run state

*Status: running. Started 2026-10-25T21:55:50Z.*

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
| Trial record | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/white-jotter-1/` |
| Project data | `/opt/polymerhus-dev/eval/instances/data/eval-server-1/dda347be-abea-48e4-94e5-4a4039f41858/` |
| Monitor log | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/monitor.jsonl` |
| Trial log | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/trial.log` |

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

The probe reads `/projects/{project_id}/usage` and the project data directory every 120 seconds.
It records capped tokens, total tokens, calls, the per-agent capped split, threat-file count, spec-file count, and pod-directory count.

## Next checkpoint

The first checkpoint after recon starts should show the recon agent's capped tokens and the first L0/L1 artifacts.
The hunting checkpoint should show the threat files and the modeller's share of the capped budget.
