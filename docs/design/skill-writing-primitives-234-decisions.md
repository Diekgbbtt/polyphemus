# Skill-writing primitives - implementation decisions (#234)

The grilled decisions behind the #234 build, recorded per the workflow (Step 2a/3).
Base description: the body of issue #234; prior draft `progressive-skill-lifecycle-system.md` (the decision ledger the spec refines).
Companion specs: `skills-typed-surface-spec.md` and `skill-runtime-loading-222-decisions.md` (the #222 loader/frontmatter rules, which govern).
Naming note: the draft's `update_project_skill` (§7) is the spec's `write_skill`; one tool, renamed, contract unchanged.

## D234-1 - data-root ownership

One shared app-layer module owns the data root and every scaffold directory: `src/polymerhus/app/data_root.py`.
`ensure_data_root()` runs at system bootstrap (`app.main` startup); `ensure_project(project_id)` runs at project creation (`project_management.repository.create_project`, scaffold first so a project row always has its directories).
Both create-if-absent and idempotent; neither removes nor overwrites existing state.
`project_id` is validated as one safe path component (separators, control chars, dot-traversal refused).
The scaffold is `skills/`, `hunting/orchestration/`, `hunting/hunter/`, `hunting/test-executor-pod/` - adding a module dir is a change here, never in a module store.

## D234-2 - store code home

The skill store lives in the skills-access module alongside the loader and both tools (`src/polymerhus/recon/domain/skills.py::SkillStore`).
Loader, store, writer, and protocol injection are one domain and cannot drift.
The store is explicit-root (the #220 auth-store / hunting notes-store precedent): production defaults to the app-owned `DATA_ROOT`, tests inject temp roots.

## D234-3 - loader resolution order

Reads resolve the per-project bundle first, then the shared repo catalogue (`SkillStore.read`, project-aware `build_load_skill_tool`).
A project skill shadows a shared one without copying; a project with no bundle reads the shared skill unchanged.
Reads are fail-open to the fallback, exactly like `skill_for`.

## D234-4 - the write_skill contract (amended by D234-12)

`write_skill(skill, target, content, source_note_ids=[])`.
`target` is the typed surface only: `procedure` rewrites the whole `SKILL.md`, `references/<name>` writes one reference file (`<name>` one safe file stem).
No section granularity, no operation verbs, no rationale field; `source_note_ids` rides the tool surface as a mechanically logged parameter (recorded on the write log, never consulted) with zero prose: no description, contract, or instruction verbatim may reference it.
The factory binds `project_id` only; any skill in the project's bundle is writable (D234-12).
The agent seam helper (`build_skill_tools`) returns `load_skill` for every agent plus project-bound `write_skill` only for agents whose procedure evolves a skill; a write tool without its project is a fail-fast wiring defect.
This is the TOOL collector's contract - which roles call it at all is the roster's decision (ADR A9): a role with no bearing skill is exempt and binds nothing, `load_skill` included.
Writes create the bundle on first use, re-validate frontmatter (data-section keys plus `name` == the bundle directory), and land atomically (temp file in the same dir + `os.replace`) under a per-project lock.
Every refusal is a denoted `ValueError` mapped to a coded in-band envelope (`skill_invalid`, `skill_target`, `store_unavailable`); nothing raises into the turn.

## D234-5 - protocol injection seam (amended by D234-13)

The `meta-usage-skill` body is appended by the skill read path itself, as a tool-internal output extension inside `build_load_skill_tool` (the draft's recommended option).
Composition is pinned: loader-identical body, `PROTOCOL_SEPARATOR` (`\n\n---\n\n`), protocol body.
Appended to the read of any skill, project or shared: no separate protocol reads, no shadowing - the appended protocol always reads from the shared catalogue, so a per-project bundle can never rewrite the judge.
The two meta-skills themselves load bare (no protocol on the protocol skills: no blackloops).
Three fail-open caveats preserve pinned contracts: a missing protocol appends nothing, an unknown skill still degrades to `''` (there is no loaded procedure to assess).

## D234-6 - removed grey-point checks (see D234-12)

No size caps and no secret-shaped refusal: both were purely heuristic checks (an arbitrary byte cap, pattern-guessed secrets) and are removed rather than tuned.
Compactness is taught by the authoring rules (`procedure` prose plus `references/` pointers), not enforced by the writer; credential placement is the auth store's contract, not the skill writer's guess.

## D234-7 - loader cache key

The loader cache is keyed by `(name, fallback)`: the same missing skill read with two different fallbacks is two distinct requests, so an earlier cached miss can never override the fallback a later caller asked for.
All pinned #222 cache behaviours (identity on repeat reads, `clear_cache`, refresh) hold unchanged.

## D234-8 - binding scope on this base

Per-agent binding of auth-executing agents rides the #223/#224 consumer tickets through `build_skill_tools` (`with_write_skill=True` for agents whose procedure evolves a skill); no agent is rewired here because the auth-phase agents those tickets build do not exist yet.
The L1 skill-index middleware is #222's in-flight seam and composes with this helper at the agent owner's binding site - it is not reimplemented per agent here.

## D234-9 - meta-skill authorship

Both meta-skills were authored by a specialised skill-writing subagent against the `writing-great-skills` bar (compact, no sediment, no no-ops, positive instruction, disclosure ladder).
`meta-write-skill` is content-stable: it describes only the stable contract (targets, frontmatter shape, observables, pointers) with no transitory language, so the future `SkillEvolver` reuses it unchanged.
`meta-usage-skill` is deliberately transitory and compact (it rides every load): assess against stated observables, separate skill defect from execution miss, write directly through `write_skill`; only its body changes at the #232 migration.
Authoring rules live only in `meta-write-skill`, the assessment protocol only in `meta-usage-skill` (one source of truth per meaning, pointer between them).

## D234-10 - hunting migration DEFERRED (conflict, needs operator ruling)

The spec's data-root layout moves the hunting buckets from the hunting-owned root (`attack/hunting/data/<pid>/{orchestration,hunter,test-executor-pod,projects}`) to the app-owned `<codebase_root>/data/<pid>/hunting/{orchestration,hunter,test-executor-pod}` (with the notes bucket's `configs.yaml`/`notes.yaml` folding into `orchestration/`), the stores dropping scaffold `mkdir`, and existing data migrating seamlessly.
That move is NOT built here: it overturns pinned, ratified contracts - the fixed `HUNT_STORE_ROOT` / `HUNTER_MEMORY_ROOT` / `HUNTING_DATA` roots asserted by name in `tests/attack/test_hunt_store.py`, `tests/attack/test_hunting_runtime.py`, and `tests/integration/test_orchestrator_candidates_rewrite_contracts.py` (C15: default root fixed, no env-var indirection) - and it orphans live accumulated memory unless paired with a verified data migration this session cannot e2e against a live stack.
The `ensure_project` scaffold already reserves the target buckets (fail-safe, idempotent, harmless while unused).
The migration is precise follow-up scope: repoint the three default roots to `DATA_ROOT`, insert the `hunting/` level in `_project_dir`, fold the notes bucket into `orchestration/`, add an idempotent old-to-new move run at bootstrap, update the pinned-root assertions - then rule on the ratchet conflict here.

## D234-11 - base-branch note

This change is branched off the committed `feat/222-skill-load-tool` tip (operator ruling).
The #222 in-flight reorganisation (flat `skills/` layout, loader at `app.llm.skills`, `metadata.version` frontmatter) is uncommitted on that branch and is NOT assumed here: catalogue skills keep their nested loader paths and the `inputs` data-section contract, and the meta-skills are flat entries the current loader already resolves.
Rebasing onto the #222 reorg, when it lands, touches paths and the loader home but not the store/tool/seam contracts built here.

## D234-12 - operator correction: no writable set, no heuristic refusals

The per-skill writable set and its `skill_read_only` refusal are removed: they are wrong and irrelevant while the future SkillEvolver must be able to write any skill.
Whether an agent may write at all is decided at the seam (the agent is given `write_skill` or it is not), not per skill name.
The secret-shaped (`secret_refused`) and size-cap (`size_exceeded`) refusals are removed with it: both were purely heuristic checks, and heuristic refusals misfire on legitimate procedural content.
The writer keeps its structural guarantees - typed surface, frontmatter re-validation, atomicity under a per-project lock, and the three structural envelopes (`skill_invalid`, `skill_target`, `store_unavailable`).
The meta-skills were rewritten to the corrected contract and reframed: `meta-write-skill` teaches extending/correcting an already-existing skill from run experience (missing target detail added, contradicted content pruned) with writing-great-skills concepts as the instrument; both files are ultra-compact, dense verbatim, with `meta-usage-skill` the most compact since it rides every load.

## D234-13 - operator rulings: protocol scope, envelope single-sourcing, sharp usage restriction

No shadowing, no separate protocol reads: the usage protocol is appended to the read of any skill (project bundle or shared catalogue) and always reads from the shared catalogue; both meta-skills load bare to prevent blackloops (feedback self-judgement).
The envelope mapping is single-sourced in the `write_skill` tool description (`WRITE_SKILL_CONTRACT`): the `meta-write-skill` step-4 Observable points at the contract instead of restating it.
The `meta-usage-skill` step-3 Observable names the three codes (`skill_invalid`/`skill_target`/`store_unavailable`) as the sharper restriction - deliberate hot-path tokens per operator ruling, the one sanctioned duplication.
Settled on operator rulings: (a) claim criticality - every divergence/lack claim must be grounded on objective evidence, defensible from any perspective, unbiased by role and execution path, so weak additions are never added and solid additions never pruned for mere non-experience (wording inspired by the critical-thinking-logical-reasoning bar); (b) content-only revisions - the reading agent receives skill text, never frontmatter metadata, so a revision touches content only and version/identity stay symbolic; `source_note_ids` is a reserved parameter with no notes system behind it, and no ambiguous verbatim about drawn-on notes may live anywhere in the system.
Open: nothing structural. Oscillation assessed post-criticality and found structurally handled: a prune needs objective contradiction (never mere non-experience) behind a keep-test demanding recurrence-or-trigger plus evidence defensible from any perspective, with zero-skip defaulting to no write - the unevidenced flip-flop has no path, while evidenced adaptation stays allowed. Residual is compliance-only (an agent fabricating objectivity), falsifiable post-hoc from traces: Tier-2 monitor, no prose action.

## D234-14 - A3 frontmatter alignment and `source_note_ids` surface

The data-section contract is aligned to the session ADR A3 (`progressive-skill-lifecycle-adr.md`), replacing the repo-dialect shape this branch inherited.
Keys are now exactly `name` (non-empty, **equal to the skill directory** - the leaf of the loader path), `description` (non-empty), and `metadata` (a mapping carrying a non-empty string `version`).
The structured `inputs` list is dropped: the body describes invocation context better than a schema stub, and no production consumer read it (only the validator touched it).
`name == directory` is enforced in `validate_skill` (it was previously deliberately not required), so five catalogue skills whose durable `name` was a long descriptive phrase were renamed to their directory leaf: `assigner-ownership-judgment` -> `assigner`, `bootstrapper-solution-architecture-projection` -> `bootstrapper`, `post-recon-curation` -> `curation`, `data-plane-modelling` -> `data-plane`, `technical-system-mechanism-typing` -> `technical-system`.
This is the pre-rebase alignment with #222's reorganisation (D234-11); it removes, rather than widens, the eventual rebase delta.
`source_note_ids` rides the `write_skill` surface as a mechanically logged parameter (recorded on the write log, never consulted) with zero prose: no contract, tool-description, README, or skill verbatim references it, pinned by `test_source_note_ids_rides_the_surface_with_zero_prose`.

## D234-15 - operator rulings: metadata ownership, version bump, migration target

Frontmatter metadata is **not** authored by `write_skill`: skill bootstrap (the creation of a skill with its metadata) happens in the shared catalogue under operator authorisation, so a write assumes the required metadata already exists.
A `procedure` write therefore carries content only; the store owns the frontmatter, carrying the existing `name`/`description` and updating `metadata.version` monotonically by +1 per write, so version history plus traces give rollback and tracking.
Consequence: `write_skill` no longer authors or validates the A3 top-level key set (that remains catalogue hygiene in the conformance sweep); the writer boundary only maintains the metadata it carries.
The hunting data layout moves onto the app-owned root: target is `<DATA_ROOT>/<project_id>/hunting/{orchestration,hunter,test-executor-pod}`, exactly the `PROJECT_SCAFFOLD` shape D234-1 already reserves; the live per-project trees are copied, verified, and then the old tree is deleted completely (`copy-verify-delete`), and the per-store lazy `mkdir` sites reduce as the app-owned scaffold takes ownership.
`fault-kb.yaml` moves to `<DATA_ROOT>/hunting/fault-kb.yaml` (shared, non-project): the `.gitignore` gains an exception for it, the `fault_kb.py` `importlib.resources` loader is rewritten to a filesystem read, and the image build must copy it.
Bootstrap is strictly a manual, operator-authorised act - it is never something the runtime passes over - so on a project bundle's first update the frontmatter is simply **copied over from the shared catalogue skill of the same name**, and every write then bumps `metadata.version` by one minor (`major.minor`, one decimal place: `1.0` -> `1.1`).
No component synthesises metadata: the store refuses `skill_invalid` when neither the project bundle nor the catalogue carries bootstrapped metadata.

## D234-16 - hunting migration executed

Built and run: the three root constants (`HUNT_STORE_ROOT`, `HUNTER_MEMORY_ROOT`, `HUNTING_DATA`) are deleted and unified behind one resolver, `app.data_root.project_dir(project_id, relative, root=...)`, which reads the same `PROJECT_SCAFFOLD` the scaffold creates.
`PROJECT_SCAFFOLD` now enumerates the whole FIXED hunting skeleton (`hunting/orchestration/hunt_configs/{produced,consumed}`, `hunting/hunter/test-specs`, `hunting/test-executor-pod`), so the stores create no fixed directory: only a path keyed by a runtime id (a hunt fault key, a pod spec id) is created lazily, and only its own leaf (B10's safety-net allowance).
`fault-kb.yaml` moved to `data/hunting/fault-kb.yaml`: `.gitignore` carries the one exception, the `fault_kb.py` `importlib.resources` loader is rewritten to that fixed path, the Dockerfile copies `data/` to `/srv/data`, the dev compose mounts `./data:/srv/data`, and a missing provisioned catalogue now fails CLOSED (`FaultKBCatalogueMissing`, plus a boot check in `app.main`).
`tools/hunting/migrate_hunting_data_root.py` performed the copy-verify-delete on the live checkout: 145 per-project memory files across 3 projects plus the catalogue moved onto `<codebase_root>/data`, and the legacy module `data/` package was removed.
