---
name: webpage-analysis
description: Identify the architectural profile of a web application by analyzing delivered HTML, network behavior, and browser/CDP runtime signals.
metadata:
  version: '1.0'
---

# Web Application Profiling Skill

Classify **independently** (the pairing is never fixed - a SPA may use SSR, an
MPA may use CSR widgets):

1. **Navigation architecture**
   - SPA
   - MPA
   - Hybrid

2. **Rendering architecture**
   - CSR
   - SSR
   - SSG
   - Streaming SSR
   - Hydrated SSR

---

# Inputs

Weigh this evidence, behavioural signals first, fingerprints last:

- Initial HTML response
- Browser DOM after JavaScript execution
- Network requests
- Navigation events
- JavaScript execution behavior
- CDP events
- Performance entries
- Framework fingerprints

---

# Outputs

## Application Profile

Per dimension emit the typed value, a `confidence` (High | Medium | Low), and
the observable signals that caused it - every classification carries its
evidence.

---

# Decision Matrix

## Navigation Architecture

### SPA

#### Definition

Client controls routing and navigation without loading new HTML documents.

#### Positive Signals

- Internal navigation changes URL without a new **Document** request.
- `history.pushState()` or `history.replaceState()` observed.
- CDP `Page.frameNavigated` is **not** triggered during route changes.
- Navigation generates Fetch/XHR/API requests instead of HTML documents.

#### Network Pattern

Initial load

- Document request
- JavaScript bundles
- CSS

Subsequent navigation

- Fetch
- XHR
- GraphQL
- JSON

#### Example

Clicking `/products`: URL changes -> `GET /api/products` -> no `GET /products` document request.

#### Typical Threats

Client state manipulation, API authorization flaws, token storage exposure, hidden route discovery.

---

### MPA

#### Definition

Server controls navigation.

Every route loads a new HTML document.

#### Positive Signals

- Every navigation generates a request with resource type **Document**.
- Full HTML response received for each route.
- No client-side router behavior observed.

#### Network Pattern

Every navigation

- Document GET
- HTML response
- Page reload

#### Example

Clicking `/profile`: `GET /profile` -> complete HTML page returned.

#### Typical Threats

CSRF, session management flaws, server-side template injection, HTML injection.

---

### Hybrid

#### Definition

Application contains both client-side and server-side navigation.

#### Positive Signals

- Some routes use `pushState()` + Fetch.
- Some routes trigger full document navigation.

#### Example

Dashboard navigates by SPA routing; authentication reloads the full server page.

#### Typical Threats

Combination of SPA and MPA attack surfaces.

---

# Rendering Decision Matrix

## CSR

### Definition

Browser constructs the page from JavaScript and API responses.

### Positive Signals

#### HTML Response

- Minimal HTML shell.
- Empty application root.

Example

```html
<div id="root"></div>
```

#### Runtime

- Large DOM mutations after JavaScript execution.
- UI appears only after JavaScript bundles execute.

#### JavaScript Disabled Test

Result

- Blank page
- Loading screen
- Unusable application

### Example

Initial response `<div id="app"></div>` -> JavaScript requests `GET /api/users` -> DOM constructed dynamically.

### Typical Threats

DOM XSS, prototype pollution, client-side logic manipulation, dependency supply-chain compromise.

---

## SSR

### Definition

Server generates final HTML before sending it to the browser.

### Positive Signals

#### HTML Response

Meaningful content already exists.

Example

```html
<h1>Products</h1>

<li>Phone</li>

<li>Laptop</li>
```

#### Runtime

JavaScript enhances the page but does not build it from scratch.

### Example

Document response already contains the visible application.

JavaScript only adds event handlers.

### Typical Threats

Server-side template injection, HTML injection, cache poisoning, server rendering DoS.

---

## SSG

### Definition

HTML is generated during build time and served as static content.

### Positive Signals

- Complete HTML
- Rarely changing content
- Minimal server computation

### Example

Static documentation website.

### Typical Threats

Stale content, static asset compromise, client-side vulnerabilities.

---

## Hydrated SSR

### Definition

Server renders HTML first.

JavaScript later attaches client-side behavior.

### Positive Signals

Sequence

1. Complete HTML received
2. JavaScript bundles downloaded
3. Hydration performed

#### Framework Fingerprints

- `__NEXT_DATA__`
- `__NUXT__`
- Hydration payloads

### Example

Product page immediately visible -> React hydrates -> buttons become interactive.

### Typical Threats

All SSR threats, DOM XSS, hydration mismatch, serialization flaws.

---

## Streaming SSR

### Definition

Server progressively streams HTML while rendering.

### Positive Signals

- Incremental HTML delivery
- Chunked transfer encoding
- Progressive page rendering

### Typical Threats

SSR threats, partial response cache issues, rendering resource exhaustion.

---

# Analysis Procedure

Work the steps in order; each step ends with its done-when.

## Step 1 - Inspect Initial Document Response

- Empty application root, UI needs JavaScript to populate -> rendering candidate `CSR`.
- Meaningful HTML already present -> rendering candidate `SSR` or `SSG`.
- Done when one candidate is recorded with the HTML shape quoted.

---

## Step 2 - Observe Internal Navigation

- Only Fetch/XHR after navigation, `pushState()` observed -> `SPA`.
- Every navigation generates a new Document request -> `MPA`.
- Mixed behavior -> `Hybrid`.
- Done when one navigation value is recorded with the network pattern quoted.

---

## Step 3 - Compare Server HTML with Final DOM

- JavaScript reconstructs most of the DOM -> strengthens `CSR`.
- DOM largely identical, JavaScript only attaches behavior -> strengthens `SSR` / `Hydrated SSR`.
- Done when the step-1 candidate is strengthened or revised, with the diff described.

---

## Step 4 - Identify Framework Indicators

React (`id="root"`, hydration markers), Next.js (`__NEXT_DATA__`), Nuxt
(`__NUXT__`), Angular (`<app-root>`), Vue (`id="app"`).

Framework markers corroborate only: a fingerprint alone never classifies.
Done when each marker is recorded as corroboration, never as the verdict.

---

## Step 5 - Produce Classification

```text
Navigation: SPA | MPA | Hybrid
Rendering: CSR | SSR | SSG | Streaming SSR | Hydrated SSR
Confidence: High | Medium | Low
Evidence:
- signal
- signal
```

Done when both dimensions carry a value, a confidence, and quoted signals -
High only with a behavioural signal behind it.

---

# Core Decision Table

| Observation | Classification |
|-------------|----------------|
| New HTML document request on every navigation | MPA |
| URL changes + `pushState()` + API calls only | SPA |
| Some routes reload, others do not | Hybrid |
| Initial HTML is an empty shell | CSR |
| Initial HTML already contains complete content | SSR / SSG candidate |
| Complete HTML + JavaScript later activates UI | Hydrated SSR |
| HTML progressively streamed in chunks | Streaming SSR |
| Static complete HTML with virtually no server computation | SSG |

---

# Guiding Principles

- Treat **Navigation Model** and **Rendering Model** as independent dimensions:
  classify each on its own signals (a SPA may use SSR; an MPA may use CSR
  widgets).
- Ground every conclusion in directly observable runtime evidence - a framework
  fingerprint alone never classifies.
- Set confidence from the quantity and quality of corroborating evidence,
  never from a single indicator.