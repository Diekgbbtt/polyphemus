from agent.app.llm.providers import resolve_role, build_chat_model

def chat_model_for(role: str, *, temperature: float = 0):
    """Build the ChatOpenAI configured for an agent role."""
    provider, model = resolve_role(role)
    return build_chat_model(provider, model, temperature=temperature)
