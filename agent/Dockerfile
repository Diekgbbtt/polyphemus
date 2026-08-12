FROM redamon-agent:latest
WORKDIR /srv
COPY agent/ /srv/agent/
COPY db/ /srv/db/
COPY skills/ /srv/skills/
COPY data/lightrag/preprocessing_pipeline/ /srv/lightrag_docprep/
# Optional lightweight tracing dependency (Langfuse). Layered on top of the
# base image; the agent runs fine without it (tracing fail-open no-op), but
# baking it in lets operators enable tracing purely via LANGFUSE_* env vars.
RUN pip install --no-cache-dir -r /srv/agent/requirements-observability.txt
# Agentic-crawl (Steel) client libs - the base image was assumed to provide
# these but does not, so steel_crawl degraded to empty manifests. Cloud browser
# over CDP, so no `playwright install` (local browsers) is needed.
RUN pip install --no-cache-dir -r /srv/agent/requirements-crawl.txt
RUN pip install --no-cache-dir /srv/lightrag_docprep
ENV PYTHONPATH="/srv:/app"
EXPOSE 8080
CMD ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
