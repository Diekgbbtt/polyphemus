# GraphQL Operation Shapes

This note details the operation shapes behind the reconnaissance, amplification, and batching steps of the body.
Every shape is written with placeholder tokens rather than a verbatim document, because concrete field names, arguments, and spellings are runtime knowledge-base facts resolved from the target schema.
Read each row as a template: fill the placeholders from the schema inventory and the recorded baseline.

## Operation shapes

| Shape | Template | What it proves |
|---|---|---|
| Meta-field enumeration | `[META-FIELD-SELECTION]` listing the schema's types, fields, and arguments | The schema is readable without a field inventory |
| Field-suggestion probe | `[UNKNOWN-FIELD-NAME]` selected on a known parent | The error text leaks neighbouring field names |
| Unknown-versus-unauthorized differential | The same `[FIELD-NAME]` requested with and without the required privilege | The field exists when the verdict classes differ |
| Alias batch | `[ALIAS-1: RESOLVER(ARG)] ... [ALIAS-N: RESOLVER(ARG)]` in one document | One request carries many operations, so per-request limits are evaded |
| Depth bomb | `[CYCLIC-NESTING]` or a fragment that references itself | Depth expands after the depth check counts it |
| Amount bomb | `[UNBOUNDED-LIST-ARGUMENT]` on a collection resolver | Amount is unbounded |
| Batch array | `[OPERATION-DOCUMENT-1, ..., OPERATION-DOCUMENT-N]` in one request | A forbidden operation rides inside a nominally allowed array |
| Negative-cost argument | `[ARGUMENT-WITH-NEGATIVE-COST]` on a cost-counted resolver | The cost function does not floor at zero, so one request refills its own budget |
| Node lookup | `[NODE-IDENTIFIER]` through the relay-style lookup | Any mapped type resolves by identifier, so a decode and re-encode reaches a hidden type |
| Subscription channel | `[SUBSCRIPTION-FIELD]` over the push channel | Events for another principal arrive on the connection, which proves a channel-scope gap |
| Backward graph traversal | `[PUBLIC-PARENT] { [GUARDED-FIELD] }` | A guarded field is reachable through an allowed parent |

## Transport variants

- JSON body with a query document plus optional variables.
- Form-encoded body carrying the same document.
- A dedicated GraphQL media type on the same path.
- GET with the document in a query parameter, which changes caching and forgery properties.
- A batch array of documents, where each element is validated separately.
- A persisted or pre-registered operation identifier, which may skip transforms applied to ad-hoc documents.

## Expected verdicts

| Observation | Reading |
|---|---|
| Meta-field data returned | The schema is exposed; treat introspection as a live recon channel |
| Suggestion list in an unknown-field error | Field names leak; enumerate from the suggestions |
| Unknown-field verdict beside an unauthorized verdict | The name exists; escalate it in the object-level sweep |
| Alias batch latency above the sequential sum | Resolvers run concurrently; name the race-conditions skill at that step |
| One forbidden operation inside an accepted array | The batch check is at array level, not operation level |
| Request succeeds with a negative or floored cost argument | The cost bound is missing; keep the proof bounded and stop |
| Foreign-object data for a foreign identifier | The resolver trusts possession; file it in the object-level sweep |
| Pushed events for another principal | The channel scope is not enforced per message |

## Discipline

- Read the schema first; every template above is filled from the schema inventory rather than guessed.
- Send one amplification axis per attempt, keep the probe bounded, and stop after proving the bound is missing.
- Keep the recorded baseline beside each amplified request, so a latency or size change attributes to the amplification rather than to load.
- Treat a verdict table row as a hypothesis until a second run reproduces it.
