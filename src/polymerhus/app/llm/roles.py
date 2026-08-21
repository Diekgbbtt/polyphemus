import logging

from polymerhus.app.llm.capability import resolve_capability
from polymerhus.app.llm.negotiation import (
    Method,
    _PROBE_CACHE,
    _emit_probe_span,
    _probe_cache_key,
    _unknown_profile,
    negotiate_method,
    probe_with_invoker,
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
    escalating attempts, never re-attempted). Observable per resolution via
    langfuse span (D11) and log with provenance."""
    try:
        profile = resolve_capability(provider, model)
        method = negotiate_method(profile, no_tools_bound=True,
                                  schema_shape=schema_shape_of(schema))
        try:
            _emit_probe_span(
                provider,
                model,
                schema,
                method,
                getattr(profile, "source", None) if profile is not None else None,
                [method],
            )
        except Exception:
            logger.debug("one-shot resolution span emit failed for %s/%s", provider, model, exc_info=True)
        logger.info(
            "capability resolution: provider=%s model=%s schema=%s chosen=%s provenance=%s",
            provider,
            model,
            getattr(schema, "__name__", str(schema)[:80]) if schema is not None else "None",
            method,
            getattr(profile, "source", None) if profile is not None else None,
        )
        return method
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


def _method_for_probe(
    provider: str,
    model: str,
    schema,
    messages,
    temperature: float,
    role: str,
):
    """Resolve the method for an unknown profile via probe-on-miss (A2).

    Off the #73 axis: single-shot probe at construction, before the escalating
    wrapper, never re-probed mid-session. Resolve capability once, check
    `_unknown_profile`, then try DEGRADE_CHAIN in order validating the parsed
    result via `result_validates` - never parsing vendor error strings. Winner
    is held in `_PROBE_CACHE` per (provider, model, schema-class) and shared
    by the session. Fail-open (D7): a probe that misses every rung degrades to
    the semantic default and the session still starts. Observable per resolution
    via langfuse span (D11) and log with provenance."""
    try:
        profile = resolve_capability(provider, model)
    except Exception as exc:  # noqa: BLE001 - fail-open
        logger.warning(
            "one-shot method negotiation failed for %s/%s (%s); "
            "using the semantic default",
            provider,
            model,
            exc,
        )
        return _SEMANTIC_DEFAULT
    if not _unknown_profile(profile):
        return None  # signal caller to use normal negotiate path
    key = _probe_cache_key(provider, model, schema)
    if key in _PROBE_CACHE:
        winner = _PROBE_CACHE[key]
        return winner if winner is not None else _SEMANTIC_DEFAULT

    def invoker(method: Method):
        llm = build_chat_model(
            provider,
            model,
            temperature=temperature,
            max_retries=0,
            thinking=thinking_for(role),
        )
        return structured_output_for(llm, schema, method).invoke(messages)

    winner = probe_with_invoker(provider, model, schema, invoker, profile)
    return winner if winner is not None else _SEMANTIC_DEFAULT


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
    never sits on the #73 retry axis (#32's multiplied-retry defect stays dead).

    Unknown-to-registry models probe at construction (A2): the degenerate
    one-call session tries the rungs in DEGRADE_CHAIN order validating the parsed
    result, holds the winner per (provider, model, schema-class), and never
    re-probes mid-session - cold-start only, off the #73 axis, fail-open."""
    provider, model = resolve_role(role)
    method: Method | None = None
    if schema is not None:
        # Probe path for unknown profiles - off the #73 axis, held per schema-class.
        probed = _method_for_probe(provider, model, schema, messages, temperature, role)
        if probed is not None:
            method = probed
        else:
            # Known profile or probe miss signal - fall back to normal negotiate.
            method = _one_shot_method(provider, model, schema)

    def call(budget):
        llm = build_chat_model(provider, model, temperature=temperature,
                               read_timeout=budget, max_retries=0,
                               thinking=thinking_for(role))
        if schema is None:
            resp = llm.invoke(messages)
            return getattr(resp, "content", None) or None
        assert method is not None
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
