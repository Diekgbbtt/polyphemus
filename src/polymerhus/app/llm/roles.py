import logging

from polymerhus.app.llm.capability import resolve_capability
from polymerhus.app.llm.negotiation import (
    Method,
    negotiate_method,
    result_validates,
    schema_shape_of,
)
from polymerhus.app.llm.providers import (
    build_chat_model,
    invoke_with_escalating_timeout,
    resolve_role,
    thinking_for,
)

logger = logging.getLogger(__name__)

# The A1 semantic default for the no-tool rung (unknown/absent profile); D7
# fail-open lands here on any resolution/negotiation miss.
_SEMANTIC_DEFAULT: Method = "json_schema"


def _one_shot_method(provider: str, model: str, schema) -> Method:
    """The structured-output method for one `invoke_role` call: resolve the
    held capability profile once and consult the PURE negotiate contract with
    `no_tools_bound=True` (the one-shot path never binds tools). Fail-open
    (D7): ANY resolution or negotiation failure lands the semantic default and
    the call still proceeds - and capability stays OFF the #73 retry axis (a
    single synchronous resolve-and-hold read at call start, never inside the
    escalating attempts, never re-attempted)."""
    try:
        profile = resolve_capability(provider, model)
        return negotiate_method(profile, no_tools_bound=True,
                                schema_shape=schema_shape_of(schema))
    except Exception as exc:  # noqa: BLE001 - fail-open: never block the call
        logger.warning("one-shot method negotiation failed for %s/%s (%s); "
                       "using the semantic default", provider, model, exc)
        return _SEMANTIC_DEFAULT


def structured_output_for(llm, schema, method: Method):
    """Build the `with_structured_output` wrapper for a negotiated method.

    Construction form (locked by the A4 pin tests): the `json_schema` rung
    passes the DICT schema (`model_json_schema()`) because that is the ONLY
    construction honouring `strict=False` on the wire - a pydantic-CLASS
    schema silently defaults to `"strict": true`, the exact #44 open-dict 400
    the negotiation exists to avoid. `function_calling` / `json_mode` pass the
    pydantic class, the proven mainline construction. A non-pydantic target
    (a raw JSON-schema dict) rides the rung verbatim."""
    if method == "json_schema":
        as_dict = getattr(schema, "model_json_schema", None)
        construction = as_dict() if callable(as_dict) else schema
        return llm.with_structured_output(construction, method="json_schema",
                                          strict=False)
    return llm.with_structured_output(schema, method=method)


def chat_model_for(role: str, *, temperature: float = 0, max_retries: int | None = None):
    """Build the ChatOpenAI configured for an agent role. Multi-turn agents
    (crawl, tool-loops) use this and keep the client's per-turn retry; the agent's
    own iteration/job budget is the outer bound. Single-shot role callers should
    use `invoke_role` instead, which owns an escalating retry (#73).

    The role's declared `thinking` baseline (#94) rides along, so a session/stateful
    agent built off this factory reasons at its configured effort."""
    provider, model = resolve_role(role)
    return build_chat_model(provider, model, temperature=temperature,
                            max_retries=max_retries, thinking=thinking_for(role))


def invoke_role(role, messages, *, schema=None, temperature: float = 0):
    """The single-shot LLM call for an agent role, with ONE coherent retry layer:
    an escalating per-attempt budget (#73). `schema=None` returns the free-text
    content (or None); a pydantic `schema` returns structured output via the
    capability-negotiated method (#99, ADR A1) - `json_schema` strict=False on a
    structured-output profile (or the unknown-profile semantic default),
    `function_calling` on a tool-calling-only profile, `json_mode` with the
    mandatory parse-validation contract on a neither-profile (or None on an
    unmet / wrong-shape generation - the fail-closed signal).

    A FRESH client is built per attempt (`max_retries=0`, so the escalating wrapper
    is the sole retry), which also denies a provider that half-closed a pooled
    socket on a prior call the chance to hand this one a dead connection (#73
    defect B). The method is chosen ONCE per logical call - before the retry, so
    every attempt retries the SAME negotiated method and capability resolution
    never sits on the #73 retry axis (#32's multiplied-retry defect stays dead)."""
    provider, model = resolve_role(role)
    method = _one_shot_method(provider, model, schema) if schema is not None else None

    def call(budget):
        llm = build_chat_model(provider, model, temperature=temperature,
                               read_timeout=budget, max_retries=0,
                               thinking=thinking_for(role))
        if schema is None:
            resp = llm.invoke(messages)
            return getattr(resp, "content", None) or None
        parsed = structured_output_for(llm, schema, method).invoke(messages)
        # The negotiation contract's parse validation (A1): a rung's result is
        # the PARSED form validated against the target - json_mode's silent
        # wrong-shape failure (HTTP 200, wrong JSON) is a miss that escalates,
        # never accepted. `result_validates` never raises (class = validate,
        # dict = shape-check).
        if not result_validates(parsed, schema):
            return None
        if method == "json_schema":
            # The dict-form construction returns a raw dict for a pydantic
            # target; hand the one-shot callers the instance they consume (the
            # same class-form validation the predicate just ran). A non-pydantic
            # target's verbatim dict rides through untouched.
            validate = getattr(schema, "model_validate", None)
            return validate(parsed) if callable(validate) else parsed
        return parsed

    return invoke_with_escalating_timeout(call)
