---
name: webpage-profile
description: Use when an anatomy skill must classify a web frontend's navigation and rendering model from runtime signals for the L1 spine.
---

# Webpage-profile anatomy skill

You reverse-engineer a web frontend into two **independent** typed classifications.
You are a system-anatomy skill (spec §7.6): your output is a *classification*,
its *evidence*, and, when passive signals cannot settle it, a *deeper probe*.

## Where these classifications live (the corrected model)

Both dimensions are **mechanism** classifications, so they live on a `System`, not
on the Service. Specifically, the Service is `EXPOSED_VIA` **one** `WebPresentation`
System that carries `rendering_model` and `navigation_model` as **independent**
props (each with its own confidence + evidence). A mechanism classification is
NEVER stored as a Service prop, and there is no per-rendering-mode System kind and
no `RENDERED_BY` edge - one `WebPresentation` System holds both attributes.
You only produce the two classifications; the sole-writer places them on the
`WebPresentation` System.

## The two dimensions are INDEPENDENT (L1D-31a)

Classify each on its OWN signals. Never infer one from the other.

- `navigation_model` ∈ **SPA | MPA | Hybrid** - how the app moves between views.
  - SPA: URL changes via `history.pushState`, no full-document reload, JSON
    fetches replace the view.
  - MPA: each view is a fresh server Document request (full navigation).
  - Hybrid: some routes navigate as Documents, others as SPA transitions.
- `rendering_model` ∈ **CSR | SSR | SSG | StreamingSSR | HydratedSSR** - how the
  first paint's HTML is produced.
  - CSR: initial HTML is an empty shell (`<div id="root"></div>`); the DOM is
    built entirely by JS after load.
  - SSR: the server returns fully-formed HTML for the route.
  - SSG: pre-rendered static HTML served from the edge.
  - StreamingSSR: HTML streamed in chunks (progressive flush).
  - HydratedSSR: server HTML that JS then hydrates into an interactive app.

A **SPA can be SSR-rendered** and an **MPA can use CSR widgets** - the pairing is
not fixed. Emit the two dimensions separately and let the evidence for each stand
on its own.

## A framework fingerprint alone is NEVER sufficient

A framework marker (`__NEXT_DATA__`, `id="root"`, `ng-version`, `data-reactroot`,
`window.__NUXT__`) tells you the *framework*, not the *behaviour*: Next.js ships
SSR, SSG, and CSR; Angular ships CSR and SSR. If the ONLY thing supporting a
classification is such a fingerprint, you MUST:

1. set that dimension's `*_fingerprint_only = true`,
2. set its confidence to **Low**, and
3. set `probe_reason` to what live interaction would settle it (e.g. "navigate
   /route and watch for a Document request vs a Fetch; render with JS disabled").

Behavioural signals that ARE sufficient: an observed Document-vs-Fetch on
navigation, `Page.frameNavigated` events, the initial-HTML shape (empty shell vs
filled), network resource-type sequence, post-JS DOM diff.

## Output contract

For each dimension emit: the typed value, a `confidence` (High | Medium | Low),
and verbatim `evidence` (quote the actual signals you used). Set the
`*_fingerprint_only` flag honestly. Set `probe_reason` whenever deeper live
interaction is needed - your probe becomes a backward-recon request.

Confidence discipline: **High** only with a behavioural signal; a fingerprint
alone caps you at **Low** with a probe. When signals conflict or are thin, prefer
**Medium/Low + a probe** over a confident guess.
