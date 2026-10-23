# Hunting context dedup impact map

## Purpose

This map links the 2026-10-23 context dedup change to the design specs that govern it.
It also records the tool-description decomposition that answers the sharing question.

The decision record is `docs/design/hunting-context-dedup-2026-10-23-adr.md`.
The implementation evidence is `docs/experiments/hunt-enhancement/CHANGES.md`.

## Tool-description sharing

The tool descriptions are shared constants.
The roles bind different subsets.

The measurement method is `sum(len(tool.description))` over the bound surface.
It includes the shared conciseness directive where a tool appends it.
It is not the request-schema character count.

### Before and after

| Role | Before | After, same full auth | Description text cut | Auth-mode cut | Production after | Total cut |
|---|---:|---:|---:|---:|---:|---:|
| Hunter | 22,775 | 13,127 | 9,648 | 4,649 | 8,478 | 14,297 |
| Modeller | 18,594 | 11,499 | 7,095 | 4,649 | 6,850 | 11,744 |
| Runner | 12,979 | 9,750 | 3,229 | 4,649 | 5,101 | 7,878 |
| Triager | 12,715 | 9,486 | 3,229 | 4,649 | 4,837 | 7,878 |

The `After, same full auth` column isolates the shared description compaction.
The `Auth-mode cut` column is the full-to-read-only auth-store switch, not description text.
The full auth-store description remains 5,291 chars.

### Shared and role-local tools

| Tool | Shared by | Text cut |
|---|---|---:|
| `load_skill` | all four | 1,166 |
| `record_skill_lesson` | all four | 699 |
| `graph_view` | hunter, runner, triager | 862 |
| `query_lightrag` / `kb_query` | hunter, runner, triager | 358 |
| `search_http_history` | hunter, modeller | 2,304 |
| `get_http_artifact` | hunter, modeller | 1,414 |
| `exec` | hunter, modeller | 964 |
| `skill_list` | hunter, modeller | 244 |
| `skill_load` | hunter, modeller | 160 |
| `note` / `notes` conciseness cap | all four | 144 to 654, role text differs |
| hunter `hunts_store` | hunter only | 823 |
| modeller `hunts_store` | modeller only | 0 |
| pod `exec` | runner only | 0 |

The shared text cut for each role is the sum of the tools it binds.
The sharing claim is correct.
The modeller's 11,744-char cut is 7,095 shared text plus 4,649 auth mode.
It is not a modeller-only edit.
The runner and triager receive the same 3,229 shared text cut and the same auth-mode cut.

`replay` is bound only when the runner has a replay seam.
Its description fell from 2,161 to 1,718 chars, a 443-char cut.
It is additional to the runner total when bound.

## Design impact

| Change | Code or prompt | Design spec | Section | Action |
|---|---|---|---|---|
| Loop tool surface removed | `hunting_agent.py` | `hunting-67-hunting-agent-spec.md` | 8.5, 8.7 | Updated |
| Hunter one instance-context first message | `hunting_agent.py` | `hunting-67-hunting-agent-spec.md` | 8.7 | Updated |
| First human pinned through compaction | `app/llm/compaction.py` | `context-compaction-95-decisions.md` | new D13 | Updated |
| Spec body generated from typed models | `hunter_tools.py`, `hunting-agent.md` | `hunting-67-hunting-agent-spec.md` | 8.6 | Updated |
| `skills` and full provenance documented | `hunter_tools.py`, `pod/types.py` | `hunting-67-test-executor-pod-spec.md` | 8.4 | Updated |
| Technical sharpening projection | `hunting_agent.py` | `hunting-67-hunting-agent-spec.md` | 8.7 | Updated |
| Phase hint transition-only | `hunting-agent.md`, `hunting_agent.py` | `hunting-67-hunting-agent-spec.md` | 8.5 | Updated |
| Tool-description budget and sharing | tool modules | `hunting-tools-design.md` | new policy section | Updated |
| Auth store read-only for hunting roles | auth seams, pod agents | `auth-store-220-decisions.md`, `analysis-auth-store-view-364-adr.md` | amendments | Updated |
| Modeller tool list and 5xx pointer | `threat-modeller.md` | `hunting-67-threat-modeller-spec.md` | 5.5, new 13 | Updated |
| Pod tool lists and auth store | pod prompts, pod agents | `hunting-67-test-executor-pod-spec.md` | 1.4, new 8.12 | Updated |
| 5xx directive pointer on `exec` | `hunter_tools.py` | `hunting-target-front-availability-adr.md` | decision 2 | Updated |
| Cache interpretation | measurement only | `session-cache-measurement-348-adr.md` | amendment | Updated |
| Spec field list superseded pointer | merged spec | `hunting-67-per-agent-specs-spec.md` | 7 | Pointer added |
| Reports and no-trial state | experiment docs | `hunting-context-dedup-2026-10-23-adr.md` | context, residual | Recorded |

## Uncommitted parallel work

The worktree also carries uncommitted parallel edits to the HTTP-history row projection, the suite-skill filter, and the sanitizer.
Those edits are not part of this change.
They are not mapped in the design updates above.
They must be reviewed and committed on their own branch or explicitly integrated later.
