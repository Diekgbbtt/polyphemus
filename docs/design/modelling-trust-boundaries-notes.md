The core principle: countless of open questions with a nested abduction(dive deeply), exploring services and systems in all directions, eventually you’ll stumble upon a grey point that none questioned or thought about sufficiently.
The Trust Boundary revese enginering reasoning workflow:

1. Reverse-engineer the request-handling stack
Start from the service's observable result and trace backward through the request-handling workflow to the lowest relevant layer, typically stored data. Then trace where that data originates and how it is transformed along the way. Infer component boundaries from observable behaviour; treat the architecture as a hypothesis, not a fact.
At each layer, investigate:
- Implementation and configuration: Are standard technology behaviours or default settings used? Which common programming mistakes, misconfigurations, or implicit assumptions could they introduce?
- Execution paths: What decision trees, fallbacks, retries, or failovers exist? Under what conditions are they triggered, and how do downstream components interpret their results?
- Data provenance: What guarantees does the data acquire or lose as it passes between components?
2. Infer developers' technical assumptions
Adopt the perspective of the developers implementing each component. Given its purpose, technology, and runtime context, what would they commonly assume to be true? Examine assumptions about input validity, identity, authorization, state consistency, dependency reliability, configuration, and upstream guarantees. Use security requirements and functional specifications as evidence of the intended security posture.
Identify absolute language (always, never, all, none, every, impossible) and strict requirements (must, must not, cannot) as clues to potentially fragile assumptions. Ask which rare but plausible edge cases could invalidate them, and what would cause those cases to occur.
3. Challenge assumptions recursively
For every significant assumption, ask:
- What evidence supports it, and what reasoning produced it?
- Is it an observed fact, a documented guarantee, or an inference?
- What if it is false? What alternative execution could occur?
- Which runtime conditions, configuration defects, or failure paths could invalidate it?
- How would downstream components behave if it failed?
Follow each promising discrepancy with further questions, using skepticism to guide investigation rather than presuming a vulnerability.
4. Reconcile trust across boundaries
Compare what each component guarantees with what the next component assumes. Identify mismatches in validation, identity, authorization, data integrity, execution outcomes, or failure handling.
5. Derive and validate candidate vulnerabilities
For each credible mismatch, establish its triggering conditions, potential impact, and observable evidence. Distinguish confirmed behaviour from hypotheses, and classify vulnerabilities only when evidence supports the conclusion.

Request-handling stack layers
These are logical boundaries to investigate, not assumptions about the actual architecture.
1. Client and network ingress: Request URLs, methods, headers, cookies, bodies, and transport context; transformations or restrictions introduced by network intermediaries, proxies, and load balancers.
2. Edge routing and gateway: Request routing, forwarding, rewriting, rate limiting, and edge access policies; guarantees that downstream services may assume have already been enforced.
3. Parsing and validation: Conversion of incoming representations into structured values through parsing, deserialization, normalization, and schema validation; ambiguous representations or inconsistent interpretations between components.
4. Authentication and identity: Interpretation of credentials, tokens, and sessions; identity and role resolution, session state, and propagation of identity context to downstream components.
5. Application and business logic: Mapping requests to operations, resolving resources, enforcing authorization, and coordinating workflows; assumptions about ownership, state, operation order, and upstream validation.
6. Internal services and dependencies: Communication with other services, workers, APIs, caches, and message brokers; assumptions about identity, data freshness, ordering, response completeness, retries, and failure handling.
7. Data access and persistence: Retrieval and modification through repositories, ORM layers, caches, and storage systems; assumptions about record ownership, consistency, isolation, and durable state changes.
8. Response construction: Translation of internal results into HTTP responses, including serialization, error handling, status codes, and caching; whether partial failures or fallback results appear as successful outcomes.
Core principle: Reverse-engineer the execution and data flow, infer the technical assumptions developers made at each boundary, challenge those assumptions under exceptional conditions, and derive vulnerabilities from the trust mismatches discovered.