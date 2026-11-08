# ADR: the trial record names the commit its stack loads

*Status: ACCEPTED (2026-10-25).
New record.
It changes how `eval_sha` is sourced; it does not change the status vocabulary, the store schema version, or the fingerprint formula.*

## Context

A `trial.yaml` did not name the commit that versions the stack.
The field existed (`eval_sha`, D32) and every consumer below it existed: the store refused a record without it, and every verdict and diagnosis row copied it.
The sourcing was the gap.
The value came from `--eval-sha` or `EVAL_SHA`, so the trial recorded what the operator declared, not what the instance loaded.

The declaration drifted in two ways.

1. The UTM driver derived the value from the canonical checkout's `dev` ref.
   Its comment claimed "the live dev checkout is the code the instance mounts".
   The compose files contradict that: `docker-compose.dev.yml` bind-mounts the instance worktree's `src/`, `lightrag/`, `db/`, `skills/`, and `gateway/`, and the compose project's working directory is the instance worktree.
2. A driver that reads the right tree still states a value the trial cannot verify.
   Any gap between the read and the trial start is invisible.

The live instance shows the defect concretely at the time of this record:

- the instance worktree HEAD is `5789ad3f26712c251a53dabb573195e87f62642c`;
- the canonical checkout's `dev` ref is `9e9e852279a7083331ea02b599d4467c5412d52a`;
- the container mounts `/opt/polymerhus-dev/eval/instances/eval-server-1/{src,lightrag,db,skills,gateway}`;
- the instance worktree carries 36 modified and 1 deleted tracked path (1,463 insertions, 531 deletions).

So a trial on that instance would have named a commit the stack did not load, and even the correct commit would not have described the running bytes.

Historical records confirm the field was operator-supplied and not derived: `9d81f7c1` and `6b0c9b59` both carry the identical `stack_fingerprint` `9b158820...`, because the fingerprint excludes the commit by design.

## Decision

The trial starter owns the identity.

- `orchestrator trial` reads the commit HEAD points to in the **Instance worktree** and stamps it as `eval_sha`.
  `instances.plan_head_sha`/`instance_head_sha` own the read; the source is the same tree the compose files bind-mount.
- The read happens at trial start, before the first API call, and it fails loud when the tree or its HEAD is unreadable.
  A record with a null identity can never be written by the starter.
- The starter runs `up`'s first idempotent step (`ensure_worktree`) before the read, so a standalone `trial` on a fresh instance still names its version.
- `--eval-sha`/`EVAL_SHA` becomes a CROSS-CHECK.
  A value that disagrees with HEAD is ignored and recorded as a trial note naming both, because the record must name the loaded code and a stale environment variable must not relabel it.
- The record gains `worktree_dirty`: true when a tracked path differs from HEAD.
  It answers the question the SHA alone cannot: are the running bytes the commit?
  Untracked operator files are excluded, because a `.env.bak-*` or a log is not code the tree loads.
  An unreadable status reports dirty, so the field never claims cleanliness it did not observe.
- The store's run manifest carries `worktree_dirty` beside `eval_sha`, so the durable artifact states the same fact.

The resume path derives the identity the same way, because a resume writes a new trial record.
The surfer's carried `Trigger.eval_sha` remains the failed record's value for its decision document; it is not a source for the new record.

## Why the instance worktree

The **Instance worktree** is the code the stack loads.
`instances.plan_up` runs `git worktree add --detach <worktree> <branch>`, `plan_preflight` and `plan_render` run with `cwd=<worktree>`, and the dev overlay mounts `./src`, `./lightrag`, `./db`, `./skills`, and `./gateway` from that working directory.
The containers' mount sources confirm it on the live host.
The canonical checkout holds the harness and originates the worktrees; it is not what the agent process executes.

## Why not derive the fingerprint too

`stack_fingerprint` stays operator-owned.

- Its historical value is an operator formula (`sha256` over the commit, the two image ids, and the env hash), not the `eval/advance` manifest hash, so a derived value would silently break comparability with every prior trial.
- A faithful derivation needs the running containers' image digests, which means a docker read per trial and a genuine design decision about which images participate.
- The fingerprint is the field that covers a patched tree; making the starter pretend to own it would hide that the patch identity is a separate question.

The pair is the identity, and each half has one owner: the starter owns the commit, the operator owns the content.

## Consequences

- A trial record can no longer be written without a version, because the starter raises instead.
- A stale `EVAL_SHA` in an operator shell produces a note, not a wrong record.
  The two drivers stop exporting it; the UTM driver keeps the fingerprint's own input variable so its historical value survives.
- A dirty instance worktree is now visible per trial.
  The live instance would have shown `worktree_dirty: true` on every trial, which is the truth the SHA alone concealed.
- Old records load unchanged: they simply lack the field, and no consumer requires it.
- The store's `identity_missing` check is unchanged; it now cannot fire for a starter-written record.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| The worktree is cleaned or re-created between `next-target` and `trial` | the recorded HEAD is the new tree's, while the running images may predate it | the fingerprint covers images; the alignment hold is the operator's gate |
| A patched tree looks like its base commit | the SHA under-describes the run | `worktree_dirty` marks it, and the fingerprint covers the content |
| An operator relies on `--eval-sha` to label a rebuild | the flag is ignored and noted | the note names both values, and the operator uses the fingerprint |
| The worktree is absent and the repo/branch cannot be added | the trial refuses to start | the error names the worktree; `up` is the documented first step |
