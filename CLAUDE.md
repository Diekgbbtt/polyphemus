# polymerhus

## Agent skills

### Issue tracker

GitHub Issues on `origin` (`Diekgbbtt/polyphemus`), via the `gh` CLI.
Two issue categories: chained workflow tickets (`workflow`) and bugs/enhancements.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels, applied to bugs/enhancements only.
`workflow` tickets are exempt from triage.
See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context. `CONTEXT-MAP.md` at the root maps the bounded contexts (recon, analysis, project-management) to their per-context `CONTEXT.md` glossaries under `src/polymerhus/`.
The reasoned ontology is `docs/design/domain-model.md`; the design principles are `CODING_STANDARD.md`; architectural decisions live in `docs/design/`.
See `docs/agents/domain.md`.

**Keep the model current as you build.** The ontology, the context map, and the glossaries are living documents.
When you introduce, rename, or sharpen a domain term while implementing, update the owning `CONTEXT.md` in the same change - do not defer it.
When a change alters the reasoned model (a new primitive, a corrected relationship, a resolved open question), update `docs/design/domain-model.md` too.
Provisional terms not yet ratified by the operator (currently the phase-3 `fault-hypothesis` / `testing technique` / `probe` / `vulnerability` vocabulary and the "escalating epistemic ladder" framing) stay marked as such until ratified. The fault-hypothesis is a phase-3 testing primitive, not a graph node or edge.

### Decision records (the commit gate)

Every change ends with a documentation pass, **before the commit, not after** - on par with lint and tests:

- **Record the design decisions** the work took as an ADR under `docs/design/` (or amend the owning design doc), so the reasoning is durable and reviewable.
- **Refine or amend superseded decisions.** When a change contradicts an earlier decision, update that record or mark it superseded in the same change; never leave two contradicting decisions live.
- **Update every impacted document** - the owning `CONTEXT.md` glossaries, `docs/design/domain-model.md`, and any spec or ADR the change touches.

A change is not ready to commit until this pass is done and the impacted docs land with it (a dedicated documentation commit in the same change is fine).

### E2E eval targets

The eval dataset is `tests/e2e/fixtures/eval-targets.yaml` - the registry of live targets for end-to-end runs.
Each target's `settings` map onto `settings.recon` (`target_seed`, `operator_kb`, feature toggles) plus the `POST /recon` job subset, and its `auth_context` seeds the shared auth store via `PUT /projects/{id}/auth` (the settings blob carries no auth, #243); the eval agent applies one target mechanically and asserts against its `expected_recon` ground truth.
The eval harness's own benchmark datasets are keyed artifacts: `eval/datasets/<id>.yaml` declares a dataset, `eval/targets/<dataset>/<target>.yaml` its target bring-up, `eval/platform/<dataset>/` its platform bank, and `eval/data/<dataset>/<target>/` its data dependencies.
Target images are bound to canonical tags `ph/<dataset>/<target>[:<service>]` (spec #301).

### Work authority

`loop-constraints.md` is the sole authority on what an agent works on next.
No label, including `ready-for-agent`, starts work on its own.

### Integration

Every change reaches prod through a pull request against `main`; there is no direct push.
One PR per `workflow` ticket.
A verifier APPROVAL authorises opening the PR;
See `docs/agents/issue-tracker.md`.
