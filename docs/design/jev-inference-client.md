# Jev inference client: design and implementation record

**Status:** accepted, 2026-11-02.
**Supersedes:** the OpenRouter SystemOne route and the OpenCode Go attempt.
**Implementation:** `src/polymerhus/app/llm/typesafe.py` on branch `fix/typesafe-systemone`, commit `214b53f0`.
**Evidence:** `docs/experiments/typesafe-provider-integration.md`.
**Probe:** `docs/experiments/typesafe_probe.py`.
**Policy probe:** `docs/experiments/runs/typesafe-jev-probe-20261102T143902Z/decisions.jsonl`.

## 1. Decision

Jev is called through the TypeSafe SystemOne API directly.

The transport is the OpenAI SDK low-level `post` primitive.

```python
await AsyncOpenAI(
    api_key=os.environ["API_KEY_TYPESAFE"],
    base_url="https://api.typesafe.ai/v1",
).post("/systemone", body=payload, cast_to=object)
```

Jev is not a chat model.
Jev is not a LiteLLM gateway model.
Jev owns one small client module, `TypeSafeSystemOne`.

This is the smallest integration that preserves the SystemOne contract.

## 2. Why the normal chat path cannot carry Jev

The project's chat lane uses LangChain `ChatOpenAI`.
`ChatOpenAI` sends `POST /chat/completions`.
TypeSafe exposes `POST /v1/systemone`.
The probe sent both project-shaped requests to TypeSafe:

- `OpenAI.chat.completions.create(model="jev-latest")` returned `404 Not Found`.
- `ChatOpenAI(model="jev-latest", base_url="https://api.typesafe.ai/v1")` returned `404 Not Found`.

The request and response contracts also differ.

- Chat sends `messages`.
- SystemOne sends `state` and named typed `questions`.
- Chat returns assistant text or tool calls.
- SystemOne returns typed `answers` with `choice`, `probabilities`, `confidence`, `noul`, or `score`.
- Chat has `tools`, `tool_choice`, and `response_format`.
- SystemOne has `Choice`, `Noul`, and `Score` as first-class question types.

A chat-compatible shim would have to translate typed questions into prose and parse typed answers back out.
That shim would discard the contract's main guarantee: the model can only answer inside the supplied options.

## 3. Options considered

| Option | Decision | Reason |
| - | - | - |
| `ChatOpenAI` against TypeSafe | Rejected | 404; no chat endpoint; typed answers lost |
| LiteLLM `openai/jev-latest` | Rejected | 404; LiteLLM sends chat completions |
| LiteLLM custom `typesafe` handler | Rejected | New code path; chat envelope; typed answers lost; operational surface |
| TypeSafe Python SDK `typesafe-sdk` | Not chosen | Viable, but adds a dependency, a second transport, and a second env name |
| Raw `httpx` or `urllib` | Rejected | Duplicates auth, retry, timeout, and observability primitives |
| OpenAI SDK low-level `post` | Chosen | Same SDK, same auth, same retries, same timeouts, no new dependency |

The decision is not "avoid LiteLLM at all costs".
The decision is "do not force a typed decision API through a chat router".

## 4. The chosen interface

### 4.1 Endpoint and auth

- Base URL: `https://api.typesafe.ai/v1`.
- Endpoint: `POST /systemone`.
- Auth: `Authorization: Bearer $API_KEY_TYPESAFE`.
- Content type: `application/json`.
- Optional image and long-context headers are not used by the crawl policy.

The base URL can be overridden with `TYPESAFE_BASE_URL`.
The model can be overridden with `TYPESAFE_MODEL`.

### 4.2 Request

```json
{
  "model": "jev-latest",
  "state": {"page": {"url": "/", "candidates": ["signin", "register"]}},
  "questions": {
    "next": {
      "type": "choice",
      "instructions": "Choose the next element to exercise.",
      "criteria": {
        "signin": "Submit the credentials.",
        "register": "Create an account."
      }
    }
  }
}
```

`state` may be a string, an object, or an array.
The crawl policy sends a compact object.
The context budget is 64k tokens for state plus questions.
The policy keeps the state small on purpose.

### 4.3 Response

```json
{
  "model": "jev-1.14.0",
  "answers": {
    "next": {
      "type": "choice",
      "choice": "signin",
      "confidence": 0.76,
      "probabilities": {"signin": 0.84, "register": 0.16}
    }
  },
  "usage": {"input_tokens": 356, "output_tokens": 38}
}
```

The `model` field reports the concrete version that answered.
The policy logs it on every decision.
A model alias change is visible in the decision log.

### 4.4 Transport details

`cast_to=object` is required.

- `cast_to=object` returns the parsed JSON object.
- `cast_to=dict` raises `ValueError: not enough values to unpack (expected 2, got 0)` in openai 2.x.
- `cast_to=httpx.Response` also works and exposes the raw status and body.

`AsyncOpenAI.models.list()` is not used.
TypeSafe returns `{"models": [{"name": ...}]}`.
The OpenAI model page expects `{"data": [{"id": ...}]}`.
The direct client reads the TypeSafe catalog through `GET /models` and parses `models`.

## 5. Model identity and versioning

The direct TypeSafe catalog currently exposes two names.

- `jev-latest`, which resolves to `jev-1.14.0`.
- `jev-preview`, the next-version preview.

The versioned name `jev-1.13` returns `400 Unknown model`.
`jev-1.13.0` and `jev-1.14` also fail.
The OpenRouter `typesafe/jev-1.13` alias belongs to a different distributor and is not available on the direct key.

The crawl policy uses `jev-latest`.
The response model records the concrete version.
The policy can compare versions across runs.

If a frozen 1.13 behavior becomes mandatory, TypeSafe direct cannot supply it today.
The options are:

1. Accept `jev-latest` and record the concrete version.
2. Pin `jev-preview` for preview behavior.
3. Ask TypeSafe for a versioned alias.
4. Return to OpenRouter `typesafe/jev-1.13`, which requires a funded key.

The design does not hide this constraint.

## 6. Token tracking and the LiteLLM bypass

### 6.1 What is lost

LiteLLM provides centralized accounting for the chat lane.

- Per virtual key token and spend aggregation.
- Model-level cost maps and budget windows.
- The `/model/info` view of registered deployments.
- The gateway's request logs and callback fan-out.

Jev does not go through LiteLLM.
Therefore Jev does not appear in the gateway's token and spend tables.
The gateway budget windows do not include Jev spend.
The gateway cannot block a Jev call when a virtual-key budget is exhausted.

### 6.2 What is not lost

The TypeSafe response carries `usage.input_tokens` and `usage.output_tokens`.
`TypeSafeSystemOne.ask` returns the full response, including usage.
The crawl policy writes the usage to `decisions.jsonl`.
The crawl metrics aggregate input tokens, output tokens, calls, latency, and cost.
The raw token counts are preserved.
Only the gateway's central aggregation is lost.

### 6.3 Why the loss is accepted

Jev cost is ephemeral at this call volume.

- TypeSafe direct prices input at `$42` per billion tokens.
- That is `42e-9` USD per input token.
- Output tokens are free.
- A 365-input-token call costs `$1.533e-05`.
- A 60-action crawl with two decisions per action is about 120 calls.
- At 500 input tokens per call, that is 60,000 tokens, or `$0.00252`.
- At 1,000 input tokens per call, that is 120,000 tokens, or `$0.00504`.
- The observed policy probe was 365 input tokens and `$1.533e-05`.

The observed `jev1` crawl was larger than the early estimate.
It made 122 calls, consumed 338,985 input tokens and 23,461 output tokens, and cost `$0.014237` for 60 actions.
The removal and candidate states are large, so the average call was about 2,780 input tokens.
The `jev2` targeted authz run made 74 calls and 224,251 input tokens for `$0.009419`.
The `jev3` final integrated run made 153 calls and 411,882 input tokens for `$0.017299`.
The three runs together made 349 calls, consumed 975,118 input tokens and 82,765 output tokens, and cost `$0.040955`.
The cost is therefore cents per crawl, not fractions of a cent.
It is still small relative to the engineering and operational cost of a custom gateway handler.
The gateway budget guard is also disabled by default in the current deployment, so the lost enforcement is not a new protection.

### 6.4 What would change this decision

Centralized accounting becomes mandatory if one of these holds.

- Jev spend becomes material relative to the run budget.
- A compliance rule requires every model call in one ledger.
- The gateway becomes the only approved egress.
- A per-tenant chargeback requires gateway virtual keys.

In those cases, the direct client can emit its usage to a small ledger.
The ledger seam already exists in the response.
A custom LiteLLM handler is the fallback, not the default.

## 7. Observability

The direct client does not use LiteLLM callbacks or Langfuse callbacks.
The crawl policy owns the decision log.

`decisions.jsonl` records:

- timestamp;
- question tag, `choose_removed`, `choose_chosen`, or `choose_value`;
- latency;
- request state and questions;
- response model, answers, usage, and probabilities;
- retry attempt.

`metrics.json` aggregates:

- call count;
- error count;
- input and output tokens;
- cost in USD;
- latency p50 and p95.

This is enough to audit the policy.
The gateway's cross-provider trace view is not available for Jev.
The crawl trace remains local and typed.

## 8. Retry and timeout policy

The client uses the OpenAI SDK retry stack.

- `max_retries` defaults to the project `MAX_RETRIES`, currently 1.
- The crawl policy can pass a larger retry count.
- The crawl's own loop retries a failed decision up to three times.
- The timeout is the project `request_timeout()` by default.
- The client accepts an explicit `timeout` for a tighter crawl bound.

Retryable failures are the OpenAI SDK's retryable classes: timeouts, connection errors, 408, 409, 429, and 5xx.
A 400 unknown model is not retryable.
A 401 or 403 key failure is not retryable.
A 404 contract failure is not retryable.
A malformed response raises `TypeSafeResponseError`.

The policy logs the final failure and falls back or stops.
The fallback decision is explicit, not silent.

## 9. Error taxonomy

| Failure | Surface | Policy response |
| - | - | - |
| Missing `API_KEY_TYPESAFE` | `LLMConfigError` at construction | Stop the run before traversal |
| 401 or 403 | OpenAI `AuthenticationError` or `PermissionDeniedError` | Fail the policy, surface the key problem |
| 400 unknown model | OpenAI `BadRequestError` | Fail the policy, fix the model pin |
| 404 | OpenAI `NotFoundError` | Fail the policy, contract or base URL mismatch |
| 429 or 5xx | OpenAI retryable error | SDK retry, then policy retry |
| Timeout | OpenAI `APITimeoutError` | SDK retry, then policy retry |
| Missing `answers` | `TypeSafeResponseError` | Fail the policy, do not invent an answer |
| Invalid choice key | Policy protocol error | Do not execute, record the error |

The client never invents an answer.
The client never parses an answer from prose.
Every answer is constrained to the supplied question criteria.

## 10. Configuration

| Variable | Required | Default | Purpose |
| - | - | - | - |
| `API_KEY_TYPESAFE` | Yes | none | TypeSafe bearer key |
| `TYPESAFE_BASE_URL` | No | `https://api.typesafe.ai/v1` | Direct API base |
| `TYPESAFE_MODEL` | No | `jev-latest` | Default model alias |

The key lives in `.env`, never in the repository.
The `.env.example` documents the three variables.
The probe reads `API_KEY_TYPESAFE` and never prints it.

The gateway config keeps `model_list: []` for TypeSafe.
The file now states that TypeSafe is deliberately absent.
`PROVIDERS` in `providers.py` does not gain a `typesafe` entry.
`SYSTEMONE_PROVIDERS` guards the chat constructor.

## 11. Implementation

`TypeSafeSystemOne` provides:

- `ask(state, questions, model=None)` for typed decisions;
- `models()` for the direct catalog;
- `close()` and async context management.

The module validates:

- the response is a mapping;
- the response has an `answers` mapping.

The module does not validate individual answer keys.
The policy owns that validation because it owns the question names.

The module uses the same `openai` package as the chat lane.
The import surface is small.
There is no new Python dependency.

`build_chat_model("typesafe", ...)` raises a clear `LLMConfigError`.
This prevents an operator from adding a `typesafe` chat role by mistake.
The sync and the gateway never see a TypeSafe model.

Tests:

- `tests/test_typesafe_systemone.py` covers the request body, `cast_to=object`, the model catalog, the missing key, the malformed response, close, and the chat guard.
- Six tests pass.
- The gateway config tests still pass, eight cases.

## 12. Security

The key is read from the process environment.
The direct client does not print it.
The probe records only key presence and length.
The key is not stored in the LiteLLM database.
The key is not committed to `.env.example`.
The key can be rotated without a gateway restart.
The direct request uses the same TLS endpoint as the TypeSafe SDK.

## 13. Consequences

Positive.

- The typed Choice, Noul, and Score contract is preserved.
- No chat envelope, no prose parsing, no tool-call shim.
- No new dependency.
- No LiteLLM custom handler.
- The retry and timeout behavior is the same SDK behavior as the chat lane.
- The model version that answered is recorded on every decision.
- The policy probe is fast: 267 ms for a 365-input-token Choice.

Negative.

- Jev is absent from the gateway's central token and spend tables.
- Jev is absent from the gateway's budget enforcement.
- Jev is absent from the gateway's callback fan-out.
- The crawl must carry a small cost logger to preserve spend visibility.
- The direct route is a second egress for one provider.
- The model alias is `jev-latest`, not the frozen `jev-1.13`.

The negative list is accepted.
The Jev spend is ephemeral.
The typed contract is worth more than the central aggregation for this one provider.

## 14. Acceptance

The design is accepted when all of these hold.

1. The direct probe returns a typed Choice from `jev-latest`.
2. The unit tests pass.
3. The chat constructor rejects `typesafe`.
4. The gateway config test passes.
5. The crawl policy runs `choose_removed`, `choose_chosen`, and `choose_value` through `TypeSafeSystemOne`.
6. The crawl decision log records model, usage, cost, and latency.
7. A deterministic baseline and a Jev run are comparable on form success, field coverage, XHR capture, safety, and no-op rate.

Items 1 to 4 are complete.
Items 5 and 6 are complete.
Item 7 is complete with a mixed policy result.

`jev1` general crawl:

- 6 pages and 60 actions.
- 21/21 XHR responses and bodies.
- 122 Jev calls and 0 Jev errors.
- 338,985 input tokens and 23,461 output tokens.
- `$0.014237`.
- p50 206 ms and p95 361 ms.
- 0 observed unsafe endpoints.
- Safety recall 1.00 and precision 0.75.
- No-op rate 45 percent.
- Impact compliance 0.967.

`jev2` targeted authz crawl:

- 6 pages and 20 actions.
- 39/39 XHR responses and bodies.
- 74 Jev calls and 0 Jev errors.
- 224,251 input tokens and 22,388 output tokens.
- `$0.009419`.
- p50 190 ms and p95 282 ms.
- 36 unsafe controls removed, 34 by Jev and 2 by the guard.
- Safety recall 1.00 and precision 1.00.
- 0 observed unsafe endpoints and 0 authz PUTs.
- No-op rate 30 percent.
- Impact compliance 1.00.

The Jev transport and the typed contract hold in both runs.

The policy quality is mixed.

- Jev removed the registration form as auth state, so the Jev run did not exercise the registration form contract.
- The library search form was submitted three times, a projection state bug.
- Jev removed 34 destructive controls on the role and user pages without over-removal.
- Jev missed two authz controls, `添加角色` and `批量添加用户`; the hard guard caught both.
- The hard guard still over-removes the book card whose abstract contains `购买`.
- The no-op rate is lower than the deterministic baseline on the general crawl, but still high.

The Jev client design is accepted.
The policy prompts and the safety boundary need another iteration.

`jev3` is the final integrated run.

- 7 pages and 59 actions.
- 73/73 XHR responses and bodies.
- The registration form succeeded once with 5/5 fields.
- 153 Jev calls and 0 errors.
- 411,882 input tokens and 36,916 output tokens.
- `$0.017299`.
- p50 208 ms and p95 302 ms.
- 35 destruction controls removed, 31 `移除` and 4 `批量删除`.
- 0 of 2 authz openers removed; both were clicked and opened dialogs.
- 0 observed unsafe endpoints and 0 authz PUTs.
- No-op local-state rate 51.0 percent; no-op all-actions rate 42.4 percent.
- Impact compliance 1.00.

The registration safe-write prompt works.
Jev did not remove the form, and the form returned HTTP 200 with all five fields.

The Jev destruction boundary is clean.
The Jev authz boundary is incomplete: it clicked `添加角色` and `批量添加用户` without removing them.
Both openers only opened dialogs.
No authz submit was clicked and no authz mutation reached the network.
The residual risk is the authz dialog submit.
It is accepted because Jev owns the decision and no symbolic guard compensates for it.

The `jev1` and `jev2` results predate the safety-ownership correction below.
The hard guard in those runs is historical.
The final `jev3` run has no symbolic guard.

## 15. Safety decision ownership

The symbolic unsafety guard is removed.

- `deterministic_safety` is gone.
- The authz hard guard is gone.
- The post-action unsafe-endpoint guard is gone.
- The keyword oracle is not a decision path.

`choose_removed` is the sole unsafety decision owner.
The specified action-domain filters are the only categories: auth state, payment, and destruction.
Account registration is an explicit safe write in the prompt.
The Jev model decides which candidates belong to a forbidden category.

The measurement is separate from the decision.
A manual expected set and the observed network are evaluation oracles.
They never feed the policy.
The residual risk is a Jev false negative.
That risk is accepted by design.

This removes the general guard that tried to compensate for Jev.
It also removes the keyword false positive that removed the book card.
The final run measures Jev's own boundary.
