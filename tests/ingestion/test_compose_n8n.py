import yaml


def test_compose_defines_n8n_and_shared_ingestion_mount():
    compose = yaml.safe_load(open("docker-compose.yml", encoding="utf-8"))

    assert "n8n" in compose["services"]
    n8n = compose["services"]["n8n"]
    agent = compose["services"]["agent"]
    assert "127.0.0.1:${N8N_PORT:-5678}:5678" in n8n["ports"]
    assert "./data/ingestion:/data/ingestion" in n8n["volumes"]
    assert "./data/ingestion:/data/ingestion" in agent["volumes"]
    assert agent["environment"]["INGESTION_ROOT"] == "/data/ingestion"
    assert agent["environment"]["INGESTION_NORMALIZED_DIR"] == "/data/ingestion/normalized"


def test_agent_dockerfile_installs_docprep_package():
    dockerfile = open("agent/Dockerfile", encoding="utf-8").read()

    assert "COPY data/lightrag/preprocessing_pipeline/ /srv/lightrag_docprep/" in dockerfile
    assert "pip install --no-cache-dir /srv/lightrag_docprep" in dockerfile
