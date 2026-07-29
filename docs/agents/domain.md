# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a **multi-context** repo: a `CONTEXT-MAP.md` at the root points to one `CONTEXT.md` per bounded context, with the reasoned ontology and architectural decisions under `docs/design/`.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root - the map of bounded contexts and how they relate.
  Read it first; it tells you which `CONTEXT.md` covers the area you are about to work in.
- **The relevant `CONTEXT.md`** - the per-context domain glossary (the ubiquitous language for that context).
  Today: `src/polymerhus/recon/CONTEXT.md` (L0 attack-surface discovery), `src/polymerhus/analysis/CONTEXT.md` (L1 service/system abstraction), and `src/polymerhus/project_management/CONTEXT.md` (the operator-intent surface).
- **`docs/design/domain-model.md`** - the reasoned ontology the glossaries derive from.
  Read it when you need the WHY behind a term, not just its definition.
- **`docs/design/`** - read the design specifications that touch the area you're about to work in.

If a file the map references does not exist yet, **proceed silently**.
Don't flag its absence; don't suggest creating it upfront.
The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates and sharpens these lazily as terms and decisions get resolved.

## Keep the model current as you build

The ontology and the glossaries are living documents, not a one-time deliverable.
When you introduce, rename, or sharpen a domain term while implementing, update the owning `CONTEXT.md` in the same change - do not batch it up or leave it for later.
When a change alters the reasoned model (a new primitive, a corrected relationship, a resolved open question), update `docs/design/domain-model.md` too.
This is the progressive-update discipline: the map, the glossaries, and the ontology track the code as it evolves, so they never drift into fiction.
See the `## Agent skills` block in `CLAUDE.md` for the binding statement of this rule.

## Contexts are now physical modules

The three bounded contexts are live packages under `src/polymerhus/` after the 2026-07 `src/` restructure (`docs/design/module-restructure.md`): `recon/`, `analysis/`, and `project_management/`.
`analysis` was extracted from under `recon/analysis/` to its own top-level module; `project_management` was minted from the operator surface previously scattered across the API layer and the Postgres gateway.
Run/Job/Phase remain recon vocabulary (they are elements of the recon pipeline, per the operator's ruling); project-management owns the operator's intent over runs, not the pipeline that executes them.

## Helper modules never get a glossary

`neo4j`, `postgres`, `mcp`, and `llm-client` are NOT bounded contexts and will not become independent modules.
They are shared/helper infrastructure (a shared kernel), inherently coupled to the domain modules that consume them, carrying no independent ubiquitous language.
Do not mint a `CONTEXT.md` for any of them, and do not invent a glossary for them (`CONTEXT-MAP.md`, operator's explicit ruling).

## Architectural decisions live in `docs/design/`

This repo has no `docs/adr/` directory.
The closest equivalent to an architecture decision record is a **design specification document** under `docs/design/`.
Where a skill says "read the ADRs", read the relevant design specs instead.

They are longer-form than a classic one-decision-per-file ADR - a single spec typically carries several decisions, often as an explicit numbered ledger (e.g. the `L1D-*` decision ids).
When citing one, cite the decision id where the document provides one, not just the filename.

## File structure

```
/
├── CONTEXT-MAP.md                    ← the map of bounded contexts
├── CODING_STANDARD.md                ← the design principles (DDD)
├── docs/design/
│   ├── domain-model.md               ← the reasoned ontology (glossaries derive from it)
│   ├── module-restructure.md         ← the 2026-07 src/ restructure decision
│   ├── service-system-model-design_1.md
│   ├── l1-domain-model-catalogue.md
│   └── ...                           ← design specifications; the ADR equivalent
├── src/polymerhus/
│   ├── recon/
│   │   ├── CONTEXT.md                ← recon context glossary (L0)
│   │   ├── control/                  ← orchestration (pipeline, jobs, job_agent, ...)
│   │   ├── domain/                   ← the L0 model + sole-writer (curator, types, pod, ...)
│   │   └── crawl/
│   ├── analysis/
│   │   ├── CONTEXT.md                ← analysis context glossary (L1)
│   │   └── l1_curator.py, pod.py, anatomy.py, ...
│   ├── project_management/
│   │   └── CONTEXT.md                ← project-management glossary (operator intent)
│   └── app/                          ← REST API + llm/ provider helpers
├── db/
└── frontend/
```

## Use the owning context's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in the `CONTEXT.md` of the context you are working in.
Don't drift to synonyms the glossary explicitly avoids.
A term defined in one context may mean something different in another (for example the L0 network-service node versus the L1 business `Service`) - use the meaning the owning context assigns.

If the concept you need isn't defined in any glossary or in `domain-model.md`, that's a signal - either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag design-spec conflicts

If your output contradicts an existing design spec, surface it explicitly rather than silently overriding:

> _Contradicts L1D-11 (identity ⊥ membership) in `service-system-model-design_1.md` - but worth reopening because…_

Several of these decisions are also restated as binding invariants in `loop-constraints.md`.
Where the two agree, they are one rule.
Where they appear to disagree, `loop-constraints.md` wins for anything an agent is about to write, and the discrepancy is an escalation.

## Eval dataset

The registry of live e2e targets is `tests/e2e/fixtures/eval-targets.yaml`.
Each target carries a `settings` block (maps onto `settings.recon`: `target_seed`, `auth_context`, feature toggles), an `operator_kb` text block that bootstraps the L1 graph, a `launch.jobs` subset, `environmental_caveats` that drive run configuration, and an `expected_recon` ground-truth sketch.
The eval agent is pointed at one or more target `name`s and applies each mechanically; only `expected_recon` maps to no setting.

## Eval-time technique: bare-IP vhost resolution

When a Project is seeded by bare IP (recon `host` scope mode), a web target routinely 301-redirects the IP to a name-based virtual host (e.g. `10.129.x.x` -> `https://fireflow.htb/`).
On a routing-only VPN the vhost is not in DNS (HTB `.htb` names are an `/etc/hosts` convention), so `httpx -fr` follows the redirect into NXDOMAIN and records nothing, and every downstream web tool that would target the vhost fails to resolve it - the eval under-reports the surface even though the host-seeding control plane is correct.

The eval agent MUST interpose to restore the vhost, and the lever is **name resolution, not routing**.
Virtual-host and TLS-SNI selection are name decisions the origin makes at L7/TLS *after* the packet arrives, so no L3 route or DNAT can pick the vhost - the client must present the name.
Two interpositions, in preference order:

- **Resolution write (preferred):** add `<vhost> <seed-ip>` to the kali container's `/etc/hosts`.
  Every tool then resolves the vhost to the IP and sets DNS + TLS SNI + `Host:` correctly by construction - one write, all tools, present and future.
- **Host-header injection (fallback):** direct each web tool to send `Host: <vhost>` while connecting to the IP.
  Weaker: it needs a flag per tool (no single chokepoint) and does not fix TLS SNI, so an SNI-routing origin still serves the wrong vhost over HTTPS.

This belongs natively in the pipeline orchestrator, not the eval agent.
The seamless form is one "vhost-resolution" step that auto-populates the container-local name map from signals httpx already witnesses - primarily the TLS **certificate CN/SAN** (present at probe time, before any redirect), plus the 301 `Location` and absolute body URLs - so every subordinate web tool inherits it at a single chokepoint.
Until that exists, the eval agent performs the `/etc/hosts` write after httpx; header injection is the fallback only where writing hosts is impossible.
