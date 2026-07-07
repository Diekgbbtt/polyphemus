FROM redamon-agent:latest
WORKDIR /srv
COPY agent/ /srv/agent/
COPY db/ /srv/db/
# Optional lightweight tracing dependency (Langfuse). Layered on top of the
# base image; the agent runs fine without it (tracing fail-open no-op), but
# baking it in lets operators enable tracing purely via LANGFUSE_* env vars.
RUN pip install --no-cache-dir -r /srv/agent/requirements-observability.txt
ENV PYTHONPATH="/srv:/app"
EXPOSE 8080
CMD ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
