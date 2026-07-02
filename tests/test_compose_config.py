import subprocess

def test_compose_config_is_valid():
    r = subprocess.run(["docker", "compose", "config"], capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "polymerhus-net" in r.stdout

def test_dev_overlay_config_is_valid():
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "config"],
        capture_output=True, text=True, cwd=".")
    assert r.returncode == 0, r.stderr
    assert "--reload" in r.stdout
