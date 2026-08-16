import yaml


def test_no_compose_service_receives_the_url_webhook_secret():
    secret = "POLYPHEMUS_URL_INGESTION_WEBHOOK_SECRET"
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    for service_name, service in compose["services"].items():
        environment = service.get("environment") or {}
        if isinstance(environment, list):
            keys = {entry.split("=", 1)[0] for entry in environment}
        else:
            keys = set(environment.keys())
        assert secret not in keys, f"{service_name} injects {secret}"

    assert secret not in open("docker-compose.yml", encoding="utf-8").read()


def test_compose_defines_n8n_and_shared_ingestion_mount():
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    assert "n8n" in compose["services"]
    assert "ingestion" in compose["services"]
    n8n = compose["services"]["n8n"]
    ingestion = compose["services"]["ingestion"]
    assert "127.0.0.1:${N8N_PORT:-5678}:5678" in n8n["ports"]
    assert "./data/ingestion:/data/ingestion" in n8n["volumes"]
    assert "./workflows/n8n:/workflows/n8n:ro" in n8n["volumes"]
    assert "./data/ingestion:/data/ingestion" in ingestion["volumes"]
    assert ingestion["environment"]["INGESTION_ROOT"] == "/data/ingestion"
    assert ingestion["environment"]["INGESTION_NORMALIZED_DIR"] == "/data/ingestion/normalized"
    assert ingestion["build"]["dockerfile"] == "agent/Dockerfile.ingestion"


def test_agent_dockerfile_installs_docprep_package():
    dockerfile = open("agent/Dockerfile.ingestion", encoding="utf-8").read()

    assert "COPY data/lightrag/preprocessing_pipeline/ /srv/lightrag_docprep/" in dockerfile
    assert "pip install --no-cache-dir /srv/lightrag_docprep" in dockerfile
    assert "FROM python:3.12-slim" in dockerfile


def test_lightrag_compose_matches_existing_embedding_dimension():
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    env = compose["services"]["lightrag"]["environment"]
    assert env["EMBEDDING_DIM"] == "${EMBEDDING_DIM:-2048}"
    assert env["EMBEDDING_BINDING"] == "${EMBEDDING_BINDING:-ollama}"
    assert env["EMBEDDING_MODEL"] == "${EMBEDDING_MODEL:-}"
    assert env["EMBEDDING_USE_BASE64"] == "${EMBEDDING_USE_BASE64:-false}"
    assert env["LLM_BINDING"] == "${LLM_BINDING:-ollama}"
    assert env["LLM_MODEL"] == "${LLM_MODEL:-mistral-nemo:latest}"


def test_ingestion_pipeline_uses_single_lightrag_service():
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    assert "lightrag" in compose["services"]
    assert "lightrag-writeups" not in compose["services"]

    ingestion_env = compose["services"]["ingestion"]["environment"]
    assert ingestion_env["LIGHTRAG_API_URL"] == "http://lightrag:9621"
    assert ingestion_env["LIGHTRAG_BASE_API_URL"] == "http://lightrag:9621"
    assert "LIGHTRAG_WRITEUP_API_URL" not in ingestion_env


def test_ingestion_compose_propagates_wait_budget_defaults():
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    env = compose["services"]["ingestion"]["environment"]
    assert env.get("LIGHTRAG_INGESTION_TIMEOUT_SECONDS") == "${LIGHTRAG_INGESTION_TIMEOUT_SECONDS:-1800}"
    assert env.get("LIGHTRAG_POLL_INTERVAL_SECONDS") == "${LIGHTRAG_POLL_INTERVAL_SECONDS:-2}"
