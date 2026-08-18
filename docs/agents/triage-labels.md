# Triage Labels

The skills speak in terms of five canonical triage roles.
This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Scope

These labels apply to **bugs and proposed enhancements only**.
Issues labelled `workflow` are chained development-workflow tickets, already specified by a plan document under `docs/design/`; they are exempt from triage and must not be given `needs-triage`.

See `docs/agents/issue-tracker.md` for the two issue categories.

## `ready-for-agent` is not a go-signal

Applying `ready-for-agent` asserts that an issue is specified well enough to hand to an agent.
It does not schedule the work and does not authorise an agent to begin.
Scheduling authority belongs to `loop-constraints.md`.

## Notes

- `wontfix` already exists as a stock GitHub label in this repo - apply it, do not recreate it.
- The other four triage labels and `workflow` were created by the setup skill on 2026-07-22.
