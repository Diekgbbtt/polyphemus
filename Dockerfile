FROM redamon-agent:latest
WORKDIR /srv
COPY src/ /srv/src/
COPY db/ /srv/db/
COPY skills/ /srv/skills/
COPY gateway/ /srv/gateway/
COPY requirements-observability.txt requirements-crawl.txt requirements-gateway.txt /srv/
# Optional lightweight tracing dependency (Langfuse). Layered on top of the
# base image; the agent runs fine without it (tracing fail-open no-op), but
# baking it in lets operators enable tracing purely via LANGFUSE_* env vars.
RUN pip install --no-cache-dir -r /srv/requirements-observability.txt
# Agentic-crawl (Steel) client libs - the base image was assumed to provide
# these but does not, so steel_crawl degraded to empty manifests. Cloud browser
# over CDP, so no `playwright install` (local browsers) is needed.
RUN pip install --no-cache-dir -r /srv/requirements-crawl.txt
# LLM API gateway (#100) - the co-located litellm proxy (#104 T1) layered on
# top of the base image like the observability/crawl layers. A litellm version
# bump is a one-file review of `requirements-gateway.txt` (ADR D10). httpx is
# pinned for the models.dev fetch (no separate client package; plain JSON
# endpoint). The agent normally uses litellm transitively only; the gateway
# subprocess is the only direct consumer.
RUN pip install --no-cache-dir -r /srv/requirements-gateway.txt
# src/ layout: the polymerhus package is under /srv/src, and the skills/ mount
# sits at /srv/skills - a sibling of src/, exactly as skills.py resolves it
# (Path(__file__).parents[4] / "skills").
ENV PYTHONPATH="/srv/src:/app"
# The gateway proxy's config path - litellm loads this on boot. See
# `gateway/litellm_config.yaml` (empty model_list filled by T2 via the mgmt API
# + the D8 auto-inject stanza + store_model_in_db). Secrets stay env-only.
# `CONFIG_FILE_PATH` is litellm's documented env var name; the entrypoint also
# forwards the path to the `litellm` CLI via `--config` (belt and suspenders).
ENV CONFIG_FILE_PATH="/srv/gateway/litellm_config.yaml"
EXPOSE 8080
# The container's single entrypoint brings up TWO co-located ASGI processes
# (ADR D1): the litellm proxy on the internal port 4000 first, then the agent
# uvicorn on 8080, in that order (ADR D10). See
# `src/polymerhus/app/gateway_entrypoint.py`. The previous bare `uvicorn ...`
# CMD now lives inside that module as the agent invocation (`_agent_command`).
# `python -m` so the package import resolves via PYTHONPATH.
CMD ["python", "-m", "polymerhus.app.gateway_entrypoint"]
