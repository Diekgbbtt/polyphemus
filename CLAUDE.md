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

### E2E eval targets

The eval dataset is `tests/e2e/fixtures/eval-targets.yaml` - the registry of live targets for end-to-end runs.
Each target's fields map onto `settings.recon` (`target_seed`, `auth_context`, `operator_kb`, feature toggles) plus the `POST /recon` job subset; the eval agent applies one target's `settings`/`launch` mechanically and asserts against its `expected_recon` ground truth.

### Work authority

`loop-constraints.md` is the sole authority on what an agent works on next.
No label, including `ready-for-agent`, starts work on its own.

### Integration

Every change reaches prod through a pull request against `main`; there is no direct push.
One PR per `workflow` ticket.
A verifier APPROVAL authorises opening the PR;
See `docs/agents/issue-tracker.md`.
