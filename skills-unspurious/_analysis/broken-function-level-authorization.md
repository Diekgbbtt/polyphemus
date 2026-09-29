# broken-function-level-authorization - variant decomposition analysis

## 1. Class and scope
BFLA is action-level authorization failure where a caller invokes a function they are not entitled to, and enforcement must bind subject by action at the service that performs the action.
The authority is `skills-unspurious/broken-function-level-authorization/SKILL.md` (132 lines), consulted against `skills/broken-function-level-authorization/SKILL.md` only for extra methodology detail.
The class covers privileged actions reachable by lower roles across transports, gateways, client gates, identity hints, and deferred execution contexts.

## 2. Ontology entity ledger
| Entity type | Value(s) | Source line(s) | Role |
|---|---|---|---|
| PreconditionEnvironment | Edge-only or UI-only enforcement with live core path; legacy or alternate route with weaker middleware; parser-specific handler path; gateway-injected identity headers present; deferred execution split between creation and finalize or approve; replayable webhook or queue endpoint; cached authorization decision at edge; handshake-only WebSocket authorization; tenant selector enforced outside token claims | 12-16, 34-58, 82-88, 90-106 | Discriminator candidate (resolves to 3 discriminators in section 6) |
| TechnologyStack | REST; GraphQL; gRPC; WebSocket; gateway or proxy or edge; background workers, jobs, queues, webhooks; JSON, form, multipart parsers | 13-16, 45-58, 61-81 | Non-discriminator (excluded axis, see section 6) |
| DefensiveControl | Role-based function check at service boundary; edge or gateway policy; UI or feature-gate hiding; token-claim validation; per-message authorization; middleware chain per route or parser; approval workflow re-check | 8, 12-16, 40-48, 59-64, 77-80, 108-115, 122-132 | Discriminator candidate (placement and identity-source values discriminate; control strength itself does not) |
| VulnerabilityClass | Broken function level authorization (action-level authorization failure) | 6-8 | Non-discriminator (this is the class definition itself) |
| AttackGoal | Invoke privileged action as lower-privileged principal; escalate to admin or staff capability; force monetary or state impact through approvals, refunds, or configuration change | 12-16, 122-132 (live catalogue Impact section) | Non-discriminator (goal is invariant across variants) |
| AttackerCapability | Authenticated session or token at a lower role (basic, premium, unauthenticated baseline); ability to call endpoints directly outside UI; ability to supply headers and selectors; ability to trigger or replay background endpoints | 110-115 | Non-discriminator (capability ladder is shared setup, owned with `two-principal-authz`) |
| AttackTechnique | Alternate method or endpoint alias replay; legacy route shadowing; parser-specific resubmission; direct-to-core reach around edge; conflicting identity-header injection; tenant selector switching; job finalize or approve as another actor; webhook or task replay; idempotent retry of state-changing finalize; cached-decision reuse across sessions | 34-58, 72-106 | Discriminator candidate (partitions by which step they bend, see section 6) |
| PayloadPattern | none | none in skill (no reusable parameterized input structure is defined; requests reuse the legitimate action body with changed method, route, encoding, header, or replay timing) | Non-discriminator (no class value exists) |
| Artifact | Lower-role token or session per role; before and after state snapshot; audit log entry; admin method response showing privileged effect | 110-115, 122-132 (live catalogue Validation section) | Non-discriminator (runtime-produced evidence, parametrises proof) |
| ObservableSignal | 401 or 403 on UI but 200 via direct API call; differing status across transports; action succeeding via background job when direct call denied; access changing on header or selector change alone | 27-31 | Non-discriminator (detection signal shared by all variants) |

## 3. RDF notion map
Vuln-specific attack surface: vertical privileged actions, feature-gated endpoints, transport-specific handlers, gateway-fronted backends, and background workers (lines 10-16); this notion varies by enforcement locus and is the raw material of discrimination.
Reconnaissance: admin consoles, hidden UI paths, schema and descriptor enumeration, mobile bundle hints, plus status-difference signals (lines 18-31); this notion is invariant procedure shared by all variants.
Adversarial capabilities: lower-role tokens and direct-call ability outside the UI (lines 110-112); this notion is invariant setup and delegates to `two-principal-authz`.
Common trust assumptions: client gates enforce, gateway checks transfer downstream, token claims decide identity, and a prior step approval covers finalize (lines 8, 12-16, 50-53, 100-106); each assumption varies independently and each maps to one variant.
Testing methodology: the five steps S1 to S5 (lines 108-115); this notion is the step-test substrate and is invariant as parent text.
Proxy techniques: direct-to-core reach and SSRF-reached internal RPC (lines 40-43, 86-88); this notion is a reached step owned by the future proxy family and invoked from the alternate-path variant, not restated here.
Defence bypass techniques: header trust, route shadowing, retry or replay, cache-key confusion (lines 90-106); this notion varies by bypassed control and partitions across the three variants.
Techniques anti-patterns: none named in the class skill; no invariant is stated.
Scripted tests (`references/`): none shipped with the class skill; no invariant is stated.
False positives: mislabeled read-only endpoints, intentional preview toggles, stubbed admin endpoints (lines 116-120); this notion is invariant across variants.
Chaining: none described beyond background-flow finalize chains (lines 50-53); chaining detail is invariant and minimal.

## 4. Runtime parametrisation
Each variant consumes the concrete Service under test, the System mechanism it lies on, and the Endpoint plus Parameter, Header, DataItem, and BaseURL atoms that locate the privileged action at runtime.
The HTTP history supplies the prior status codes, the approval-step transcript, and the cached-decision evidence that each variant compares against.
The operator knowledge base supplies the role roster, the tenant layout, and the gateway topology that parametrise matrix rows and header names.
None of these entities defines a variant because swapping them never changes the kind of testing action performed.

## 5. Agent-with-skill walkthrough
The hunting circumstance is a deployed application where a basic-role agent holds a valid low-privilege session and suspects some privileged function lacks a service-boundary check.
S1 Build Actor by Action matrix: enumerate unauthenticated, basic, premium, and staff or admin roles against every privileged action, with completion when each action has an expected-role cell.
S2 Obtain tokens or sessions: acquire one working credential per matrix role, with completion when each role can issue an authenticated baseline request.
S3 Exercise every action: replay each privileged action across transports and encodings including method overrides, with completion when every action has a same-input lower-role attempt beside a proper-role control.
S4 Vary headers and selectors: resubmit actions with changed org, tenant, or project selectors and gateway-versus-direct routing, with completion when each selector and routing pair has a recorded decision.
S5 Include background flows: drive job creation then finalize or approve, plus webhook and queue endpoints, with completion when each deferred step shows whether the actor was re-checked.
S1 and S2 procedure detail is owned by the cross-cutting `two-principal-authz` methodology and is referenced, not restated, by this class.

## 6. Feature-verdict table
| Candidate feature | Accurate? | Exhaustive? | Verdict | Evidence |
|---|---|---|---|---|
| Enforcement locus (client or edge-only gate versus live core path, legacy shadow route, parser-specific chain) | Yes (S3 performs a different kind of action on alternates: middleware-stack diffing and alias resubmission) | No (S3 names transports, encodings, and method overrides but never describes legacy-route chains, parser-specific middleware, or direct-to-core reach) | Discriminator D1 | Lines 34-38, 55-57, 96-98 versus S3 at lines 112-113 |
| Identity source (token claims versus client-supplied identity header or edge-injected header, including precedence on conflict) | Yes (S4 performs a different kind of action here: contradictory-header precedence probing rather than tenancy routing) | No (S4 describes varying selectors and gateway routing but never describes identity overriding claims or which source wins on conflict) | Discriminator D2 | Lines 42-43, 92-94 versus S4 at lines 113-114 |
| Execution context (synchronous call versus deferred finalize, approve, webhook, retry, or cached-decision reuse) | Yes (S5 performs a different kind of action here: cross-context replay and session-swap reuse rather than first-pass invocation) | No (S5 says confirm re-validation but never describes replaying webhooks, retrying finalize without actor check, or reusing cached edge decisions) | Discriminator D3 | Lines 50-53, 100-106 versus S5 at lines 114-115 |
| Transport or protocol name (REST, GraphQL, gRPC, WebSocket) | No (transport name alone changes tooling, not the kind of authorization-testing action) | Not applicable | Non-discriminator | Stability criterion excludes TechnologyStack; transport tooling detail is owned by transport skills including `graphql` |
| Parser encoding name (JSON, form, multipart) | No (encoding label alone does not change the kind of action) | Not applicable | Non-discriminator | The discriminating fact is the parser-specific middleware gap (D1), and encoding labels alone are aspects inside it |
| Tenant selector value (which org or tenant string) | No (one selector string versus another is the same kind of action) | Not applicable | Non-discriminator | Concrete selector values are runtime parameters consumed through D2 |
| Attack goal or impact severity (escalation, refund, deletion) | No (impact changes reporting, not the testing action) | Not applicable | Non-discriminator | Goal is invariant across all three discriminators |
| Observable signal shape (status pair, signal channel) | No (signals are read the same way in every variant) | Not applicable | Non-discriminator | Signals at lines 27-31 detect success for all variants alike |
| Payload pattern | No (the class defines no reusable parameterized input structure) | Not applicable | Non-discriminator (`none`) | Ledger records `none` for PayloadPattern |
| GraphQL alias or batching shape; gRPC reflection detail; WebSocket message framing | Yes in tooling only (each needs its transport tool) | Yes as transport aspects (covered inside D1 or D2 once the transport tool is applied) | Aspect, not variant axis | STATE 3 branch 3b applies because values overlap and are continuous across transports; procedure lives in transport skills |

## 7. Step-coverage falsification
D1 value legacy or alternate route: parent S3 covers transports, encodings, and method overrides, but the uncovered reality is a legacy route such as `/admin/v1` skipping the new middleware chain while performing the identical privileged action.
D1 value parser-specific handler: parent S3 covers submitting across encodings, but the uncovered reality is JSON, form, and multipart handlers wired to different middleware where only the permissive parser path must be diffed and resubmitted.
D1 value edge-blocked but core-open path: parent S3 covers exercising the action, but the uncovered reality is reaching the internal RPC through an exposed route or SSRF where the proxy-reach step belongs to the proxy family and S3 never names it.
D2 value conflicting identity headers: parent S4 covers varying selectors and gateway routing, but the uncovered reality is supplying `X-User-Id` or `X-Role` headers that contradict token claims and observing which source wins.
D2 value tenant selector as identity: parent S4 covers switching selectors, but the uncovered reality is a tenant-admin action authorized solely by a header or subdomain value with the same token, which is an identity-source substitution rather than tenancy routing.
D3 value split job finalize: parent S5 covers including background flows, but the uncovered reality is creating a job as an allowed actor and finalizing or approving another actor's job where the finalize step never re-checks the caller.
D3 value webhook or task replay: parent S5 covers background endpoints, but the uncovered reality is replaying a webhook or queue task that performs a privileged action without verifying the caller on each delivery.
D3 value retry or cache reuse: parent S5 covers re-validation, but the uncovered reality is retrying an idempotent finalize endpoint or swapping sessions against a cached edge decision where the stored decision, not the current actor, authorizes the call.

## 8. Hypotheses
H1 Single-feature hypothesis on enforcement locus: if the only discriminator is D1 (where the check lives), then the class splits into synchronous alternate-path testing versus everything else, and it is falsified if header-precedence probing or job-finalize replay bends a different parent step than S3.
H2 Single-feature hypothesis on execution context: if the only discriminator is D3 (when the check happens), then the class splits into synchronous versus deferred testing, and it is falsified if alternate-route resubmission or conflicting-header injection bends a step other than S5.
H3 Combined-feature hypothesis on locus by source by time: if D1 (where), D2 (whose identity), and D3 (when) each bends a distinct parent step (S3, S4, S5 respectively), then the class yields exactly three variants, and it is falsified if any two discriminators bend the same step or any proposed variant lacks its own non-coverable step.
H4 Transport-split hypothesis: if transport name discriminates, then REST, GraphQL, gRPC, and WebSocket each deserve a variant, and it is falsified by the stability criterion because renaming the stack preserves the authorization-testing procedure while only the transport tooling changes.

## 9. Variant sets per hypothesis
| Hypothesis | Variant | First non-coverable step | Secondary divergences carried inside |
|---|---|---|---|
| H1 | bfla-alternate-path-testing | S3 (alias, shadow route, parser chain, and direct-to-core reach are not covered by S3 text) | Method override values; encoding labels; middleware diff notes |
| H1 | bfla-remainder | none (no single non-coverable step is named) | Header, selector, job, and replay techniques left unsplit |
| H2 | bfla-deferred-execution-testing | S5 (replay, retry without actor check, and cached-decision reuse are not covered by S5 text) | Job split; webhook replay; idempotency retry; cache reuse |
| H2 | bfla-remainder | none (no single non-coverable step is named) | Alternate path and header techniques left unsplit |
| H3 | bfla-alternate-path | S3 | Verb drift and aliases; route shadowing; content-type parser paths; edge-versus-core direct reach via proxy family step |
| H3 | bfla-client-identity-trust | S4 | Conflicting identity headers and precedence; tenant selector as identity; gateway injection precedence |
| H3 | bfla-deferred-execution | S5 | Split create versus finalize or approve; webhook and queue replay; idempotent retry; cached-decision reuse |
| H4 | bfla-rest; bfla-graphql; bfla-grpc; bfla-websocket | none per variant (no transport adds its own non-coverable authorization step; transport tooling is owned by transport skills) | Resolver, interceptor, and per-message notes as aspects |

## 10. Well-formedness evaluation
Coverage (critical): H1 fails because header-precedence and finalize-replay steps belong to no variant, and H2 fails because alias and header steps belong to no variant, while H3 and H4 both cover every technique.
Disjointness (critical): H3 passes because path, identity-source, and execution-time partitions never admit the same attempt twice, and H4 passes formally but only by duplicating one procedure under four names.
Divergence delta (high): H1 remainder and H2 remainder carry no delta and are deleted, H4 variants each carry no authorization-step delta beyond tooling and are deleted, and all three H3 variants carry a positive delta named in section 7.
Stability (high): H3 survives stack, payload, library, and runtime-asset swaps because locus, source, and time are stack-independent, while H4 fails stability outright because it splits on the excluded TechnologyStack axis.
Parsimony (medium): H3 uses the fewest features that still cover (three), while H4 uses one excluded feature to produce four redundant variants.
Winner: H3 is the only well-formed set, and H1 loses on coverage and delta while H2 loses on coverage and delta while H4 loses on delta and stability.
No return to STATE 3 was needed because the winner passes coverage and disjointness.

## 11. Recommended set
Discrimination function: BFLA discriminates by enforcement locus (which path actually checks) versus identity source (which input the service treats as the actor) versus execution context (whether the authorizing check binds the deferred step).
Recommended variant bfla-alternate-path: first non-coverable step S3, with delta of middleware-stack diffing plus alias, shadow-route, parser-specific, and direct-to-core resubmission that S3 never describes.
Recommended variant bfla-client-identity-trust: first non-coverable step S4, with delta of conflicting-header precedence probing and selector-as-identity substitution that S4 never describes.
Recommended variant bfla-deferred-execution: first non-coverable step S5, with delta of cross-context finalize, webhook replay, idempotent retry, and cached-decision reuse that S5 never describes.
Non-discriminators: TechnologyStack names and transport tooling; parser encoding labels; concrete tenant, org, header, route, and token values; AttackGoal and impact; AttackerCapability ladder; Artifact evidence objects; ObservableSignal shapes; PayloadPattern (`none`).
STATE 1 completed with five parent steps S1 to S5 and no malformed-class stop.
STATE 2 tested every ledger value with both halves and outliers are reported here: transport-specific GraphQL, gRPC, and WebSocket tooling passed accuracy in tooling only and were folded as aspects per STATE 3 branch 3b rather than hidden.
Grey points: the boundary between a parser-specific chain gap and a legacy shadow route can require reading gateway configuration to attribute, and such cases are assigned by which artifact diverges (parser wiring versus route table).
Grey points: direct-to-core reach that requires SSRF invokes the proxy family mid-procedure, and the BFLA variant records the authorization delta while the reach step itself stays owned by the proxy skill.
Grey points: tenant-selector cases where the selector is purely routing (same identity, different scope) stay inside S4 as an aspect, and only selector-as-identity cases enter the identity-trust variant.
Open questions: none at FAIL level, and no uncertainty blocks the three-variant recommendation.
