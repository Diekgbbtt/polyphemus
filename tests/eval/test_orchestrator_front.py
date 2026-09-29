"""The host-level nginx front for local targets (ticket #269, SP2).

Local `image`/`compose` targets publish on a host port, but the platform's
seed is a bare domain on the standard web port. One shared `ph-eval-front`
container binds host :80 and serves one conf per synthetic Host, proxying to
the target's published port over the Docker host gateway. These are pure
command assertions; the orchestrator lifecycle is covered in
`test_orchestrator_orchestrator.py`.
"""
from __future__ import annotations

import shlex

from orchestrator import front, routing


def test_container_up_is_idempotent_and_binds_port_80() -> None:
    command = front.plan_container_up()
    script = command.argv[-1]

    # A running/stopped container is started; the run only happens when absent.
    assert f"docker start {front.FRONT_CONTAINER}" in script
    assert "docker run -d --name ph-eval-front" in script
    assert f"--publish {front.FRONT_HOST_PORT}:{front.FRONT_CONTAINER_PORT}" in script
    # The in-container nginx must resolve the gateway in proxy_pass.
    assert f"--add-host {routing.HOST_GATEWAY}:host-gateway" in script


def test_container_down_is_idempotent() -> None:
    command = front.plan_container_down()
    script = command.argv[-1]

    assert f"docker rm -f {front.FRONT_CONTAINER}" in script
    assert "|| true" in script


def test_conf_apply_writes_server_name_and_gateway_backend() -> None:
    command = front.plan_conf_apply("t-aaaa.target", 18080)
    argv = " ".join(command.argv)

    assert command.argv[:4] == ("docker", "exec", "-i", front.FRONT_CONTAINER)
    assert "nginx -t" in argv and "nginx -s reload" in argv
    assert "server_name t-aaaa.target;" in (command.stdin or "")
    assert f"proxy_pass http://{routing.HOST_GATEWAY}:18080;" in (command.stdin or "")


def test_conf_remove_deletes_the_per_host_conf() -> None:
    command = front.plan_conf_remove("t-aaaa.target")
    argv = " ".join(command.argv)

    assert front.FRONT_CONTAINER in argv
    assert "eval-target-t-aaaa.target.conf" in argv
    assert "rm -f" in argv and "nginx -s reload" in argv


def test_each_synthetic_host_gets_its_own_conf_file() -> None:
    a = front.front_conf("t-aaaa.target")
    b = front.front_conf("t-bbbb.target")

    assert a != b
    assert a.name == "eval-target-t-aaaa.target.conf"
    assert str(a).startswith(front.FRONT_CONF_DIR + "/")


def test_conf_path_is_shell_quoted() -> None:
    """S5: interpolated conf paths are quoted in the remote shell string."""
    command = front.plan_conf_apply("t-a b.target", 18080)
    quoted = shlex.quote("/etc/nginx/conf.d/eval-target-t-a b.target.conf")

    assert quoted in " ".join(command.argv)
