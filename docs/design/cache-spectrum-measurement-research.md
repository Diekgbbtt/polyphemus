# Cache-spectrum measurement: reliability research

*Status: research deliverable (no code changed). Date: 2026-10-15.*
*Scope: how to obtain a reliable per-session cache spectrum (cached vs fresh input tokens) for the eval pipeline, given that the local LiteLLM gateway intermittently omits or mangles cache usage detail on streamed responses.*
*Evidence base: the running local stack (agent container `polymerhus-agent-1`, gateway on `http://localhost:4000`, model `opencode-go/deepseek-v4.1-flash`), captured wire/stream/usage artifacts, and the pinned source of litellm 1.96.0, langchain-openai 1.3.2, and langfuse.*

*Resolution (2026-10-15, same day): the recommended primary fix landed as `src/polymerhus/app/gateway_proxy_bootstrap.py` - the entrypoint launches the proxy CLI through it, the patch is pinned to 1.96.0 and unit-tested against the real release (fail-open, idempotent).*
*In-container A/B on the running stack: the unpatched proxy returned streamed `prompt_tokens=3614` with no details on 2 of 3 calls; the patched proxy returned `7215` with `cached_tokens=7040` on 3 of 3, matching the nonstream twin.*
*The N5 flag now rides `SPECTRUM_FIELDS` and the trial's `token_spectrum` (with the C4 reading rules amended), and the bounded nonstream probe seam stays DEFERRED as the documented fallback (phasing step 2) - dormant while the gateway is correct, to be built if a silence recurs.*

## Recommendation (short)

Fix the gateway hop, not the app.
The streamed cache detail is lost inside litellm 1.96.0, which the gateway pins (`gateway/requirements.txt`, ADR D10).
Upgrade or patch that pin so streamed usage keeps `prompt_tokens_details`.
Add a cheap nonstream probe as a bounded fallback for calls the gateway marks as detail-omitted (N5).
Thread the N5 omission count into the trial record so the cached axis is never read as a measured miss.

Exact files that must change:

- `gateway/requirements.txt`: bump or patch the pinned `litellm[proxy]==1.96.0` so the streamed usage assembly keeps `prompt_tokens_details`.
- `src/polymerhus/app/llm/providers.py`: keep `stream_usage=True` (`build_chat_model`, line 939) as the primary source, and add the bounded nonstream probe seam behind the ledger.
- `src/polymerhus/app/llm/usage.py`: keep `cache_detail_omitted` (`CACHE_DETAIL_OMITTED_FIELD`, line 63; `_cache_read_omitted`, line 106) and let a probe correct the axis when the record is flagged.
- `eval/orchestrator/api.py`: add `cache_detail_omitted` to `SPECTRUM_FIELDS` (line 364) and project it in `usage_spectrum` (line 385); today the projection drops it.
- `eval/orchestrator/trial.py`: carry the omission signal into `token_spectrum` (`_finish`, line 1031) so a flagged entry is not read as a cache miss.
- `docs/design/eval-token-spectrum-349-adr.md` and the results methodology (`docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`, C4, lines 77-86): record that the cached axis is sampled and gated.

## Scope and method

The task is a research deliverable, so this document changes no code.
It answers four questions against primary sources: the pinned litellm/langchain/langfuse source in `.venv`, the repo source, and live probes against the local gateway.
Every claim below is tagged with a `path:line` citation or a captured artifact.
The probes are cheap: tiny `max_completion_tokens` on an already-warm prefix.
Only the local stack was touched; `eval-server-1` was never contacted.

Provider/model under test: `opencode-go/deepseek-v4.1-flash`, reached only through the local gateway.
Direct-to-upstream probes are blocked by Cloudflare without a browser or SDK User-Agent, so the gateway is the only observable hop.

## Where the cache spectrum is consumed today

The app records each model call's native `usage_metadata` in a process-wide ledger (`src/polymerhus/app/llm/usage.py`).
The ledger decomposes input into `cached` (cache read) and `uncached` (fresh input), and output into `reasoning` and `visible` (`_axis_totals`, `usage.py:113-158`).
Two scalars ride the surface: `total_tokens` (cache-inclusive) and `capped_tokens = generated + uncached` (the budget axis) (`usage.py:20-25`, `usage.py:150-157`).
The app exposes the ledger read-only at `GET /projects/{project_id}/usage` (`src/polymerhus/project_management/api.py:158`).
The eval harness reads that endpoint and bounds a trial by `capped_tokens` (`api.usage_capped`, `eval/orchestrator/api.py:343`; `Trial._check_spend`, `eval/orchestrator/trial.py:909`).
At terminal the harness projects the same read into a per-agent `token_spectrum` on the trial record (`eval/orchestrator/api.py:364-418`, `trial.py:1027-1050`).
The results methodology reads the spectrum for the C4 cache metrics `cached_share_total` and `cached_share_worst_proposer` (`docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md:77-86`, `:160-164`).

So one streamed usage number drives the budget guard, the trial record, and the results metrics.
When the gateway drops the cache detail, all three drift together.

## Q1 - Which endpoint or probe yields a reliable per-session cache spectrum?

Finding: a nonstream call to the gateway returns the full spectrum; a streamed call usually does not.

The reliable measurement seam is a **nonstream** `POST /v1/chat/completions` to the gateway (`http://localhost:4000`).
It must carry the same `x-opencode-session` header and the same leading prefix bytes (system prompt plus tool specs) as the session under test, and a tiny `max_completion_tokens`.
On that call the response `usage` carries `prompt_tokens` (tools included) and `prompt_tokens_details.cached_tokens`.

Captured evidence on the same warm prefix and session:

- `sdk-a-raw` (nonstream SDK, async): `prompt_tokens=7215 details={"cached_tokens": 7040}` (full).
- `sdk-a-str`, `sdk-s-str`, `u-v1-min`, `u-root-min`, `u-root-apphdr` (streamed, all client shapes): `prompt_tokens=3614 details=null` (degraded).
- `matrix3` nonstream on session `matrix3-fresh-A:mechanism_typist`: `prompt_tokens=7215 ... "cached_tokens": 7040` (full).
- `matrix3` streamed on the same session: `prompt_tokens=3614` with no `prompt_tokens_details` (degraded).
- `tc_capture.out` nonstream forced-tool calls: `prompt_tokens=4673 ... "cached_tokens": 4672` (full).

These are recorded in the captured outputs `/srv/probe/matrix2.out`, `/srv/probe/matrix3.out`, and `/srv/probe/tc_capture.out`.

The degraded streamed number is provably the messages-only tokenizer count, not the real prompt length.
For the captured dev body (system plus user plus 5 tools) litellm's own counter gives `msgs_only=3614` and `with_tools=6025`, while the real prompt is `7215` (computed locally with `.venv` litellm, zero network cost).
So the streamed `3614` excludes the tools and the cache entirely.

Endpoint survey:

| Seam | Cache spectrum? | Verdict |
|---|---|---|
| `POST /v1/chat/completions` (nonstream) | `prompt_tokens` + `prompt_tokens_details.cached_tokens` | reliable |
| `POST /v1/chat/completions` (stream) | usually `prompt_tokens` only, no details | unreliable |
| `GET /projects/{id}/usage` (app ledger) | inherits the streamed call's usage | reliable only if the seam is |
| `GET /spend/logs` (master key only) | the same synthesized usage | not a source of truth |
| `GET /key/info`, `GET /model/info`, `GET /v1/models` | no cache spectrum | not usable |
| `GET /metrics` | 404 on this gateway | not usable |

`GET /spend/logs` requires the master key (the virtual key gets 401), and it records the same synthesized usage, so it inherits the degradation.
Langfuse inherits the degradation too, because it reads the client-side `usage_metadata` (see Q3).

Design implication: a nonstream probe on the same session and identical prefix bytes reads an accurate cache spectrum, and it does not perturb the session prefix.

## Q2 - What must the eval harness change to consume a reliable spectrum?

Finding: the harness needs no new endpoint, but it must lose less signal and must not read a flagged axis as a measured miss.

Three concrete gaps:

1. The omission signal never reaches the record.
   `app/llm/usage.py` computes `cache_detail_omitted` per entry and exposes it in `_entry_surface` (`usage.py:157`, `usage.py:177`).
   `eval/orchestrator/api.py::usage_spectrum` projects only the eight `SPECTRUM_FIELDS` (`api.py:364-373`, `api.py:385-418`) and drops `cache_detail_omitted`.
   So the trial record's `token_spectrum` cannot tell a reported 0% share from a provider that stayed silent.
   Fix: add the count to `SPECTRUM_FIELDS` and project it.

2. The budget guard can false-stop.
   `capped_tokens = generated + uncached` and `uncached = input_tokens - cache_read` (`usage.py:145-157`).
   A degraded call yields `input_tokens=3614` and `cache_read=0`, so `uncached=3614`.
   The real value with cache is far smaller (for the full 7215/7040 case, `uncached=175`).
   So a degraded budget axis inflates, and `Trial._check_spend` (`trial.py:909-940`) can stop a trial early.
   Fix: gate the budget read on the omission count, or correct it with the probe.

3. The N5 alarm exists but is not consumed downstream.
   The spec defines `cache_detail_omitted` as the count of silent calls, and says a fraction read against `cache_detail_omitted == calls` is unaudited (`docs/design/eval-token-tracking-spec.md:106-118`).
   The flag is recorded but nothing downstream reads it.
   Fix: carry it into `token_spectrum` and into the results methodology.

Harness changes, in one sentence each:

- Add `cache_detail_omitted` to the flat spectrum and to the trial record.
- When the entry is fully flagged, mark the cached axis as unknown rather than zero.
- When a probe seam exists, record the probe-corrected spectrum as the authoritative cached axis.
- Document in the C4 methodology that the cached axis is sampled and gated.

## Q3 - Which client layers lose or mangle cache usage detail?

Finding: exactly one hop loses the detail (litellm's streamed usage assembly); every later hop faithfully propagates the loss.

Layer 1 - the gateway (litellm 1.96.0), the lossy hop.
`litellm/litellm_core_utils/streaming_handler.py:1463` runs `model_response.usage = chunk.usage` when the usage-bearing chunk also carries choices.
That overwrites the converted litellm `Usage` with the raw `openai.types.completion_usage.CompletionUsage` (a pydantic model).
Downstream, `litellm/litellm_core_utils/streaming_chunk_builder_utils.py:462` `_usage_chunk_calculation_helper` guards with `if "prompt_tokens" in usage_chunk:` (line 472).
That `in` test is false for `CompletionUsage` (proven: `"prompt_tokens" in litellm.types.utils.Usage` is True, `"prompt_tokens" in CompletionUsage` is False).
So `prompt_tokens` reads 0 and `prompt_tokens_details` reads None.
Then `calculate_usage` (`streaming_chunk_builder_utils.py:719`) falls back at line 749: `returned_usage.prompt_tokens = prompt_tokens or token_counter(model=model, messages=messages)`.
That fallback counts messages only, excludes tools, and leaves the details map empty.
This is the exact `3614` value observed (see Q1).

The mechanism is chunk-shape dependent.
When the provider sends usage in a separate `choices=[]` chunk, `chunk_creator` early-returns before line 1463 and the converted `Usage` keeps the details (full).
When the provider attaches usage to the finish chunk, line 1463 overwrites it (degraded).
`stream_options.include_usage=True` requests the separate chunk but does not guarantee it through this relay, which is why the shape is time-intermittent.

Layer 2 - langchain-openai 1.3.2, faithful propagation.
`_create_usage_metadata` (`langchain_openai/chat_models/base.py:4021`) sets `input_tokens = prompt_tokens` and `input_token_details.cache_read = prompt_tokens_details.cached_tokens`.
When the details map is absent, `cache_read` is omitted.
So a degraded stream yields `input_tokens=3614` and no `input_token_details`.

Layer 3 - the app ledger, faithful propagation plus the N5 flag.
`app/llm/usage.py:_axis_totals` (line 113) computes `uncached = input_tokens - cache_read` (`usage.py:148`).
`_cache_read_omitted` (`usage.py:106-110`) returns 1 when `input_token_details` is absent, which is the degraded shape.
So the ledger does flag the silence, but the numeric axis still inflates to `uncached=3614`.

Layer 4 - langfuse, faithful propagation with the flag dropped.
`langfuse/langchain/CallbackHandler.py:1517` `_parse_usage_model` maps `input_tokens` to `input` and subtracts `cache_read`, emitting `input_cache_read` when present.
It does not preserve any omission flag.
Observed downstream shape: a degraded generation shows `usageDetails.input=3614` with no `input_cache_read` key (`local_probe_io.json:750`), while a full generation shows `input=1010`, `input_cache_read=7040`, `inputUsage=8050` (`assigner_g2.json:1093-1101`).

Layer 5 - the eval spectrum, drops the flag (see Q2).

Net: the loss has one origin (litellm 1.96.0) and no compensating layer, because litellm is the only hop that both observes the real prompt size and writes the usage the client sees.

## Q4 - What design should we adopt, and what fallbacks and risks apply?

Recommended design (primary): fix the gateway pin.

Upgrade litellm to a release where the streamed usage assembly keeps the details, or apply a minimal patch to the pinned 1.96.0.
The patch target is `_usage_chunk_calculation_helper` (`streaming_chunk_builder_utils.py:472`): make the guard tolerate the pydantic model, for example a `hasattr`/`model_dump` read instead of the `in` test.
A version bump is a one-file review by ADR D10, so the change is `gateway/requirements.txt`.
After the fix, the app's existing `stream_usage=True` path (`providers.py:939`) produces accurate details with no app change.
`cache_detail_omitted` stays as a belt-and-braces alarm.

Fallback (secondary): a bounded nonstream probe seam.

When a streamed call is recorded with `input_token_details` absent (the N5 case), issue one nonstream measurement call on the same session id and the same leading prefix bytes.
Record its `prompt_tokens` and `prompt_tokens_details.cached_tokens` as the authoritative cached axis for that call.
Keep `max_completion_tokens` tiny; the prefix is already warm, so the probe is cheap.
Do not append the probe turn to the session, only send it with the same `x-opencode-session` header and prefix.
Bound the cost by probing only flagged calls, so a healthy (fixed) gateway pays nothing.

Rejected alternatives:

- Read `/spend/logs`: it records the same synthesized usage and needs the master key.
- Read Langfuse usage details: same client-side source, so same loss.
- Direct-to-upstream capture: Cloudflare-blocked without a browser or SDK User-Agent.
- Force `include_usage` and trust it: the relay does not always honour it (loop probe degraded 10/10 with it set).

Phasing:

1. Gateway fix first; re-run the loop probe and expect streamed details to match nonstream.
2. Add the probe seam only as a guard behind the N5 flag, so it stays dormant when the gateway is correct.
3. Thread `cache_detail_omitted` into `SPECTRUM_FIELDS` and the trial record regardless, because the flag is cheap and the silence is real.

## Live evidence summary

| Probe | Transport | Session | Result | Artifact |
|---|---|---|---|---|
| `sdk-a-raw` | nonstream SDK | `replay-matrix-2:mechanism_typist` | `pt=7215 cached=7040` full | `/srv/probe/matrix2.out` |
| `sdk-a-str` | stream SDK | same | `pt=3614 details=null` degraded | `/srv/probe/matrix2.out` |
| `sdk-s-str` | stream SDK | same | `pt=3614 details=null` degraded | `/srv/probe/matrix2.out` |
| `u-v1-min` / `u-root-min` / `u-root-apphdr` | stream urllib | same | `pt=3614 details=null` degraded | `/srv/probe/matrix2.out` |
| nonstream | stream=False raw | `matrix3-fresh-A:mechanism_typist` | `pt=7215 cached=7040` full | `/srv/probe/matrix3.out` |
| stream | stream=True raw | same | `pt=3614 no details` degraded | `/srv/probe/matrix3.out` |
| forced-tool nonstream | nonstream urllib | `g2_session` | `pt=4673 cached=4672` full | `/srv/probe/tc_capture.out` |
| local tokenizer check | none (local) | n/a | `msgs_only=3614`, `with_tools=6025` | computed with `.venv` litellm |
| langfuse degraded | inherited | `wire-probe-chain:mechanism_typist` | `input=3614`, no `input_cache_read` | `local_probe_io.json:750` |
| langfuse full | inherited | arm G2 assigner | `input=1010`, `input_cache_read=7040` | `assigner_g2.json:1093-1101` |

Supporting observations:

- The degradation is intermittent: a production-path probe once returned full 3/3 (`prod_probe.py`), and a later side-by-side streamed probe returned degraded 8/8 (`sidebyside_probe.py`).
- The client path toggles nothing: the degraded shape appears for raw urllib, the sync SDK, and the async SDK alike, all streamed.
- Provider cache facts observed live: cached counts are block-aligned (multiples of 16, for example 3840, 7040, 7168), a fresh session shared a cached prefix (7040), and the cache TTL exceeded 13.5 hours.
- The 348 diagnosis already saw the same omission for `mechanism_typist` and treated the null details as a provider property (`docs/design/348-failure-diagnosis.md:28`, `:132`, `:461-465`); this research shows the gateway hop can manufacture the same null.
- The typist cache-collapse diagnosis likewise frames a per-role null as provider-side; the probe evidence here means the gateway hop must be excluded before that conclusion holds (`docs/experiments/typist-cache-collapse-diagnosis.md`).

## Open risks and non-goals

- Upgrade risk: a litellm bump touches many behaviours; pin and re-verify with the loop probe plus the forced-tool and tool-bearing cases.
- Patch risk: a local patch to a pinned release drifts from upstream; prefer an upstream fix or a version that carries it.
- Intermittency: the relay's chunk shape is not under our control, so even a correct client cannot guarantee a separate usage chunk without the gateway fix.
- Nonstream assumption: nonstream carried the details in every observation, but this is observed behaviour, not a contract; keep the N5 alarm.
- Probe cost: each probe is a real call; probe only flagged calls and keep the output budget tiny.
- Probe perturbation: the probe must reuse the prefix bytes and the session header without appending a turn; a probe that changes the prefix measures a different cache state.
- Sampling: a probe measures one instant; the prefix changes between calls, so the spectrum is sampled, not continuous.
- Cross-provider: the fix must hold for every provider the gateway relays, not only `opencode-go`.
- TTL: a probe near cache expiry can report a miss that is a TTL effect, not a prefix mismatch.
- Non-goal: detecting a provider-exclusive `input_tokens` convention is out of scope here; the ledger already documents that non-goal (`usage.py:125-128`).

## Sources

Repo:

- `src/polymerhus/app/llm/usage.py` (ledger, `_axis_totals` line 113, `_cache_read_omitted` line 106, `CACHE_DETAIL_OMITTED_FIELD` line 63).
- `src/polymerhus/app/llm/providers.py` (`build_chat_model` line 846, `stream_usage=True` line 939).
- `src/polymerhus/project_management/api.py` (`GET /projects/{id}/usage` line 158).
- `eval/orchestrator/api.py` (`usage_capped` line 343, `SPECTRUM_FIELDS` line 364, `usage_spectrum` line 385).
- `eval/orchestrator/trial.py` (`_check_spend` line 909, `_terminal_usage` line 993, `token_spectrum` line 1031).
- `gateway/requirements.txt` (pinned `litellm[proxy]==1.96.0`).
- `docs/design/eval-token-tracking-spec.md` (N5, lines 106-118).
- `docs/design/eval-token-spectrum-349-adr.md` (accepted ADR).
- `docs/design/348-failure-diagnosis.md` (H1 provider-omission, lines 28, 132, 461-465).
- `docs/design/session-cache-measurement-348-adr.md` (measurement record).
- `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md` (C4, lines 77-86, 160-164).
- `docs/experiments/typist-cache-collapse-diagnosis.md` (per-role null framing).

Pinned third-party source (`.venv`):

- litellm 1.96.0: `litellm/litellm_core_utils/streaming_handler.py:1463`.
- litellm 1.96.0: `litellm/litellm_core_utils/streaming_chunk_builder_utils.py:462`, `:472`, `:719`, `:749`.
- langchain-openai 1.3.2: `langchain_openai/chat_models/base.py:4021`.
- langfuse: `langfuse/langchain/CallbackHandler.py:1517`.

Captured probe artifacts (temporary, not committed):

- `/srv/probe/matrix2.out`, `/srv/probe/matrix3.out`, `/srv/probe/tc_capture.out` (in `polymerhus-agent-1`).
- `/private/var/folders/gs/p9fl4f1s1yqfl8801x50nhjc0000gn/T/opencode/lf/`: `wire_records.json`, `replay_shapes.json`, `local_probe_io.json`, `assigner_g2.json`, and the probe scripts (`loop_probe.py`, `prod_probe.py`, `sidebyside_probe.py`, `counter_probe.py`).
