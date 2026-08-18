# Base: python:3.11-slim - the agent is a python runtime container that layers
# pip installs on top (app/observability/crawl/gateway). The legacy redamon-agent
# base was built from exactly `python:3.11-slim` (redamon/agentic/Dockerfile)
# and no longer exists in the docker daemon, so we FROM the upstream image
# directly and recreate the app runtime it used to bake in via
# `requirements-app.txt`. prisma generate below assumes python 3.11 at
# /usr/local (the pip site-packages path), which this base provides.
FROM python:3.11-slim
# Build/runtime system deps the pip wheels below may need (gcc/g++ for source
# builds when no prebuilt manylinux wheel exists; git for any pip VCS install).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY src/ /srv/src/
COPY db/ /srv/db/
COPY skills/ /srv/skills/
COPY gateway/ /srv/gateway/
COPY requirements-app.txt requirements-observability.txt requirements-crawl.txt requirements-gateway.txt /srv/
# The FULL app runtime (previously baked into the removed `redamon-agent` base):
# the langchain family, langgraph + its postgres checkpointer, the data-store
# clients (psycopg/neo4j), the agent ASGI surface (fastapi/httpx), pydantic and
# pyyaml. `requirements-app.txt` is the canonical manifest; a bump is a one-file
# review there, never a base-image rebuild (ADR D10 discipline).
RUN pip install --no-cache-dir -r /srv/requirements-app.txt
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
# Generate the Prisma client Python code from litellm's own schema.prisma. The
# `prisma` pip package ships NO generated client - without this step the proxy
# crashes at boot with "The Client hasn't been generated yet, you must run
# `prisma generate`" as soon as DATABASE_URL is set (ADR D1: the shared
# postgres) (verified live 2026-08-17). `prisma generate` downloads the query
# engine binaries at build time, so runtime containers need no network for it.
# Schema path is the one baked in by the pip install above (litellm 1.96.0).
RUN prisma generate --schema=/usr/local/lib/python3.11/site-packages/litellm/proxy/schema.prisma
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
