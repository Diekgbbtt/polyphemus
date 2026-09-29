# Decomposition report

The decomposition ran the seven-state algorithm of `docs/design/skills-variant-boundary.md` over every kept class except the cross-cutting `two-principal-authz`.
Each class has a full argued analysis (12 sections: class and scope, ontology entity ledger, RDF notion map, runtime parametrisation, agent-with-skill walkthrough, feature-verdict table, step-coverage falsification, hypotheses, variant sets, well-formedness evaluation, recommended set) at `_analysis/<class>.md`, each independently reviewed and PASSed.
This report is the per-class index over those analyses.

Result: 29 classes analysed, 28 decompose into 101 variants, `graphql` does not decompose.

| Class | Result | Variants produced |
|---|---|---|
| authentication-jwt | decompose | jwt-signature-forgery, jwt-key-resolution, jwt-claims-confusion, jwt-flow-lifecycle |
| broken-function-level-authorization | decompose | bfla-alternate-path, bfla-client-identity-trust, bfla-deferred-execution |
| business-logic | decompose | concurrent-duplication, value-domain-manipulation, quota-window-slicing, async-boundary-abuse |
| crypto-weakness | decompose | crypto-predictable-token, crypto-signing-key-forgery, crypto-timing-oracle |
| csrf | decompose | csrf-form-post, csrf-navigation-get, csrf-parser-differential, csrf-login-fixation, csrf-websocket-handshake |
| graphql | no decomposition | none (protocol/surface aggregator; stands as one skill) |
| header-injection | decompose | header-crlf-splitting, header-host-forward-spoof, header-cache-poisoning, header-method-override, header-request-smuggling, header-response-value-confusion |
| http-method-tampering | decompose | http-method-tampering-verb-switch, http-method-tampering-override-smuggling, http-method-tampering-informational-verb, http-method-tampering-preflight-coercion |
| http-request-smuggling | decompose | http-request-smuggling-h2-desync (the base smuggling procedure is the parent) |
| idor | decompose | idor-direct-object-swap, idor-collection-batch-scope, idor-deferred-artifact-redemption, idor-context-carrier-substitution, idor-nested-expansion-binding |
| information-disclosure | decompose | error-verbosity-disclosure, stored-artifact-disclosure, differential-oracle-disclosure |
| insecure-deserialization | decompose | deserialization-gadget-chain, deserialization-signed-forgery, deserialization-deferred-trigger |
| insecure-file-uploads | decompose | upload-server-execution, upload-client-execution, upload-archive-extraction, upload-toolchain-execution, upload-pipeline-deferred-trust |
| llm-prompt-injection | decompose | direct-injection-override, indirect-injection-plant, context-leakage, tool-abuse, output-handling |
| mass-assignment | decompose | mass-assignment-nested-relation-write, mass-assignment-bulk-collection-injection, mass-assignment-bulk-nested-relation-write |
| nosql-injection | decompose | nosql-operator-injection, nosql-server-side-script-injection, nosql-aggregation-pipeline-injection, nosql-query-language-injection, nosql-command-protocol-smuggling |
| oauth | decompose | oauth-redirect-uri-validation, oauth-state-nonce-csrf, oauth-pkce-enforcement, oauth-code-client-binding, oauth-device-approval |
| open-redirect | decompose | generic-redirect-parser-bypass, oauth-redirect-uri-relay, redirector-to-fetcher-pivot |
| path-traversal-lfi-rfi | decompose | traversal-read, lfi-include-execution, rfi-remote-include, archive-zipslip-write |
| prototype-pollution | decompose | prototype-pollution-client-side, prototype-pollution-server-side |
| race-conditions | decompose | idempotency-dedup-bypass, optimistic-guard-evasion, cross-service-consistency-race, single-request-fanout (the synchronised-duplication core is the parent) |
| rce | decompose | rce-command-injection, rce-pipeline-execution |
| sql-injection | decompose | sqli-union-extraction, sqli-error-based-extraction, sqli-boolean-blind-extraction, sqli-time-blind-extraction, sqli-oast-exfiltration |
| ssrf | decompose | no-response-egress-inference, scheme-translated-command-execution, header-gated-cloud-credential-read (plain direct mapping is the parent baseline) |
| ssti | decompose | ssti-reflected-evaluation, ssti-blind-evaluation |
| subdomain-takeover | decompose | dangling-record-resource-claim, cdn-alternate-domain-binding, ns-delegation-takeover |
| weak-credential-discovery | decompose | exposed-secret-extraction, default-credential-replay, username-enumeration-oracle, session-token-authority-decode |
| xss | decompose | xss-stored, xss-dom (reflected folds to the parent baseline) |
| xxe | decompose | blind-parameter-entity-oob-exfiltration, transclusion-without-entity-resolution, entity-expansion-denial-of-service (the base in-band read is the parent) |

## Attributes walked

Per class, the analysis walked every ontology entity value and every RDF notion against the two-half step test (accurate and exhaustive), and recorded each as discriminator, aspect, or non-discriminator.
Non-discriminators confirmed across classes: technology stack and versions, payload literals, runtime asset identity, pure impact, and surface/protocol as class-selection concerns rather than variant axes.

## Open questions and grey points

- `graphql` does not decompose; the parent stands as the family entry.
- Class-level grey points (for example the `ssrf` file-wrapper versus command-craft split, the `information-disclosure` referrer and tracing-header placement) are recorded in each analysis section 11 and were accepted as pass-level.
- Cross-references to the future `defence-bypass` and `proxy-techniques` families (#278) and to `two-principal-authz` are named at their steps rather than restated.
