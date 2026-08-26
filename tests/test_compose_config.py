import subprocess

import yaml


def test_compose_config_is_valid():
    r = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "polymerhus-net" in r.stdout


def test_lightrag_is_baseline_config():
    r = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr

    config = yaml.safe_load(r.stdout)
    lightrag = config["services"]["lightrag"]

    assert lightrag["image"] == "ghcr.io/hkuds/lightrag:v1.5.0rc3"
    assert lightrag["environment"]["ENTITY_TYPE_PROMPT_FILE"] == "methodology_entities.yml"
    assert "ENTITY_TYPES" not in lightrag["environment"]
    assert "LIGHTRAG_PARSER" in lightrag["environment"]
    assert "lightrag-writeups" not in config["services"]
    assert "ingestion" not in config["services"]
    assert "n8n" not in config["services"]


def test_ingestion_overlay_config_is_valid():
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.ingestion.yml", "config"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert r.returncode == 0, r.stderr

    config = yaml.safe_load(r.stdout)
    assert "ingestion" in config["services"]
    assert "n8n" in config["services"]
    assert config["services"]["ingestion"]["build"]["dockerfile"] == "src/polymerhus/Dockerfile.ingestion"
    assert "lightrag-writeups" not in config["services"]


def test_dev_overlay_config_is_valid():
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "config"],
        capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "--reload" in r.stdout
