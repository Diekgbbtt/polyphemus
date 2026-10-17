# WebExploitBench eval data dependencies - build workflow

Status: workflow definition for building the pre-eval data dependencies of all 15 WebExploitBench targets.
This document is the operator-facing contract for the creator and critic subagents; the prompts in `tools/bootstrap/prompts/` implement it.

## 1. What we are building

Three data dependencies per target, the N12 work items of the eval harness:

1. **L1 surface** - the target's business-function `Service`s and cross-cutting `System`s, grounded on the real deployed target.
   Consumed now as `operator_kb.md` (structured prose) through the platform scaffold (`src/polymerhus/analysis/scaffold.py`; the eval CLI wrapper is `eval/scaffold.py`); also emitted as a graph-ready RDF dataset (`l1-surface.yaml`).
2. **AuthContext** - the store's `overview` (login mechanism, defences, required headers, anti-bot, replayability) and `accounts` (credentials, tokens, roles).
   Consumed inline through `target_config.auth` -> `PUT /projects/{id}/auth`.
3. **Project authn skill** - the replayable sign-in/sign-up procedure bundle.
   Consumed as text through `target_config.auth.authn_skill` -> `<data_root>/<project_id>/skills/authn/SKILL.md`.

## 2. Where it lands (assumption)

Two locations, both operator assumptions that may move once the eval symbolic layer's data interface is finalised.

**L1 surface** - the existing per-target eval KB directory, extended:

```
eval/data/webexploitbench/<target>/
  operator_kb.md        # L1 skeleton, consumed by eval/scaffold.py (structured: ## Services / ## Systems / ## Roles)
  l1-surface.yaml       # graph-ready RDF dataset of the L1 units (Services + Systems) and their edges
  surface-map.md        # human-readable crawl notes (existing convention)
  research-notes.md     # human-readable research notes (existing convention)
```

**AuthContext + authn skill** - a staging directory that REPLICATES the app-owned project data dir, so it can be mounted (or copied) as a data root at wire time:

```
eval/data-dependencies/
  <project_id>/         # placeholder project id (the target name; remapped to the real eval project id at wire time)
    auth/
      overview.yaml     # AuthContext overview - SECRET-BEARING when it carries tokens; never commit
      credentials.yaml  # AuthContext accounts - SECRET-BEARING; never commit
    skills/
      authn/
        SKILL.md        # project authn skill (procedure; cites secret NAMES only, never values)
        references/      # login-specific scripts
```

This mirrors `<data_root>/<project_id>/{auth,skills}` exactly, which is the layout the `AuthStore` (`src/polymerhus/app/auth/store.py`) and `SkillStore` read.
No seeding into a live store is required at build time: the creator authors these files directly, and the eval trial seeds them later through `target_config.auth`.

`<target>` is the WebExploitBench target name (`comfyui`, `dify`, ...).

### Secrets policy

`auth/overview.yaml` and `auth/credentials.yaml` hold live tokens and passwords.
They MUST stay out of git: the auth bundles live only in the staging root (default `eval/data-dependencies/`), which is git-ignored; only the redaction-safe `overview` subset is ever committed.
The authn skill cites secret NAMES, never values.

## 3. The L1 surface, two renderings

### 3.1 `operator_kb.md` (consumed today)

The deterministic platform scaffold (`src/polymerhus/analysis/scaffold.py`) parses exactly three sections and ignores the rest:

```
# <Target> (<version>)

## Overview

```yaml
domain: <stable target identity, e.g. wordpress, comfyui - never a per-run host>
description: <one generalised paragraph: what the application is, its deployment model, its audiences>
journeys:
  - name: <canonical end-to-end navigation journey>
    steps:
      - <a concrete surface part: page / form / menu entry / endpoint> (<component identity it exercises: Service business_function_slug or System kind>)
      - <at least 3 steps per journey>
      - <...>
  - <at least 2 journeys>
```

## Services
### <business-function-slug>
- contract: <what it does and owns, domain nouns and verbs; NO paths/URLs/parameters>
- exposure: public | authenticated

## Systems
### <free-form mechanism kind> - <discriminator name>
- description: <what the mechanism is and why it matters adversarially>

## Roles
- <role>
- <role>
```

Notes:
- The `## Overview` is the STRUCTURED entity (Q3, 2026-10-17): a fenced ```yaml
  block with `domain`, `description`, and `journeys`. `domain` is the target's
  STABLE identity (the product/application name); a per-run minted host is not a
  domain. Each journey carries >= 3 steps; each step references a specific
  surface part (endpoint, form, menu entry, page navigation) and, where it
  activates existing L1 knowledge, the component by its KB identity. The whole
  Overview stays <= 250 words over the rendered plain text (domain +
  description + journey names + steps, whitespace-tokenised) - the same
  `polymerhus.analysis.overview` rule the creator self-checks and the critic
  judges with.
- A legacy prose Overview still PARSES at runtime (it maps to `description`,
  fail-open), but it FAILS the validator: the fenced form above is the contract.

Notes:
- `contract` must DISCRIMINATE between services and contain NO path/URL/route/parameter names (the scaffold reads it as the routing profile; a path would enter the graph looking like evidence).
- A System must carry exactly ONE `- description:` bullet: `src/polymerhus/analysis/scaffold.py::parse_kb` is line-based and a second bullet silently overwrites the first.
- A `System` heading whose kind maps to no `SYSTEM_KINDS` value is dropped: prefer vocabulary kinds (`WAF`, `CDN`, `ReverseProxy`, `APIGateway`, `RESTApi`, `GraphQLApi`, `IdentificationSystem`, `IntegrationSystem`, `AuthenticationMechanism`, `AuthorizationSystem`, `WebPresentation`, `Sitemap`).
- Roles land on the `AuthorizationSystem`.
- The three pre-auth service linchpins (`sign-in`, `register`, `password-recovery`) are HARD-forced by the platform; the KB may still name them explicitly.

### 3.2 `l1-surface.yaml` (graph-ready RDF, the future insert path)

The RDF dataset mirrors the corpus's established `l0-surface.yaml` shape (label / identity / props / edges), so it is directly usable in a parametrisable insert query.
`project_id` is the ONE query parameter; it is never baked into the file.

```yaml
target: <target>
observed_at: <iso8601>
base_url: <reachable target root the crawl used>
units:
  - label: Service
    identity: {business_function_slug: <slug>}          # graph identity key
    props: {exposure: public|authenticated, service_contract: <prose>}
    outbound_edges:
      - rel: EXPOSED_VIA | AUTHENTICATED_BY | AUTHORIZED_BY
        target_label: System
        target_identity: {kind: <SYSTEM_KIND>, discriminator: <disc>}
    inbound_edges: []
  - label: System
    identity: {kind: <SYSTEM_KIND>, discriminator: <disc>}
    props: {description: <prose>, roles: [<role>], realms: [<realm>]}
    outbound_edges: []
    inbound_edges:
      - rel: EXPOSED_VIA
        source_label: Service
        source_identity: {business_function_slug: <slug>}
```

Rules:
- `label` is one of the L1 labels (`Service`, `System`).
- `identity` carries exactly the graph identity keys: Service -> `business_function_slug`; System -> `kind`, `discriminator`.
- `discriminator` convention (matches the L1 write boundary, `analysis/bootstrap.py` and `analysis/CONTEXT.md`): the identify/authenticate/authorize linchpins (`IdentificationSystem`, `AuthenticationMechanism`, `AuthorizationSystem`) use the literal `__singleton__`; a `WebPresentation` uses `<business_function_slug>::<cluster>` (one node per service per rendered-page cluster, never one global cluster); any other multi-instance kind uses a short descriptive discriminator with NO target-name prefix. The `discriminator` in `l1-surface.yaml` must equal the name the scaffold derives from `operator_kb.md`.
- `props` carries only valid L1 props; every identity key is unique within the file; every edge endpoint must resolve to a unit in the file.
- Edge `rel` is one of the L1 relations (`EXPOSED_VIA`, `AUTHENTICATED_BY`, `AUTHORIZED_BY`, `CONSUMES`, `PRODUCES`).
- An insert query is `MERGE (n:<label> {<identity>, project_id:$project_id}) SET n += $props` then a relationship MERGE per edge.

## 4. The creator, the order, and the batch critic

One creator subagent per target.
The order is **authn first, L1 second**: the L1 crawl is authenticated, so the authn artifacts must exist before it runs.

- **Phase 1 (authn)** - deploy the target locally, then run the `authn-skill-writing` meta-skill P0-P6 against it; write `auth/{overview.yaml,credentials.yaml}` + `skills/authn/`, including the persisted session `snapshot`. Leave the target running. STOP.
- **Phase 2 (L1, authenticated)** - the same creator is resumed; it reads the AuthContext + skill, authenticates by replaying the persisted session snapshot (falling back to the skill's sign-in procedure with credentials when the snapshot is stale or not portable), then crawls both the anonymous and the post-login surface into `operator_kb.md` + `l1-surface.yaml` + `surface-map.md`/`research-notes.md`. STOP.

Why this order:

- Phase 1 is self-sufficient: it needs only the live target (seeded credentials come from the compose seed files or a freshly minted account), not the L1 surface.
- Phase 2 depends on phase 1 to reach the authenticated services; crawling before authn would leave them unobserved.
- `tools/bootstrap/validate_data_dependencies.py --auth-only --staging <root> <target>` validates phase 1 before `<target_dir>` exists; the full mode (with `--staging`) validates phase 2.

Batch policy: the remaining targets are heavy (dify, mogu-blog-v2, youlai-mall, openmetadata each ~10 services, all amd64 under Rosetta) and the Docker VM is 6 GiB RAM + 3 GiB swap.
Run them **one at a time (batch=1)**: build with nothing else up, tear the target down and `docker system prune -a` between targets.
Batch=2 is only safe at >=8 GiB RAM + 4 GiB swap; the earlier dify failure was two heavy targets contending for 5.1 GiB.

A single critic subagent evaluates each target's L1 (advisory; the operator decides):

1. **L1 coverage** - can the L1 surface, by threat-modelling every service, outline all the target's vulnerability classes? Is the shape correct? Are the authenticated services actually observed and wired to the auth linchpins?
2. **Auth compliance** - reported separately from the L1 critic: do `overview.yaml`/`credentials.yaml` and the authn skill conform to their design specification (`docs/design/auth-store-220-decisions.md`, `skills/meta/authn-skill-writing/SKILL.md`)?

## 5. Local mechanics (Mac)

- Target host: the Mac (`/Users/diekgbbtt/WebExploitBench`), Docker Desktop with Rosetta amd64 emulation.
- Deploy: `export DOCKER_DEFAULT_PLATFORM=linux/amd64` then `scripts/targetctl build <target>` and `scripts/targetctl up <target>`.
- `targetctl` needs bash 4+ (`/opt/homebrew/bin/bash`); macOS bash 3.2 collapses every target's compose project to `web_` and two targets collide.
- Reach the target at the printed `http://0.0.0.0:<port>/` via `127.0.0.1:<port>`.
- Docker VM: 6 GiB RAM + 3 GiB swap (`MemoryMiB=6144`, `SwapMiB=3072`), 8 CPUs. Sufficient for batch=1; batch=2 heavy targets need >=8 GiB RAM + 4 GiB swap.
- Disk is the scarce resource: between targets run `docker rm -f $(docker ps -aq)` then `docker system prune -a -f` (reclaims ~7-14 GiB per heavy target).
