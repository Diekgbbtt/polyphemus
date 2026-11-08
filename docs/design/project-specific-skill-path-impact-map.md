# Project-specific skill path impact map

**Status:** done.
**Date:** 2026-10-22.
**Scope:** every component that reads, writes, mirrors, validates, packages, or documents the project-specific skill area.

## Authority

The design bank is authoritative.
The project-specific skill area is the live skills root's `target-specific-procedure` branch:

- `docs/design/auth-store-220-decisions.md`
- `docs/design/eval-data-dependency-placement-decisions.md`
- `docs/design/skills-typed-surface-spec.md`
- `docs/design/skill-evolution-232-decisions.md`
- `docs/design/progressive-skill-lifecycle-adr.md`
- `docs/design/skills-system-decomposition.md`
- `src/polymerhus/app/CONTEXT.md`
- `src/polymerhus/recon/CONTEXT.md`

## Canonical layout

```
<skills_root>/target-specific-procedure/<project_id>/
├── <skill>/
│   ├── SKILL.md
│   ├── references/
│   ├── scripts/
│   ├── assets/
│   └── revisions/          # the revision manifest and snapshots
├── lessons/<skill>.yaml
└── evolution/<pass_id>.yaml
```

The data root is separate:

```
<data_root>/<project_id>/
├── auth/                   # AuthStore: overview.yaml, credentials.yaml
├── usage/
├── analysis/
└── hunting/
```

The data root never carries project-specific skills.
A `<data_root>/<project_id>/skills/` directory is not a runtime location.
It is at most a legacy data-dependency mirror, and the mirror is wrong.

## Source versus runtime

The eval staging tree is an upload source, not a runtime root:

```
<staging>/<target>/auth/{overview.yaml,credentials.yaml}
<staging>/<target>/skills/authn/{SKILL.md,references/...}
```

The `authn-skill` upload normalizes the archive to bundle-relative paths.
The app endpoint writes the bundle through `SkillStore.replace_bundle`.
The runtime destination is therefore:

```
<skills_root>/target-specific-procedure/<project_id>/authn/SKILL.md
```

The auth files go through `AuthStore` to the data root.
The L1 surface goes through the deterministic graph scaffold.
The eval's recon predicate reads the canonical skills root, not a data-root mirror.

## Components

| ID | Component | Current path or behavior | Target | Action | Status |
|---|---|---|---|---|---|
| C1 | `SkillStore.read/list_skills/meta` | Canonical branch plus a `data_root` fallback I added | Canonical project branch only | Remove `data_root`, `_data_project_skills_root`, `_project_skill_roots`, and the fallback | Done |
| C2 | `SkillStore` write, replace, lessons, evolution | Canonical `target-specific-procedure` branch | Canonical | Verify no data-root path | Done |
| C3 | `write_skill` contract and module comments | `data/<project_id>/skills/<skill>/` in `WRITE_SKILL_CONTRACT` and the store comment | `skills/target-specific-procedure/<project_id>/<skill>/` | Correct the contract and comments | Done |
| C4 | `load_skill`, listing, `render_skill_index` | Project-first through `SkillStore`; some comments say data-dir | Canonical | Correct the comments and keep the seam | Done |
| C5 | `auth_capable_binding` and auth-store agents | Explicit project now reaches `skill_agent_binding`; direct refs replace the full index | Canonical via the store | Keep the project fix; remove the index; verify the authn load | Done |
| C6 | `project_management.repository.write_authn_skill` | Writes the canonical bundle and mirrors to `<data_root>/<project>/skills/authn` | Canonical bundle only | Delete the mirror and its `data_root` import | Done |
| C7 | `project_management.data_dependencies`, `api`, `repository` docs | Docs say `<data_root>/<project>/skills/authn` | Canonical skills root | Correct the docs and the endpoint docstring | Done |
| C8 | `app/data_root.py` | Doc lists `skills/` under the data root; scaffold correctly omits it | No skills in the data root | Correct the docstring; keep the scaffold omission | Done |
| C9 | `app/auth/store.py` doc | Says the data root is the same root as the skills | Separate data root and skills root | Correct the docstring | Done |
| C10 | `eval/orchestrator/files.py` `skills_dir` / `authn_skill_path` | Reads `<data_root>/<project>/skills/authn` | Reads `<skills_root>/target-specific-procedure/<project>/authn` | Add a skills-root parameter; update the callers | Done |
| C11 | `eval/orchestrator/predicates.py` and `PhaseState` | Uses the data-root skill path | Uses the skills root | Add `skills_root`; update the predicate | Done |
| C12 | `eval/orchestrator/trial.py` and `TrialConfig` | Uses the data-root skill path; no skills root | Carries `skills_root`; uses the canonical path | Add the field; update `_phase_state` and the trial | Done |
| C13 | `eval/orchestrator/setup.py`, `cli.py`, eval config | Source staging only; no skills root for the read predicate | Skills root for the read path | Add the config/CLI seam and the default | Done |
| C14 | `eval/CONTEXT.md`, `eval/setups/*.yaml`, eval compose | Say the app data root carries `skills/authn` | Data root carries auth; skills root carries the project skills | Correct the docs/comments and mounts | Done |
| C15 | `tools/bootstrap/DATA-DEPENDENCIES.md`, validator, publisher | Call the staging a mirror of the app data dir | Staging is the upload source; the app writes the canonical target | Correct the docs; keep the source and validator | Done |
| C16 | `tools/bootstrap/prompts/data-dep-authn.md` | Says the staging mirrors the app data dir | Staging is the upload source; authn target is the skills root | Correct the prompt | Done |
| C17 | `.opencode/agent/data-dep-worker.md` | Delegates to the phase prompt | Same source/target distinction | Correct or rely on the phase prompt | Done |
| C18 | `skills/meta/authn-skill-writing` | Canonical path in the meta-skill and workflow | Canonical | Verify the tests | Done |
| C19 | `tests/app/test_auth_seams.py` | New test uses `<data_root>/<project>/skills/authn` | Canonical `target-specific-procedure` | Move the fixture and the store root | Done |
| C20 | `tests/project_management/test_data_dependency_endpoints.py` | Asserts the canonical bundle and the data-root mirror | Asserts the canonical only | Remove the mirror assertion | Done |
| C21 | `tests/project_management/test_rest_api.py` and `test_data_root.py` | Canonical path and no data-root skills | Canonical | Verify | Done |
| C22 | `tests/e2e/test_authn_bootstrap_walkthrough.py` docstring | Says `data/<project>/skills/authn` | Canonical | Correct the docstring | Done |
| C23 | `tests/e2e/harness/compose.authn-e2e.yml` | Comment says the bundle lands under the data root | The skills volume carries the bundle | Correct the comment and verify the mount | Done |
| C24 | `docs/experiments/.../PLAN.md` | Says seven targets have `skills/authn` | Clarify whether that is the staging source or the canonical target | Correct the wording | Done |
| C25 | `docs/experiments/.../CONTEXT-LIFECYCLE-FOLLOWUP-PLAN.md` | Task 2 test uses the data-dir path | Canonical | Correct the plan and the test | Done |
| C26 | `docs/experiments/.../CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md` | Authn path references need a check | Canonical | Correct if present | Done |
| C27 | Live eval instance | `data/eval-server-1/<project>/skills/authn` mirror; canonical may exist | Canonical in the app skills root | Verify the canonical; migrate/copy if needed; remove the mirror after verification | Done |
| C28 | Live eval read predicate and trial | Reads the data-root mirror | Reads the canonical skills root | Deploy the corrected eval code/config; verify | Done |
| C29 | Deployment mounts | App `./skills:/srv/skills`; data `./data:/srv/data`; the project branch is a Docker volume | Same skills volume for the app and the eval read path | Verify the compose, the volume, and the eval path | Done |
| C30 | Auth-capable agent project scope | Several call sites fell back to `config.PROJECT_ID` (`default`), so the live `load_skill` saw no project `authn` despite the canonical bundle | Every auth-capable binding receives the run/trial project id | Thread `project_id` through the hunter, idle loop, actors, pod runner/triager, and recon triager; add the live explicit-project verification | Done |

## Work order

1. C1-C5: remove the data-dir fallback and restore the canonical store and agent seams.
2. C6-C9: remove the project-management mirror; correct the data-root and auth-store docs.
3. C10-C14: give the eval a skills root and read the canonical path.
4. C15-C18: correct the bootstrap staging language and the meta-skill references.
5. C19-C26: update the tests and the docs/report/plan.
6. C27-C29: verify the live canonical bundle, the eval read path, and the mounts.
7. Run the targeted suites:
   - auth store and auth seams;
   - skill store, listing, lessons, task binding, project management;
   - eval orchestrator predicates, trial, setup, and API;
   - bootstrap validator and publisher;
   - the e2e path assertions.
8. Update this map's statuses and commit it with the code.

## Acceptance

- No runtime code reads or writes project-specific skills under `<data_root>/<project_id>/skills/`.
- `SkillStore` resolves only the canonical `target-specific-procedure` branch.
- The project-management `authn-skill` endpoint writes the canonical bundle and no mirror.
- The eval `authn` predicate and trial read the canonical skills root.
- The bootstrap staging remains an upload source and is documented as such.
- The live instance has the canonical bundle in the app skills root; the data-root mirror is removed after verification.
- The project `authn` skill is listable and loadable by every auth-store agent.
- All targeted tests pass.
