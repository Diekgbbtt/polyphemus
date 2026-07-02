FROM redamon-agent:latest
WORKDIR /srv
COPY agent/ /srv/agent/
COPY db/ /srv/db/
ENV PYTHONPATH="/srv:/app"
EXPOSE 8080
CMD ["uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
