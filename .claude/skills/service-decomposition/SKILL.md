---
name: service-decomposition
description: Use when an L1 umbrella Service bundles several discretely-testable functions or conflates distinct auth_contexts (a public surface hidden behind an authenticated node), and it must be drilled into finer subordinate services during Phase-A.2.
---

# Service decomposition ("screaming" decomposition)

Status: DESIGNED-NOT-BUILT / DRAFT. Full design: `docs/design/service-decomposition-A2.md`.

## Overview

Drill a coarse umbrella `Service` into finer SUBORDINATE services that each scream a discrete business/technical function and carry their own disambiguated auth_context.
Additive and convergent: mint leaves, link each to its umbrella by a `DECOMPOSES` edge, write nothing to Layer-0.

## The one test: split only on a discretely-testable axis

Split an umbrella into a leaf ONLY when the leaf differs from its siblings on one of these axes:

- **auth_context** - a different exposure (`public` vs `authenticated`) or a different gating mechanism.
- **trust boundary** - it produces/consumes data a sibling does not.
- **role/realm gate** - a different role or realm reaches it.

If two candidate leaves would be tested identically (same exposure, same gating mechanism, same data owner), they are ONE service. Do not split them.

## Worked examples (from the eval)

| Umbrella | Decompose? | Result |
|---|---|---|
| daytona `human-access` (auth) | YES - auth_context axis | `human-access-preview-url` (**public**), `-ssh`, `-web-terminal`, `-vnc`, `-vpn` (authenticated) |
| moodique `product-page-and-reviews` (auth) | YES - exposure axis | `product-page` (**public**), `product-reviews` (authenticated) - rescues the hidden public surface |
| daytona `agent-tools` (auth) | NO / minimal - 8 tools, ONE Toolbox auth_context | keep whole, or at most split on a real trust axis (interactive-session vs state-mutation); never one leaf per tool |
| daytona `secrets` (auth) | NO - coherent single auth_context | leave whole |

The canonical win: `human-access` and `product-page-and-reviews` each hide a PUBLIC surface behind an authenticated umbrella. Splitting on the auth_context axis stamps the public leaf `exposure=public` and stops the umbrella flipping the whole node closed.

## auth_context per leaf

Stamp each leaf its own `exposure` (`public`/`authenticated`) - that is the only auth prop on a Service.
The specific mechanism (SSH-token vs preview-token vs public signed URL) is a `System` reached by `AUTHENTICATED_BY` / `AUTHORIZED_BY`, owned by the TechnicalSystem Analyser - never a prop on the Service (mechanism-as-System, `CODING_STANDARD` §1).
Record a suspected mechanism only as a transient Langfuse `claim`.

## Termination guard

- One level deep per umbrella. No recursive subdivision (that is Phase-B).
- A candidate that maps 1:1 to a single endpoint, parameter, or header is over-decomposition - reject it; it is an `AGGREGATES` target or a `DataItem`, Layer-0's job.
- A coherent single-auth_context, single-trust umbrella is NOT decomposed - it flags nothing.

## Identity

The leaf is keyed on its OWN `business_function_slug`, linked up by a `DECOMPOSES` edge (identity independent of the parent). Never encode the parent in the leaf's slug (identity ⊥ membership).

## Common mistakes

- Atomising `agent-tools` into one leaf per tool -> they share ONE auth_context; that is over-decomposition.
- Storing "requires SSH token" on the Service -> category error; that is a `System` edge.
- Splitting a coherent umbrella because it "feels" big -> size is not an axis; testability is.
- Letting an umbrella's single `exposure` stand when a bundled function is public -> the exposure-flip bug; split and stamp the public leaf.
