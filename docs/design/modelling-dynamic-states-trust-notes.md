Core principle: Model trust not only as who or what is trusted, but also as which states are trustworthy, how they were reached, and whether they remain valid under every possible execution sequence

## Generalised workflow: Dynamic state-trust modelling
1. Define the application service and initial state. Identify its observable interface, relevant objects, operations, and initial state \(S_0\). Without source-code access, distinguish observed behaviour from inferred internal state.
2. Construct the EFSM. Model the service as states, transitions, guards, actions, and state variables. For every identified state, systematically enumerate possible operations and resulting states, including error paths, repeated operations, and asynchronous or concurrent execution where relevant.
3. Characterise every transition. For each transition, identify its preconditions, state changes, side effects, and implicit assumptions. Determine which state attributes must hold, which are actually verified, and which are merely trusted.
4. Evaluate transition validity. Classify each transition against:
- State invariants: Does the resulting state preserve required security properties?
- Trust-transition agreements: Are the conditions required to cross from an untrusted state to a trusted state satisfied?
- State consistency: Are dependent attributes and related objects consistent with the resulting state?
   Record violations and unverified assumptions without yet presuming attacker control.
5. Derive the required execution capabilities. For each problematic transition or state, determine the precise conditions needed to reach it: operation access, parameter control, identity or role, prior state, request ordering, concurrency, or control over external events.
6. Assess capability attainability. Using the black-box capability model, establish whether those conditions are already available to an attacker, can be obtained through legitimate functionality, or require bypassing an existing security control.
7. Identify the necessary implementation faults. Determine what programming or architectural defect would enable the transition: missing guards, incorrect authorisation, stale-state reliance, non-atomic updates, inadequate object binding, or failure to verify a trust prerequisite. Treat these as candidate explanations until supported by evidence.
8. Characterise the vulnerability. Correlate the invalid transition, violated invariant, required capabilities, and enabling fault. A vulnerability exists when a reachable, security-invalid execution can be induced by an actor within the defined threat model.

## Examples

1. Checkout and order fulfilment
Business workflow

Service boundary: The operations exposed for creating a cart, validating an order, processing payment, confirming an order, and initiating fulfilment.
Initial state: An order is created from a user's cart. Its items, quantities, owner, and initial status are recorded.
From this initial state, enumerate transitions such as editing the cart, validating prices and inventory, applying a discount, initiating payment, receiving a payment result, cancelling the order, and requesting fulfilment. Each transition may change several state variables, not just the order's nominal status.
For example, validation might set validated = true and record a total. Payment might set payment_status = confirmed. Fulfilment might set fulfilment_status = queued. The model must establish whether later operations invalidate earlier assumptions: editing the cart after validation, for example, may make the recorded total stale.
Next, inspect every transition that can lead to an order being fulfilled. The invariant is that fulfilment requires authoritative payment confirmation for the same order and amount. The trust-transition agreement is that an order cannot move into a trusted, fulfilment-eligible state merely because a client supplies a status or because an earlier validation succeeded.
Only after identifying possible violations should the analysis determine whether the exposed interface permits the required operation sequence, whether concurrent requests can interleave, and whether missing guards, stale state, or non-atomic updates could enable the transition.


2. Authentication, session management, and account recovery
Identity lifecycle

Service boundary: Login, session creation and renewal, logout, password recovery, and identity verification.
Initial state: A user has no authenticated session. The service maintains some combination of account status, authentication challenges, session records, and credential versions.
Enumerate transitions from unauthenticated to authenticated, from authenticated to expired or revoked, and from recovery-requested to recovery-verified and credential-reset. Also include failed attempts, retries, token renewal, simultaneous sessions, and changes to account status.
A key modelling question is whether the same apparent state can represent materially different security conditions. A session may be active but associated with an outdated credential version; a recovery challenge may be verified but already consumed; or an account may be suspended while an existing session remains usable.
The invariant is that protected operations require a currently valid authentication context for an eligible account. A recovery token must only authorise the intended recovery action, within its intended scope and validity period. The trust-transition agreement is that possession of a recovery token or session identifier must not implicitly establish broader identity or authority than the corresponding verification process grants.
After mapping the state transitions, assess whether the interface permits token reuse, session renewal after revocation, or recovery-state reuse. Then identify the potential implementation fault: for example, failure to invalidate sessions, incorrect token binding, or a missing check against current account state.


3. File upload, processing, and publication
Content lifecycle

Service boundary: Uploading files, scanning or transforming them, storing them, and making them available to users.
Initial state: A file record exists, or an upload has been initiated. The file may be incomplete, unverified, or temporarily stored.
Enumerate transitions from initiated to uploaded, uploaded to validated, validated to processed, and processed to published. Include retries, asynchronous scanning, cancellation, replacement, deletion, and download requests.
Model the file's state attributes separately: owner_id, object_id, content_hash, scan_status, processing_status, visibility, and storage_location. These attributes may be updated by different components and at different times.
Consider a file that is scanned and approved, then replaced with different content while retaining its record identifier. The nominal state may still say approved, even though the content no longer matches what was inspected. Another possible inconsistency is a file becoming publicly accessible before scanning finishes.
The invariant is that only the intended content, belonging to the correct object and meeting the required processing conditions, may be published or downloaded under the relevant access policy. The trust-transition agreement is that untrusted uploaded content cannot become trusted published content without the required validation of that exact content.
Once a problematic transition is identified, investigate whether the interface supports replacement, concurrent processing, or premature access. Candidate faults include a check-to-use gap, stale approval metadata, missing ownership checks, and inconsistent publication guards.


4. Funds transfer and financial transactions
Financial state

Service boundary: Creating transfers, checking account eligibility and balances, authorising transactions, recording ledger entries, and reporting transaction status.
Initial state: An account exists with a recorded balance and a set of transaction records. A transfer may initially be absent or newly created.
Enumerate transitions such as transfer initiation, validation, authorisation, reservation of funds, ledger posting, settlement, reversal, and cancellation. Model concurrent transfers and repeated requests as part of the service's behaviour, not as attacks presumed in advance.
Relevant state variables include available balance, reserved balance, transaction status, transaction identifier, authorisation status, and ledger entries. A status such as completed should be distinguished from a request being accepted or queued.
One critical invariant is that a transfer cannot spend funds beyond the permitted balance and transaction limits. Another is that each logical transfer must produce the intended financial effect exactly once, even if requests are retried.
Suppose two transfers each validate against the same initial balance. If both are then committed without atomic balance enforcement, the resulting ledger state may violate the balance invariant. The individual requests can be authenticated and correctly formatted; the invalid state arises from their interleaving.
The trust-transition agreement is that a validated transfer is not automatically an authorised, committed, or settled transfer. Each state change must rely on the appropriate authoritative transaction state.
After establishing the problematic execution, assess whether the interface allows concurrent or repeated operations and whether the implementation could lack atomicity, idempotency, or ledger consistency.


5. Multi-tenant resource and access management
Ownership and authorisation

Service boundary: Creating resources, assigning owners, sharing resources, managing roles, transferring ownership, and accessing or deleting resources.
Initial state: A resource exists within a tenant or workspace, with an owner and an initial access-control configuration.
Enumerate transitions for creating a resource, granting and revoking access, changing roles, transferring ownership, moving resources between workspaces, and deleting them. Include nested objects and dependent resources, such as documents inside projects or credentials attached to integrations.
The EFSM should represent not only the resource's lifecycle but also relationships such as resource.tenant_id, resource.owner_id, actor.role, and the applicable permission version. A user's global role and their permissions on an individual resource are distinct attributes.
A possible inconsistency occurs when a resource is transferred to another tenant but a child object or associated credential retains the previous ownership relationship. Another occurs when a role is revoked but a previously issued access context continues to authorise operations that should no longer be permitted.
The invariant is that every operation must be authorised against the correct resource, tenant, and current permission state. The trust-transition agreement is that possession of a valid resource identifier, or prior access, does not establish current authority over that resource.
Only after discovering a transition that violates this property should you test whether the public interface can reach it. Potential enabling faults include missing object-level authorisation, inconsistent propagation of ownership changes, stale permission caches, and checks against the wrong tenant context.


6. Subscription, entitlement, and quota management
Entitlement lifecycle

Service boundary: Creating subscriptions, changing plans, processing renewals and cancellations, and enforcing feature access, usage quotas, and billing status.
Initial state: An account exists with a subscription status, plan, billing period, and entitlement configuration.
Enumerate transitions for trial activation, subscription creation, upgrade, downgrade, renewal, failed payment, grace-period entry, cancellation, expiration, and reactivation. Include asynchronous billing notifications and the separate operations that actually enforce feature access.
Relevant state variables include subscription_status, plan_id, billing_period, payment_status, quota_limit, and entitlement_version. These values may be updated by different services, so the EFSM should capture their dependencies and timing.
A subscription may become cancelled while an entitlement cache still grants premium access. Alternatively, a plan upgrade may change the displayed plan without updating the quota enforced by a downstream service. A delayed payment notification may also arrive after a cancellation or after a newer billing period has started.
The invariant is that effective entitlements must correspond to the authoritative subscription state and applicable billing rules. The trust-transition agreement is that a subscription event or displayed plan must not, by itself, establish an entitlement unless the event is valid for the current subscription and period.
After identifying a possible inconsistent state, investigate whether the service interface and event timing permit it. Candidate faults include out-of-order event handling, missing version checks, inconsistent caches, and entitlement checks that rely on client-controlled plan attributes.