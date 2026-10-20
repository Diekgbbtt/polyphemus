---
name: webapp-clientside-semantic-model
description: Construct a semantic model of the client-side application from browser-observable artifacts before performing any security analysis.
metadata:
  version: '1.0'
---

# Client-Side Semantic Modeling

## Objective

Construct a semantic model of the client-side application from browser-observable artifacts. Model first: understand **what the application is, how it behaves, what it trusts, and which assumptions it makes**. Vulnerability reasoning builds on that model, never ahead of it.

---

## Inputs

The following reconnaissance artifacts are assumed to be available:

- HTML source
- Rendered DOM
- JavaScript bundles
- Source maps and recovered sources (when available)
- Runtime execution traces
- Network activity
- Browser storage (cookies, localStorage, sessionStorage, IndexedDB, Cache Storage)
- Runtime metadata (framework fingerprint, browser APIs, workers, dynamically loaded resources)

---

## Analysis Pipeline

Work the stages in order. Each stage states its question and its done-when.

### 1. Structural Reconstruction

Ask what exists. Reconstruct the static structure:

- pages and navigation entry points
- UI components
- JavaScript modules
- dynamically loaded resources
- event handlers
- browser APIs
- persistence mechanisms
- communication mechanisms

Done when the client-side architecture is inventoried.

---

### 2. Behavioral Reconstruction

Ask how the application behaves. Correlate execution traces with the reconstructed structure:

- initialization sequence
- navigation flow
- event-driven execution
- asynchronous operations
- DOM mutations
- storage updates
- network interactions
- dynamic imports

Done when runtime execution reads as a behavioral graph.

---

### 3. Data Flow Reconstruction

Ask how information moves. For every significant piece of data, trace source,
transformations, persistence, communication, and consumers.

Typical sources: user input, browser storage, URL parameters, cookies, server
responses, browser APIs, postMessage, iframe communication.

Typical sinks: DOM rendering, browser storage, network requests, third-party
integrations, analytics, logging.

Done when the end-to-end data-flow model names every significant flow's source
and sink.

---

### 4. Trust Boundary Identification

Ask where trust changes. Classify components into trust domains:

- browser runtime
- first-party application
- user-controlled input
- browser storage
- backend services
- third-party services
- embedded iframes
- external scripts
- service workers
- Web Workers

For every boundary, document communicating parties, exchanged data, trust
assumptions, validation performed, authentication mechanisms, and integrity
guarantees.

Done when every boundary carries its parties, data, and assumptions.

---

### 5. Domain Model Reconstruction

Ask what the application's business concepts are. Extract entities,
identifiers, relationships, and client-side state objects - business concepts
over implementation details.

Done when the model names what the application manipulates.

---

### 6. External Integration Analysis

Ask what every external dependency is. For each integration document provider,
loading mechanism, communication channel, exchanged data, browser APIs used,
permissions required, failure handling, and resulting trust boundary.
(Providers such as OAuth, payment, analytics, chat widgets, CAPTCHA, embedded
maps, feature flag services.)

Done when every integration carries its trust relationship.

---

### 7. Assumption Extraction

Ask what the application takes on trust. Make implicit assumptions explicit -
trusted browser storage, client-side state, API responses, iframe origins,
feature flags, JWT contents, dynamically loaded code, cross-origin
communication - documenting each together with the component relying on it.

Done when every assumption names its relying component.

---

### 8. Architectural Risk Review

Ask which architectural choices carry risk, still without searching for
specific vulnerabilities: client-side enforcement of security decisions,
unnecessary exposure of sensitive information, excessive trust in third-party
resources, unrestricted cross-origin communication, excessive browser storage
usage, dynamic code execution, weak isolation between trust domains,
unnecessary propagation of sensitive data.

Describe observations objectively; never claim exploitability.

Done when each risky choice is recorded as an observation, not a finding.

---

# Final Deliverable

Produce a concise natural-language model containing:

- Client-side architecture
- Runtime behavior
- Data-flow model
- Trust boundaries
- Domain entities
- External integrations
- Explicit trust assumptions
- Risk-oriented architectural observations

This semantic model serves as the foundation for all subsequent security analysis and vulnerability reasoning.
