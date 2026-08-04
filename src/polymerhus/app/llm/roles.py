from polymerhus.app.llm.providers import (
    build_chat_model,
    invoke_with_escalating_timeout,
    resolve_role,
)


def chat_model_for(role: str, *, temperature: float = 0, max_retries: int | None = None):
    """Build the ChatOpenAI configured for an agent role. Multi-turn agents
    (crawl, tool-loops) use this and keep the client's per-turn retry; the agent's
    own iteration/job budget is the outer bound. Single-shot role callers should
    use `invoke_role` instead, which owns an escalating retry (#73)."""
    provider, model = resolve_role(role)
    return build_chat_model(provider, model, temperature=temperature, max_retries=max_retries)


def invoke_role(role, messages, *, schema=None, temperature: float = 0):
    """The single-shot LLM call for an agent role, with ONE coherent retry layer:
    an escalating per-attempt budget (#73). `schema=None` returns the free-text
    content (or None); a pydantic `schema` returns structured output via
    function_calling (or None on an unmet generation - the fail-closed signal).

    A FRESH client is built per attempt (`max_retries=0`, so the escalating wrapper
    is the sole retry), which also denies a provider that half-closed a pooled
    socket on a prior call the chance to hand this one a dead connection (#73
    defect B)."""
    provider, model = resolve_role(role)

    def call(budget):
        llm = build_chat_model(provider, model, temperature=temperature,
                               read_timeout=budget, max_retries=0)
        if schema is None:
            resp = llm.invoke(messages)
            return getattr(resp, "content", None) or None
        return llm.with_structured_output(schema, method="function_calling").invoke(messages)

    return invoke_with_escalating_timeout(call)
