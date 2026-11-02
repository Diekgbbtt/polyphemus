# TypeSafe SystemOne provider integration

**Status:** probe complete, minimal client patch committed.
**Date:** 2026-11-02.
**Branch:** `fix/typesafe-systemone` in `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/fix-typesafe-systemone`.
**Commit:** `214b53f0 feat(llm): add direct TypeSafe SystemOne decision client`.
**Probe script:** `docs/experiments/typesafe_probe.py`.
**Probe evidence:** `docs/experiments/runs/typesafe-probe-20261102T143335Z/probe.json`.
**Policy probe:** `docs/experiments/runs/typesafe-jev-probe-20261102T143902Z/decisions.jsonl`.

## 1. Answer first

Use the TypeSafe SystemOne API directly through the OpenAI SDK low-level `post` primitive.

- Base URL: `https://api.typesafe.ai/v1`.
- Endpoint: `POST /systemone`.
- Request: `{model, state, questions}`.
- Auth: `Authorization: Bearer $API_KEY_TYPESAFE`.
- Model: `jev-latest`, which currently resolves to `jev-1.14.0`.
- The OpenAI SDK call: `await AsyncOpenAI(...).post("/systemone", body=payload, cast_to=object)`.

Do not use `ChatOpenAI` for Jev.
Do not add TypeSafe to LiteLLM.
Both paths were tested and both fail because TypeSafe has no chat-completions endpoint.

A small client patch is strictly required by the contract.
It is not a configuration branch of the chat client.
It is a separate SystemOne client that reuses the OpenAI SDK transport, key, timeout, and retry stack.

## 2. Probe results

| Probe | Result |
| - | - |
| `GET /v1/models` raw | 200, `{"models":[{"name":"jev-latest"},{"name":"jev-preview"}]}` |
| `OpenAI.models.list()` | fails with `TypeError`; the catalog is not the OpenAI `data`/`id` page |
| `OpenAI.chat.completions.create(model=jev-latest)` | 404 `Not Found` |
| `ChatOpenAI(model=jev-latest, base_url=https://api.typesafe.ai/v1)` | 404 `Not Found` |
| `OpenAI.post("/systemone", cast_to=object)` | 200, model `jev-1.14.0`, Choice answer, usage `{input_tokens, output_tokens}` |
| `AsyncOpenAI.post("/systemone", cast_to=object)` | 200, 262 ms |
| `OpenAI.post("/systemone", cast_to=dict)` | client-side `ValueError: not enough values to unpack (expected 2, got 0)` |
| LiteLLM `openai/jev-latest` | 404 `Not Found` |
| LiteLLM `typesafe/jev-latest` | 400 `LLM Provider NOT provided` |
| LiteLLM provider registry | no `typesafe` provider in 1.96.0 |
| Direct module `TypeSafeSystemOne.ask` | 200, 267 ms, Choice `add_role` 0.75, cost `$1.533e-05` for 365 input tokens |

The `cast_to=object` detail is load-bearing.
`cast_to=dict` fails in openai 2.x even though the response is a JSON object.
Use `cast_to=object` and check `isinstance(result, dict)`.

## 3. Model catalog

The direct TypeSafe catalog exposes two names:

- `jev-latest`, which currently resolves to `jev-1.14.0`.
- `jev-preview`, the next-version preview.

The versioned name `jev-1.13` returns `400 Unknown model`.
`jev-1.13.0` and `jev-1.14` also fail.
The OpenRouter `typesafe/jev-1.13` offering is a different distributor alias and is not available on the direct key.

Consequence: the crawl policy pin must be `jev-latest` or `jev-preview`.
If a frozen `1.13` behavior is mandatory, TypeSafe direct cannot supply it today.

## 4. Client patch

The new module is `src/polymerhus/app/llm/typesafe.py`.

```python
async with TypeSafeSystemOne() as client:
    response = await client.ask(
        state={"page": ...},
        questions={"next": Choice(...)},
    )
```

The module does four things.

- Reads `API_KEY_TYPESAFE` and defaults to `https://api.typesafe.ai/v1`.
- Uses `AsyncOpenAI(...).post("/systemone", body=payload, cast_to=object)`.
- Rejects a response without an `answers` object.
- Reads the non-OpenAI model catalog through `GET /models` with `cast_to=httpx.Response`.

`providers.py` gains a `SYSTEMONE_PROVIDERS = {"typesafe"}` guard.
`build_chat_model("typesafe", ...)` fails with a clear error instead of sending a chat request.

The chat `PROVIDERS` table deliberately does not gain a `typesafe` entry.
This keeps the gateway sync and the chat client from treating TypeSafe as a chat model.
The env example documents `API_KEY_TYPESAFE`, `TYPESAFE_MODEL`, and `TYPESAFE_BASE_URL`.

Tests: `tests/test_typesafe_systemone.py`, six cases, all pass.
The gateway config test still passes, eight cases.

## 5. LiteLLM verdict

LiteLLM 1.96.0 does not support TypeSafe.

- It has no `typesafe` provider.
- Its `openai/` provider sends `POST /chat/completions`.
- TypeSafe returns 404 for that path.
- A custom LiteLLM handler could translate chat completions to SystemOne, but that is a new code path, not a configuration change.
- The typed Choice, Noul, and Score answers would also lose their structure through a chat envelope.

Configuration decision: keep TypeSafe out of `gateway/litellm_config.yaml`.
The gateway remains the chat-model transport.
The crawl policy calls `TypeSafeSystemOne` directly.
The gateway file now states this explicitly.

## 6. Why a small patch is required

The chat client cannot express the SystemOne contract.

- The request is `state` plus typed `questions`, not `messages`.
- The response is typed `answers`, not assistant text.
- There is no `tools`, `tool_choice`, or `response_format` surface.
- `ChatOpenAI` and LiteLLM both send `/chat/completions`, which returns 404.

The minimal patch reuses the same OpenAI SDK primitives and adds no dependency.
The optional `typesafe-sdk` would add a second Python package and uses `TYPESAFE_API_KEY`.
The OpenAI SDK path keeps `API_KEY_TYPESAFE` and the project's timeout and retry conventions.

TypeSafe Python SDK reference: https://docs.typesafe.ai/sdk/python.

## 7. Jev rerun result

`jev1` ran the general crawl with `TypeSafeSystemOne`.

- 6 pages and 60 actions.
- 21/21 XHR responses and bodies.
- 122 Jev calls and 0 errors.
- 338,985 input tokens and 23,461 output tokens.
- `$0.014237`.
- p50 206 ms and p95 361 ms.
- 0 observed unsafe endpoints.
- Safety recall 1.00 and precision 0.75.

`jev2` ran the targeted authz crawl.

- 6 pages and 20 actions.
- 39/39 XHR responses and bodies.
- 74 Jev calls and 0 errors.
- 224,251 input tokens and 22,388 output tokens.
- `$0.009419`.
- p50 190 ms and p95 282 ms.
- 36 unsafe controls removed, 34 by Jev and 2 by the guard.
- Safety recall 1.00 and precision 1.00.
- 0 observed unsafe endpoints and 0 authz PUTs.

`jev3` is the final integrated run.

- 7 pages and 59 actions.
- 1/1 registration form with 5/5 fields and HTTP 200.
- 73/73 XHR responses and bodies.
- 35 destruction controls removed, all by Jev.
- 0 of 2 authz openers removed; both were clicked and opened dialogs.
- 0 observed unsafe endpoints and 0 authz mutations.
- No-op local-state rate 51.0 percent; no-op all-actions rate 42.4 percent.
- 153 Jev calls and 0 errors.
- 411,882 input tokens and 36,916 output tokens.
- `$0.017299`.

The three Jev runs made 349 calls with zero errors and cost `$0.040955`.

The Jev transport is accepted.
The registration safe-write prompt works.
The destruction boundary is clean.
The authz boundary is incomplete and carries the accepted residual risk.

The evidence is in `docs/experiments/steel-crawl-proto-v2-measurement.md`.

## 8. Open items

1. Update the spec's Jev model pin from `jev-1.13` to `jev-latest` or `jev-preview`.
2. Add a TypeSafe cost override for the direct client: `$42` per Btok input and output free, which is `42e-9` USD per input token.
3. Decide whether `jev-preview` is acceptable for the P4 quality gate or whether `jev-latest` must be pinned at evaluation time.
4. Registration is now a safe write in the Jev prompt. Done and verified in jev3.
5. The duplicate search submission is skipped by the stable form key. Done; not exercised in jev3.
6. The authz hard guard and the symbolic unsafety guard are removed. Jev owns the decision. Done.
7. The keyword false positive path is removed with the guard. Done.
8. The final Jev-owned run is `crawl-jev3-20261102T154800Z`.
9. Add a coverage and effect signal to the policy. Pending.
10. Decide the authz residual risk or add explicit authz examples to the prompt. Pending.
