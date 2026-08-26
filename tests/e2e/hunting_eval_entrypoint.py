"""Container entrypoint for the hunt-orchestrator full-machine eval.

The eval container co-locates its OWN litellm gateway and then runs the eval
driver (pytest) once the proxy is healthy. ``LLM_GATEWAY_URL`` points at the
co-located proxy, so the real orchestrator actor resolves
``LLM_MODEL_HUNTING_ORCHESTRATOR`` through the same gateway path the
production agent uses.

The proxy is launched DIRECTLY (``litellm --config``), not through the image's
``gateway_entrypoint``: the eval reuses the SHARED ``polymerhus_gateway`` DB,
whose schema is already migrated and whose ``LiteLLM_ProxyModelTable`` already
holds the registered ``LLM_MODEL_*`` routing set - so the entrypoint's
migration step (``prisma migrate deploy``, a flaky 420s+ cold run) and the T2
sync are both redundant here. ``store_model_in_db: true`` loads the model set
from the DB at boot. This is a test-harness shortcut on the PROXY BOOT only;
the orchestrator turns themselves run the real client through the real
gateway surface.

Sequence:
  1. install the dev requirements (pytest) - the same step the ``tests``
     service runs, the image ships runtime deps only;
  2. spawn the litellm proxy ASGI on the internal port (127.0.0.1:4000);
  3. poll the proxy readiness surface ``/health/liveliness`` (bounded);
  4. exec the eval driver command;
  5. terminate the proxy child and propagate the driver's exit code.

Fail-closed on the gateway: a proxy that never becomes ready aborts the eval
with a clear diagnostic rather than letting the orchestrator actor fail
opaque LLM turns. No I/O at import; every collaboration runs inside ``main``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx

_LITELLM_CONFIG = "/srv/gateway/litellm_config.yaml"
_PROXY_PORT = "4000"
_DEV_REQUIREMENTS = "/srv/requirements-dev.txt"
_HEALTH_PATH = "/health/liveliness"
_HEALTH_MAX_ATTEMPTS = 600
_HEALTH_INTERVAL_S = 1.0
_HEALTH_TIMEOUT_S = 2.0


def _install_dev_requirements() -> None:
    """pytest and the dev deps (the image ships runtime requirements only)."""
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "--no-cache-dir", "-q", "-r", _DEV_REQUIREMENTS,
    ])


def _start_proxy() -> subprocess.Popen:
    """The co-located litellm proxy on the internal port (ADR D1 shape)."""
    return subprocess.Popen([
        "litellm", "--config", _LITELLM_CONFIG,
        "--host", "127.0.0.1", "--port", _PROXY_PORT,
    ])


def _gateway_url() -> str:
    raw = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:4000")
    return raw.rstrip("/")


def _gateway_ready(gateway: subprocess.Popen) -> bool:
    """True once the co-located proxy answers /health/liveliness 200."""
    url = _gateway_url() + _HEALTH_PATH
    for _ in range(_HEALTH_MAX_ATTEMPTS):
        if gateway.poll() is not None:
            raise RuntimeError(
                f"gateway child exited early (rc={gateway.returncode}); "
                "the eval cannot reach the orchestrator model"
            )
        try:
            response = httpx.get(url, timeout=_HEALTH_TIMEOUT_S)
            if response.status_code == 200:
                return True
        except Exception:  # noqa: BLE001 - the proxy is still booting
            pass
        time.sleep(_HEALTH_INTERVAL_S)
    return False


def main(argv: list[str]) -> int:
    _install_dev_requirements()
    proxy = _start_proxy()
    try:
        if not _gateway_ready(proxy):
            raise RuntimeError(
                f"gateway never became healthy at {_gateway_url()}{_HEALTH_PATH}"
            )
        if not argv:
            raise SystemExit("no eval driver command given")
        if os.path.basename(argv[0]) in ("python", "python3"):
            argv = [sys.executable, *argv[1:]]
        return subprocess.call(argv)
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=10)
        except Exception:  # noqa: BLE001 - teardown must never raise
            proxy.kill()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))