# Web Application Profiling Skill

## Purpose

Identify the architectural profile of a web application by analyzing delivered HTML, network behavior, and browser/CDP runtime signals.

Classify **independently**:

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

Available evidence:

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

### Navigation Model

Possible values:

- SPA
- MPA
- Hybrid

### Rendering Model

Possible values:

- CSR
- SSR
- SSG
- Streaming SSR
- Hydrated SSR

### Confidence

Possible values:

- High
- Medium
- Low

### Evidence

Every classification **must** include the observable signals that caused it.

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

Clicking `/products`

↓

URL changes

↓

`GET /api/products`

↓

No `GET /products` document request

#### Typical Threats

- Client state manipulation
- API authorization flaws
- Token storage exposure
- Hidden route discovery

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

Clicking `/profile`

↓

`GET /profile`

↓

Complete HTML page returned

#### Typical Threats

- CSRF
- Session management flaws
- Server-side Template Injection
- HTML Injection

---

### Hybrid

#### Definition

Application contains both client-side and server-side navigation.

#### Positive Signals

- Some routes use `pushState()` + Fetch.
- Some routes trigger full document navigation.

#### Example

Dashboard

↓

SPA routing

Authentication

↓

Full server reload

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

Initial response

```html
<div id="app"></div>
```

↓

JavaScript requests

```
GET /api/users
```

↓

DOM constructed dynamically

### Typical Threats

- DOM XSS
- Prototype pollution
- Client-side logic manipulation
- Dependency supply-chain compromise

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

- Server-side Template Injection
- HTML Injection
- Cache poisoning
- Server rendering DoS

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

- Stale content
- Static asset compromise
- Client-side vulnerabilities

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

Product page immediately visible.

↓

React hydrates

↓

Buttons become interactive

### Typical Threats

- All SSR threats
- DOM XSS
- Hydration mismatch
- Serialization flaws

---

## Streaming SSR

### Definition

Server progressively streams HTML while rendering.

### Positive Signals

- Incremental HTML delivery
- Chunked transfer encoding
- Progressive page rendering

### Typical Threats

- SSR threats
- Partial response cache issues
- Rendering resource exhaustion

---

# Analysis Procedure

## Step 1

### Inspect Initial Document Response

If

- Empty application root
- JavaScript required to populate UI

Then

Rendering Candidate

```
CSR
```

If

- Meaningful HTML already exists

Then

Rendering Candidate

```
SSR or SSG
```

---

## Step 2

### Observe Internal Navigation

If

- Only Fetch/XHR after navigation
- `pushState()` observed

Then

```
SPA
```

If

- Every navigation generates a new Document request

Then

```
MPA
```

If

- Mixed behavior

Then

```
Hybrid
```

---

## Step 3

### Compare Server HTML with Final DOM

If

JavaScript reconstructs most of the DOM

Strengthen

```
CSR
```

If

DOM remains largely identical

and JavaScript only attaches behavior

Strengthen

```
SSR
Hydrated SSR
```

---

## Step 4

### Identify Framework Indicators

React

- `id="root"`
- Hydration markers

Next.js

- `__NEXT_DATA__`

Nuxt

- `__NUXT__`

Angular

- `<app-root>`

Vue

- `id="app"`

---

## Step 5

### Produce Classification

Navigation

```text
Classification: SPA | MPA | Hybrid

Confidence: High | Medium | Low

Evidence:
- signal
- signal
```

Rendering

```text
Classification:
CSR
SSR
SSG
Streaming SSR
Hydrated SSR

Confidence:
High
Medium
Low

Evidence:
- signal
- signal
```

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

- Treat **Navigation Model** and **Rendering Model** as completely independent dimensions.
- Never infer one dimension from the other.
- A SPA may use SSR.
- An MPA may still use CSR for individual widgets.
- Framework detection alone is **never sufficient** for classification.
- Every conclusion must be supported by directly observable runtime evidence.
- Confidence should reflect the quantity and quality of corroborating evidence rather than a single indicator.