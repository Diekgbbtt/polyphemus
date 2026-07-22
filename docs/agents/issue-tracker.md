# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues on the `origin` remote (`Diekgbbtt/polyphemus`).
Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` - `gh` does this automatically when run inside a clone.
Note that the local directory is `polymerhus` while the remote repo is named `polyphemus`; always resolve the repo from the remote, never from the directory name.

## Issue categories

Two kinds of issue live in this tracker, and every new issue belongs to exactly one.
Classify before choosing labels.

1. **Chained workflow tickets** - labelled `workflow`.
   Distinct work items produced by `/to-tickets` from a specification, each of which is then broken down into its own implementation plan.
   They are opened already-scoped, so they do NOT enter triage and must not carry `needs-triage`.
2. **Bugs and proposed enhancements** - the stock GitHub labels (`bug`, `enhancement`, `documentation`, `question`) plus the triage vocabulary in `docs/agents/triage-labels.md`.
   These enter at `needs-triage`.

## Where work comes from

Planned work follows one chain, and each link has an owning skill:

```
/to-spec      →  a specification
/to-tickets   →  distinct `workflow` issues, one per work item
per ticket    →  an implementation plan
the loop      →  implementation, one FR area at a time, verifier-gated
one PR        →  per workflow ticket, merged by a human
```

The tracker owns the first two links and the last.
Everything between the implementation plan and the PR is loop territory - see below.

Unplanned work (bugs, enhancements) enters at `needs-triage` instead and is scheduled separately; it does not need a spec.

## Relationship to the loop workflow

Code implementation in this repo runs on the loop discipline (`loop-constraints.md`, `STATE.md`, `loop-run-log.md`, `loop-budget.md`), not on issue labels.
The tracker records and specifies work; it does not schedule it.

- `loop-constraints.md` is the **sole authority** on what an agent works on next.
  Its gates are unconditional: one FR area at a time, no second area until a separate verifier sub-agent has APPROVED the first, the budget cap, and the kill switch.
- `ready-for-agent` is **advisory metadata**.
  It asserts that an issue is specified well enough to hand over.
  It is never a go-signal, and an agent must not begin work merely because an issue carries it.
- Escalations still land in `STATE.md` under `High Priority` (`Waiting on human`).
  An issue comment does not substitute for that.
- Per-iteration outcomes are still appended to `loop-run-log.md`.
  Closing an issue does not substitute for a log entry.
- The loop's worktree discipline (one FR area = one bounded goal in its own worktree) is unchanged.
  Worktrees are an internal working mechanism; they do not each become a branch on the remote.
  The branch that becomes the PR is the ticket's branch.
- The handoff point is the PR.
  Up to it, `loop-constraints.md` governs; at it, the tracker and a human reviewer take over.

## Pull requests as the integration instrument

Every change reaches production through a pull request.
There is no direct push to `main`.

- **Target branch**: `main`, the only long-lived branch. `main` is prod.
- **Granularity**: **one PR per `workflow` ticket.** A ticket's implementation plan may span several FR areas; those land as separate commits (or commit groups) on the one branch, not as separate PRs. Areas that share a file cannot be split into separate PRs without a red intermediate - when that happens, name both areas in the commit message.
- **Branch naming**: `feat/<slug>` for new capability, `fix/<slug>` for defect work, `experiment/<slug>` for exploratory increments.
- **Linking**: put `Closes #<ticket>` in the PR body so merging closes the workflow ticket.

### Who may open, and who may merge

- A loop verifier APPROVAL authorises **pushing the branch and opening the PR**. The agent may do this without asking.
- **Merging to `main` is a human action.** An agent must never merge, and never self-approves its own PR. This preserves the never-auto-merge rule in `loop-constraints.md` verbatim.
- A PR should not be opened while any FR area on its branch is still awaiting verifier approval - the ticket is not done.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

This flag is about **inbound** PRs from external parties being treated as feature requests that enter the triage queue.
This repo receives none, so the flag is `no`.
That is independent of the section above: PRs are central to how work is integrated here, they are simply never a request surface.

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either - resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** - the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only - the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` - the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

The `wayfinder:*` labels are not created yet; create them on first use.
