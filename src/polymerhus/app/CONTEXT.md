# app - module context (technical supporting layer)

`src/polymerhus/app/` is the shared technical supporting layer the bounded contexts sit on.
It owns no domain language of its own (see `CONTEXT-MAP.md`), yet its sub-modules carry the fundamentals every context's runtime depends on.
This file records those fundamentals and the implementation patterns to repeat.
It is explicitly not a bounded-context glossary: the meaning of what these modules persist, execute, or invoke belongs to the consuming contexts.

## Sub-modules

- `llm/` - the LLM client layer: the provider table and client construction (`providers.py`), the role registry and the one-shot/session seams (`roles.py`, `session.py`, `actor.py`), parsing-error recovery at the session seam (`parsing_recovery.py`), the token-usage ledger (`usage.py`), capability negotiation (`capability.py`, `negotiation.py`), reasoning replay (`reasoning.py`), context compaction (`compaction.py`), the product-skill loader (`skills.py`), the gateway sync (`sync.py`, `sync_mapping.py`), and the conversation scope (`conversation.py`).
- `auth/` - the per-project shared auth store and its agent tool (`store.py`, `tool.py`, `records.py`); the operator seed face is a thin adapter over the same seam (`project_management/api.py`).
- `data_root.py` - the one layout owner for the app-owned data root (`<repo>/data/`): every store resolves its bucket through `project_dir`, so no module hand-builds a path.
- `runtime.py` - the module runtime/registry: run holds and the session lifecycle.
- `observability/` - Langfuse callbacks and tracing.
- `gateway_entrypoint.py` - the container entrypoint: proxy first, health poll, sync, then the agent ASGI.
- `clients/`, `config.py`, `logging_config.py`, `main.py` - the HTTP/ASGI shell and process configuration.

## Fundamental decisions

- **One construction point per concern.** Every LLM client is built by `build_chat_model` (`llm/providers.py`), which the session and one-shot seams and every module share. Every storage path resolves through `data_root`. Store writes go through the owning store (`write` / `replace_operator_state`), never around it: the agent tool and the operator API are thin adapters.
- **Mode selection is one env var, never a branch per caller.** `LLM_GATEWAY_URL` unset means direct per-provider mode; set means the co-located gateway, which owns id translation and upstream routing (`docs/design/llm-gateway-100-decisions.md`, ADR D3/D5).
- **Provider policy lives in tables with safe defaults.** `PROVIDERS`, `_ID_KIND_BY_PROVIDER` / `id_kind()`, and `_REQUEST_HEADERS_BY_PROVIDER` / `request_headers()` are the one place a provider's policy sits; an unlisted provider gets the transparent default (verbatim ids, no bound headers), so a new provider is a one-line table entry.
- **Fail-open at read boundaries, fail-loud at write boundaries.** A missing or unreadable store file reads as a valid empty, loudly; a write that cannot read its target refuses (`store_unavailable`) rather than overwriting blind; a shape violation refuses with a coded error naming the field.
- **Server-stamped facts are never trusted from the client.** `origin` and `updated_at` are stamped server-side on every write and seed; a client-supplied value is dropped, never merged.
- **Ambient context is scoped, not global.** Cross-cutting identity travels in ContextVars (`conversation_scope`, the checkpoints module context, the runtime run hold); each is set for a bounded scope and restored on exit, so nothing leaks between turns or sessions.
- **Bind at the native layer before wrapping.** Where the stack already has the mechanism, use it: client request headers ride `ChatOpenAI.default_headers` (the SDK threads them into the httpx client), never hand-rolled request mutation. The reasoning-passthrough subclass is the one justified wrapper, and its SDK-internal seams are pinned by contract tests that turn red on a version bump.
- **Durability is per-record, not per-file.** Every store write is atomic (same-directory temp file + `os.replace`) and serialised per project (one lock per id covering the whole check-then-write), so concurrent writers converge instead of forking records.
- **A checkpointed trail must satisfy the tool-call/response pairing contract.**
  The upstream now enforces pairing only - a valid or malformed assistant tool call with no answering `tool` message is rejected with HTTP 400, and symmetrically a `tool` message with no preceding assistant call is rejected too, so the pairing contract must hold in BOTH directions - while the arguments' JSON validity is irrelevant, so an error `ToolMessage` answer is a complete, contract-valid repair; the pinned wire serializer (`langchain_openai.chat_models.base._convert_message_to_dict`) emits both `tool_calls` and `invalid_tool_calls` as `tool_calls`, which is why a checkpointed parse failure poisons every later request.
  `create_agent` never ported `AgentExecutor.handle_parsing_errors` (langchain issue #33504, PR #35818 closed unmerged), so the session seam owns the recovery: `app/llm/parsing_recovery.py` is wired FIRST in `session._build_agent`.
  Its `after_model` answers the TAIL REQUEST's unanswered `invalid_tool_calls` entries with an error `ToolMessage`, jumping back to the model for a bounded in-turn retry - where the tail request is the last assistant tool-call request whose only trailing messages are its own `tool` answers.
  Walking back over those trailing answers is what covers the structured-output path (F13): `create_agent._handle_model_output` appends the structured call's answer INSIDE the model node, so a sibling malformed ordinary call - the observed `graph_view` case - would otherwise sit one message behind the literal tail and stay unanswered (the ordinary-tool sibling of #296's malformed structured call, which the literal tail already covered).
  The answer is appended at the tail; a `HumanMessage` (or a later assistant message) is a stop boundary and is never crossed, so answering a stale call before one would append a `tool` message with no adjacent call (an orphan answer, rejected symmetrically) - the #280 follow-up, where the old whole-trail scan did exactly that.
  The jump is suppressed when the turn is already resolving (a trailing `tool` answer) or a valid `tool_calls` entry is still unanswered and ToolNode must run it; jumping there would bypass the tools routing and leave that valid call unanswered.
  Valid `tool_calls` are never touched - ToolNode owns those and runs after `after_model`.
  Its `before_model` reconciles a RESUMED turn positionally: the seam reads the framework's pending-next variable (`StateSnapshot.next`) before invoking and passes it as `session_pending_next` metadata, and only then does `before_model` insert each missing answer immediately after the assistant call it answers, because the upstream requires the tool answer to directly follow the call.
  The read sits at the seam because the module checkpointer prunes to the latest checkpoint per thread, so the interrupted parent tuple is gone once the new input is written.
  A normal, completed turn carries no signal and is left untouched, so pre-existing completed-turn poison is deliberately not auto-repaired.
  Recovery never drops or rewrites a message to hide the violation from the wire (#280).

## Patterns to repeat

- Provider request primitives live in the provider table and are evaluated at construction (D12): the session seam binds the conversation as an ambient scope, the construction reads it, and unlisted providers stay byte-identical.
- A pattern that fails open (tracing, capability resolution, an absent conversation) must say so loudly and never gate the caller; fail-loud is reserved for write corruption and contract violations.
- Write the decision down in the owning ledger before or with the code, and keep the module path pointers honest.

## Glossary

- **usage ledger** - the process-wide, per-project, per-agent token accumulator (`app/llm/usage.py`) the session seam records into and the app API exposes read-only as a two-axis typed surface: `context_tokens` (`cached` from `input_token_details.cache_read`; `uncached` = `input_tokens - cache_read`, because on the pinned path `input_tokens` is INCLUSIVE of cache_read) and `generated_tokens` (`reasoning` from `output_token_details.reasoning`, `visible` from output minus reasoning), plus the raw scalar `total_tokens` (context + generated) and the scalar `capped_tokens` (generated + uncached = `total_tokens - cached`; retained for callers). The trial's token-budget axis is `generated_tokens` (reasoning + visible), so input (cached or not) never consumes it (2026-10-05). A missing/blank project id lands in the unscoped bucket, which a project snapshot never returns.
- **voluntary function calling** - the A6 negotiated rung for a model whose upstream refuses a forced `tool_choice`: the schema tool is bound, the choice is not forced, the provider decides (a relaxed model rewrites the force to `"auto"` at bind time).
- **capability override** - the operator-declared correction of a registry claim, via `LLM_CAPABILITY_OVERRIDES` (e.g. a thinking-mode relay refusing a forced tool choice that models.dev cannot express).
