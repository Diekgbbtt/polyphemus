"""Trust ONE operator-provided CA so the recording proxy can verify its upstream.

Measured live 2026-09-17 against the lab target `soupmarket.shop` (self-signed
leaf): mitmdump verifies the upstream certificate, so the intercepted request
never completes - the client gets a 502 and the artifact records
`Certificate verify failed: self-signed certificate` with `tls=false`. The
traffic is *visible* as a failure but not inspectable, and the replay is
impossible.

The targeted treatment is to trust THAT CA. Installing a specific certificate is
strictly narrower than `ssl_insecure`, which would make the proxy accept any
upstream certificate: the recording plane is the one place where silently
trusting the wrong peer would falsify every artifact it produces.

Best-effort by contract: a missing file or a broken trust-store refresh is
reported, never raised - the exec server must come up regardless.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

#: Debian's drop-in directory: `update-ca-certificates` folds these into the
#: system bundle AND the hashed capath, which is what Go tools read.
DEFAULT_DEST_DIR = "/usr/local/share/ca-certificates"
DEFAULT_NAME = "polymerhus-upstream-ca.crt"


def install_upstream_ca(
    source: str,
    *,
    dest_dir: str = DEFAULT_DEST_DIR,
    name: str = DEFAULT_NAME,
    update=None,
) -> dict:
    """Install ``source`` as a trusted CA and refresh the store.

    Returns a small result dict rather than raising: the caller is the container
    bootstrap, where a trust failure must leave the exec server running.
    """
    if not source:
        return {
            "installed": False,
            "dest": None,
            "reason": "KALI_HTTP_UPSTREAM_CA is not set",
        }
    if not os.path.isfile(source):
        return {
            "installed": False,
            "dest": None,
            "reason": f"not a readable file: {source}",
        }
    dest = os.path.join(dest_dir, name)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copyfile(source, dest)
    except OSError as exc:
        return {"installed": False, "dest": dest, "reason": f"install failed: {exc}"}

    runner = update or _refresh_with_openssl
    try:
        updated, detail = runner()
    except Exception as exc:  # noqa: BLE001 - bootstrap is best-effort
        updated, detail = False, f"{type(exc).__name__}: {exc}"
    if not updated:
        logger.warning("upstream CA installed but the trust store refresh failed: %s", detail)
    return {"installed": True, "dest": dest, "updated": bool(updated), "detail": detail}


def _refresh_with_openssl() -> tuple[bool, str]:
    proc = subprocess.run(
        ["update-ca-certificates"], capture_output=True, text=True, timeout=120, check=False
    )
    detail = (proc.stdout or proc.stderr or "").strip().splitlines()
    return proc.returncode == 0, (detail[-1] if detail else "")


#: Deterministic name the entrypoint looks for when it starts the proxy.
UPSTREAM_BUNDLE_NAME = "upstream-ca-bundle.pem"


def _default_trust_source() -> str | None:
    """What mitmproxy verifies against when nothing is configured: certifi."""
    try:
        import certifi  # noqa: PLC0415 - optional, resolved at call time

        return certifi.where()
    except Exception:  # noqa: BLE001 - fall back to the distro bundle
        pass
    for candidate in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if os.path.isfile(candidate):
            return candidate
    return None


def build_upstream_bundle(
    source: str,
    *,
    dest_dir: str,
    base: str | None = None,
    name: str = UPSTREAM_BUNDLE_NAME,
) -> dict:
    """A CA bundle for mitmproxy's UPSTREAM verification: default store + source.

    Necessary because mitmproxy does NOT verify against the system trust store -
    it uses its own CA source (certifi) - so installing the operator CA the
    Debian way was not enough to record a self-signed lab target: the proxy still
    answered `Certificate verify failed: self-signed certificate` (measured live
    2026-09-17). The bundle keeps the normal CAs (or every public target would
    break) and appends the operator's, once.
    """
    if not source or not os.path.isfile(source):
        return {"bundle": None, "added": False, "reason": f"no readable CA at {source!r}"}
    trust_source = base or _default_trust_source()
    base_text = ""
    if trust_source and os.path.isfile(trust_source):
        with open(trust_source, encoding="utf-8", errors="replace") as handle:
            base_text = handle.read()
    with open(source, encoding="utf-8", errors="replace") as handle:
        ca_text = handle.read()
    if ca_text.strip() and ca_text.strip() in base_text:
        body, added = base_text, False
    else:
        body, added = f"{base_text.rstrip()}\n{ca_text.lstrip()}", True
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(body)
    return {"bundle": dest, "added": added, "base": trust_source}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    source = args[0] if args else os.environ.get("KALI_HTTP_UPSTREAM_CA", "")
    dest_dir = os.environ.get("KALI_HTTP_MITM_CONFDIR", "/data/mitmproxy")
    result = {
        "system_store": install_upstream_ca(source),
        "mitm_bundle": build_upstream_bundle(source, dest_dir=dest_dir),
    }
    print(json.dumps(result), flush=True)
    return 0  # bootstrap never fails the container over a trust store


if __name__ == "__main__":
    raise SystemExit(main())
