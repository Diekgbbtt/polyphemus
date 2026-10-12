# ADR: the operator_kb Overview is a skeleton attribute, prepended to each Service

Status: accepted (2026-10-12).

## Context

The comfyui analysis could not map the ComfyUI-Manager Services.
One cause is the L0 surface gap (#353); another is FRAMING: every proposer
reasoned from a Service's `contract` alone, with no view of what the whole
application IS.
Every `operator_kb.md` already carries a `## Overview` paragraph - the macro
description of the deployed solution - but `analysis/scaffold.py` ignored it (it
parsed only `Services`, `Systems`, `Roles`), so the framing never reached the
model.

A Service contract alone cannot tell a proposer that the target is, say, "a
node-graph editor extended with a manager custom node"; the Overview can.

## Decision

The Overview is a first-class SKELETON ATTRIBUTE (operator decision: an
attribute, not a graph node), threaded from the KB to the effective querying
component.

1. **Parse** (`analysis/scaffold.py::parse_overview`).
   Extract the `## Overview` body as whitespace-normalised prose; `""` when
   absent. The pure function is the single source.
2. **Persist** (`scaffold_project`).
   When the deterministic scaffold writes the skeleton it also writes
   `settings.application_overview`. The write is fail-open: a settings failure
   drops the framing, never the skeleton.
3. **Surface** (`analysis/l1_inventory.py::read_l1_inventory`).
   The inventory dict gains the additive key `application_overview`, read from
   settings (not from a `:L1*` label - it is deliberately not a graph node).
4. **Prepend** (the effective querying component).
   The assigner's `_unit_context_block` prefixes `APPLICATION OVERVIEW: ...` to
   the Service unit it is reasoning about, so every harvest is framed by what
   the application is.
5. **Contract** (`analysis/prompts/bootstrapper.md`).
   The in-repo bootstrapper discipline now requires an `## Overview` first.

The in-project bootstrapper is NOT authoritative for the eval: the eval's
`operator_kb.md` is authored by the EXTERNAL bootstrapper
(`tools/eval/kb-authoring.md`, recovered from opencode session
`ses_f8ef9ce44`, 2026-09-05), which the operator adjusts. This change lands the
in-repo contract and the downstream plumbing it requires.

## Consequences

- Every proposer that reads `read_l1_inventory` can frame its reasoning; the
  assigner, the mechanism-typist, and the data-modeller all do so today.
- The Overview is not a graph node, so it is invisible to `graph_view` by
  design; consumers read it from the inventory dict.
- No kb retrofit was needed: all five present `eval/data/webexploitbench/*/
  operator_kb.md` files already carry an `## Overview`.
