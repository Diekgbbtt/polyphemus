import subprocess

import yaml


def test_compose_config_is_valid():
    r = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "polymerhus-net" in r.stdout

def test_lightrag_profile_config_is_valid():
    r = subprocess.run(
        ["docker", "compose", "--profile", "lightrag", "config"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert r.returncode == 0, r.stderr
    assert "ghcr.io/hkuds/lightrag:v1.5.0rc3" in r.stdout
    assert "ENTITY_TYPE_PROMPT_FILE" in r.stdout
    assert "ENTITY_TYPES" not in r.stdout
    assert "LIGHTRAG_PARSER" in r.stdout
    assert "127.0.0.1" in r.stdout


def test_lightrag_profile_includes_isolated_writeup_overlay():
    r = subprocess.run(
        ["docker", "compose", "--profile", "lightrag", "config"],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert r.returncode == 0, r.stderr

    config = yaml.safe_load(r.stdout)
    base = config["services"]["lightrag"]
    overlay = config["services"]["lightrag-writeups"]

    assert overlay["environment"]["WORKSPACE"] == "writeups_0xdf"
    assert overlay["environment"]["WORKING_DIR"] != base["environment"]["WORKING_DIR"]
    assert overlay["environment"]["INPUT_DIR"] != base["environment"]["INPUT_DIR"]
    assert any(port["published"] == "9622" for port in overlay["ports"])


def test_dev_overlay_config_is_valid():
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "config"],
        capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "--reload" in r.stdout
