FROM redamon-agent:latest
WORKDIR /srv
COPY src/ /srv/src/
COPY db/ /srv/db/
COPY skills/ /srv/skills/
COPY requirements-observability.txt requirements-crawl.txt /srv/
# Optional lightweight tracing dependency (Langfuse). Layered on top of the
# base image; the agent runs fine without it (tracing fail-open no-op), but
# baking it in lets operators enable tracing purely via LANGFUSE_* env vars.
RUN pip install --no-cache-dir -r /srv/requirements-observability.txt
# Agentic-crawl (Steel) client libs - the base image was assumed to provide
# these but does not, so steel_crawl degraded to empty manifests. Cloud browser
# over CDP, so no `playwright install` (local browsers) is needed.
RUN pip install --no-cache-dir -r /srv/requirements-crawl.txt
# src/ layout: the polymerhus package is under /srv/src, and the skills/ mount
# sits at /srv/skills - a sibling of src/, exactly as skills.py resolves it
# (Path(__file__).parents[4] / "skills").
ENV PYTHONPATH="/srv/src:/app"
EXPOSE 8080
CMD ["uvicorn", "polymerhus.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
