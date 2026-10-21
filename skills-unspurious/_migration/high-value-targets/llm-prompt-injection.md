# llm-prompt-injection - high-value targets (extracted for the threat-modeller migration)

## High-Value Targets

- Agents with tools that read private data or perform actions (send email, create tickets, run code)
- RAG systems over multi-tenant or user-supplied documents
- Features that echo model output into the DOM without encoding
- Assistants that see other users' data or internal system context
- Anything that forwards the model's text into another privileged system
