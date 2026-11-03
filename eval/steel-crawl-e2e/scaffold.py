#!/usr/bin/env python3
"""Host-side orchestration for the steel-crawl live e2e.

The scaffold runs on the eval server host. It owns the environment the engine
does not: the target stack, the shared front alias, the pre-authenticated Steel
session, the AuthContext placement, and the project/run API calls. The crawl
itself runs inside the deployed agent container through `phase_runner.py`, so
the real pipeline, auth gateway, crawl pod, engine, ledger, edge, and curator
execute at runtime.

Only the target stack and the Steel session are test setup; nothing inside the
crawl is mocked. Secrets are read from the operator data and are never printed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

EVAL_ROOT = Path("/root/WebExploitBench")
DATA_DEPS = Path("/root/eval-dd/data")
INSTANCE_ENV = Path("/opt/polymerhus-dev/eval/instances/eval-server-1/.env")
AGENT_CONTAINER = "ph-dd131acc-agent-1"
KALI_CONTAINER = "ph-dd131acc-kali-1"
FRONT_CONTAINER = "ph-eval-front"
FRONT_HOST = "t-1618c524.target"
API_BASE = "http://127.0.0.1:8080"
AGENT_CODE = "/opt/steel-crawl-e2e"
AGENT_CLI = "/opt/localbin/steel"
STEEL_API = "http://192.33.91.87:3000"


@dataclass(frozen=True)
class TargetSpec:
    """One target the e2e can run."""

    name: str
    entry: str
    auth: str
    probe: str | None
    account: str | None = None
    expected_title: str = ""
    notes: str = ""
    ready_path: str = "/"


TARGETS: dict[str, TargetSpec] = {
    "comfyui": TargetSpec(
        name="comfyui",
        entry="/",
        auth="none",
        probe=None,
        expected_title="ComfyUI",
        notes="No authentication surface; the legacy surface gate is the oracle path.",
    ),
    "prestashop": TargetSpec(
        name="prestashop",
        entry="/admin-dev/index.php?controller=AdminDashboard",
        auth="prestashop_cookie",
        probe="/admin-dev/index.php?controller=AdminDashboard",
        account="psprobe1-first_authn_bootstrap",
        notes=(
            "Back-office cookie is address-bound; the session is minted with the "
            "application's own classes. The modern admin controllers need a "
            "one-time Symfony container compile with a writable cache."
        ),
        ready_path="/admin-dev/index.php",
    ),
    "siyucms": TargetSpec(
        name="siyucms",
        entry="/index.php/admin/Index/index.html",
        auth="siyucms_form",
        probe="/index.php/admin/Index/index.html",
        account="admin-first_authn_bootstrap",
        expected_title="SIYUCMS | 控制台",
        notes="Admin form login; the browser keeps the rotated PHPSESSID.",
    ),
}


class E2EError(RuntimeError):
    """The scaffold could not bring one prerequisite to its ready state."""


@dataclass
class RunEvidence:
    """Everything one walkthrough reads back."""

    target: str
    project_id: str
    run_id: str
    session_name: str
    target_url: str
    phase: dict[str, Any]
    manifest: dict[str, Any]
    summary: dict[str, Any]
    ledger_entries: list[dict[str, Any]]
    recon: dict[str, Any]
    graph: dict[str, Any]
    auth: dict[str, Any]
    session_catalogue: list[dict[str, Any]]
    session_catalogue_before: list[dict[str, Any]] = field(default_factory=list)
    session_catalogue_after: list[dict[str, Any]] = field(default_factory=list)
    secrets: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


def _run(
    command: list[str],
    *,
    timeout: int = 300,
    cwd: Path | str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if check and completed.returncode != 0:
        raise E2EError(
            f"{' '.join(command[:4])} failed ({completed.returncode}): "
            f"{completed.stderr.strip()[-500:]}"
        )
    return completed


def _env_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _steel_api_headers() -> dict[str, str]:
    key = _env_value(INSTANCE_ENV, "STEEL_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _json_line(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise E2EError("the command returned no JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise E2EError("the command returned no JSON object")


class SteelCli:
    """The Steel CLI in the agent container; the one action surface.

    The CLI's session catalogue is daemon-scoped, so the session must be
    minted by the same daemon the crawl uses. The agent container is that
    daemon; the host only drives it over `docker exec`.
    """

    def __init__(self, container: str = AGENT_CONTAINER) -> None:
        self._container = container

    def run(
        self,
        verb: str,
        *args: str,
        session: str | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        command = [
            "docker",
            "exec",
            "-e",
            "STEEL_REAL_BINARY=/opt/localbin/steel-real",
            self._container,
            AGENT_CLI,
            "browser",
            verb,
            *args,
        ]
        if session:
            command.extend(["--session", session])
        command.append("--json")
        completed = _run(command, timeout=timeout, check=False)
        payload = _json_line(completed.stdout or completed.stderr)
        if not payload.get("success", False):
            raise E2EError(
                f"steel {verb} failed: "
                f"{payload.get('error') or payload.get('message')}"
            )
        return payload

    def start(self, session: str) -> dict[str, Any]:
        return self.run(
            "start",
            "--inactivity-timeout",
            "900000",
            session=session,
        )

    def stop(self, session: str) -> None:
        try:
            self.run("stop", session=session)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            pass

    def navigate(
        self, session: str, url: str, *, timeout: int = 180
    ) -> dict[str, Any]:
        last: E2EError | None = None
        for attempt in range(3):
            try:
                return self.run(
                    "navigate",
                    url,
                    "--wait-until",
                    "domcontentloaded",
                    session=session,
                    timeout=timeout,
                )
            except E2EError as exc:
                last = exc
                if "ERR_NAME_NOT_RESOLVED" not in str(exc) or attempt >= 2:
                    raise
                time.sleep(2)
        raise last or E2EError("navigation failed")

    def eval(self, session: str, script: str) -> Any:
        return self.run("eval", script, session=session).get("data")

    def cookies(self, session: str) -> list[dict[str, Any]]:
        data = self.run("cookies", session=session).get("data")
        if isinstance(data, dict):
            data = data.get("cookies")
        return [item for item in (data or []) if isinstance(item, dict)]

    def set_cookie(self, session: str, name: str, value: str) -> None:
        self.run(
            "cookies",
            "set",
            name,
            value,
            "--path",
            "/",
            session=session,
        )

    def catalogue(self) -> list[dict[str, Any]]:
        data = self.run("sessions").get("data")
        return [item for item in (data or []) if isinstance(item, dict)]

    def session_id(self, name: str) -> str:
        for item in self.catalogue():
            if item.get("name") == name:
                return str(item.get("id") or "")
        raise E2EError(f"the Steel session {name!r} is not live")

    def context(self, session_id: str) -> dict[str, Any]:
        response = httpx.get(
            f"{STEEL_API}/v1/sessions/{session_id}/context",
            headers=_steel_api_headers(),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise E2EError("the Steel session context is not an object")
        return data


class TargetStack:
    """One targetctl stack and the shared front alias it rides."""

    def __init__(self, spec: TargetSpec) -> None:
        self.spec = spec
        self.port: int | None = None
        self.started = False
        self._front_backup: str | None = None

    @property
    def container_prefix(self) -> str:
        return f"web_{self.spec.name}"

    def up(self) -> int:
        self._reset_stale_containers()
        before = _run(
            ["./scripts/targetctl", "ps", self.spec.name],
            cwd=EVAL_ROOT,
            check=False,
            timeout=120,
        ).stdout
        was_running = self.container_prefix in before
        completed = _run(
            ["./scripts/targetctl", "up", self.spec.name],
            cwd=EVAL_ROOT,
            timeout=600,
            check=False,
        )
        match = re.search(r"http://0\.0\.0\.0:(\d+)", completed.stdout)
        if match is None:
            raise E2EError(
                f"targetctl did not print the {self.spec.name} port: "
                f"{completed.stderr[-500:] or completed.stdout[-500:]}"
            )
        self.port = int(match.group(1))
        self.started = not was_running
        self._wait_ready()
        self._write_front()
        return self.port

    def _configure_prestashop_shop_url(self) -> None:
        """Point the target's shop URL at the front alias it is actually served on.

        PrestaShop generates absolute redirects from `PS_SHOP_DOMAIN` and
        `ps_shop_url.domain`. The seeded deployment names the shop
        `prestashop` (its compose service), which the Steel browser cannot
        resolve. The front alias is the deployment address the crawl uses, so
        the target's own configuration is updated to it before the session
        starts.
        """
        script = """<?php
define('_PS_ADMIN_DIR_', '/var/www/html/admin-dev');
$_SERVER['HTTP_HOST'] = getenv('PS_HOST');
$_SERVER['SERVER_NAME'] = $_SERVER['HTTP_HOST'];
require '/var/www/html/config/config.inc.php';
$host = getenv('PS_HOST');
Configuration::updateValue('PS_SHOP_DOMAIN', $host);
Configuration::updateValue('PS_SHOP_DOMAIN_SSL', $host);
Db::getInstance()->execute(
    'UPDATE `' . _DB_PREFIX_ . 'shop_url` SET '
    . '`domain` = "' . pSQL($host) . '", '
    . '`domain_ssl` = "' . pSQL($host) . '" WHERE `main` = 1'
);
echo "shop-url-updated\\n";
"""
        container = self.web_container()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = _run(
                [
                    "docker",
                    "inspect",
                    container,
                    "--format",
                    "{{.State.Status}}",
                ],
                timeout=30,
                check=False,
            ).stdout.strip()
            if status == "running":
                break
            time.sleep(2)
        local = Path(tempfile.gettempdir()) / "steel-crawl-prestashop-shop-url.php"
        local.write_text(script, encoding="utf-8")
        try:
            _run(
                [
                    "docker",
                    "cp",
                    str(local),
                    f"{container}:/tmp/configure-shop-url.php",
                ],
                timeout=30,
            )
            completed = None
            for attempt in range(6):
                completed = _run(
                    [
                        "docker",
                        "exec",
                        "-u",
                        "www-data",
                        "-e",
                        f"PS_HOST={FRONT_HOST}",
                        container,
                        "php",
                        "/tmp/configure-shop-url.php",
                    ],
                    timeout=120,
                    check=False,
                )
                if completed.returncode == 0:
                    break
                if (
                    "is restarting" in completed.stderr
                    or "is not running" in completed.stderr
                ) and attempt < 5:
                    time.sleep(5)
                    continue
                break
            if completed is None or completed.returncode != 0:
                raise E2EError(
                    "the PrestaShop shop URL could not be configured: "
                    f"{(completed.stderr if completed else '')[-500:]}"
                )
        finally:
            local.unlink(missing_ok=True)

    def _reset_stale_containers(self) -> None:
        """Remove the target's stale containers and old networks.

        The dataset's compose names its project `pb_<target>`; `targetctl`
        recreates it as `web_<target>`. A previous deployment can leave the
        old `pb_<target>_default` network and a sibling holding it, which makes
        a fresh `up` fail before the app starts. The target stack is setup, so
        the scaffold resets it deterministically.
        """
        names = _run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"name={self.container_prefix}",
                "--format",
                "{{.Names}}",
            ],
            timeout=30,
            check=False,
        ).stdout.splitlines()
        for name in names:
            if name:
                _run(["docker", "rm", "-f", name], timeout=60, check=False)
        for prefix in (f"pb_{self.spec.name}_default", f"web_{self.spec.name}_default"):
            ids = _run(
                [
                    "docker",
                    "network",
                    "ls",
                    "--filter",
                    f"name={prefix}",
                    "--format",
                    "{{.ID}}",
                ],
                timeout=30,
                check=False,
            ).stdout.splitlines()
            for network_id in ids:
                if network_id:
                    _run(
                        ["docker", "network", "rm", network_id],
                        timeout=30,
                        check=False,
                    )

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + 180
        last = ""
        while time.monotonic() < deadline:
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{self.port}{self.spec.ready_path}",
                    follow_redirects=False,
                    timeout=5,
                )
                if response.status_code < 500:
                    return
                last = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 - readiness is a poll
                last = str(exc)
            time.sleep(2)
        raise E2EError(
            f"the {self.spec.name} stack did not answer within 180s: {last}"
        )

    def _front_conf(self) -> str:
        if self.spec.name == "prestashop":
            # The target generates absolute `http://prestashop/...` URLs from
            # its seeded shop domain and resolves that name server-side. Keep
            # the target's own Host for its internal identity, and rewrite the
            # redirects/HTML to the front alias the browser can resolve.
            proxy = (
                f"        proxy_pass http://host.docker.internal:{self.port};\n"
                "        proxy_set_header Host prestashop;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
                '        proxy_set_header Accept-Encoding "";\n'
                f"        proxy_redirect http://prestashop/ http://{FRONT_HOST}/;\n"
                f"        proxy_redirect https://prestashop/ https://{FRONT_HOST}/;\n"
                f"        sub_filter 'http://prestashop' 'http://{FRONT_HOST}';\n"
                f"        sub_filter 'https://prestashop' 'https://{FRONT_HOST}';\n"
                "        sub_filter_once off;\n"
            )
        else:
            proxy = (
                f"        proxy_pass http://host.docker.internal:{self.port};\n"
                "        proxy_set_header Host $host;\n"
                "        proxy_set_header X-Real-IP $remote_addr;\n"
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                "        proxy_set_header X-Forwarded-Proto $scheme;\n"
            )
        return (
            "server {\n"
            f"    server_name {FRONT_HOST};\n"
            "    listen 80;\n"
            "    location = /_ip {\n"
            "        default_type text/plain;\n"
            '        return 200 "$remote_addr";\n'
            "    }\n"
            "    location / {\n"
            f"{proxy}"
            "    }\n"
            "}\n"
        )

    def _write_front(self) -> None:
        target = f"/etc/nginx/conf.d/eval-target-{FRONT_HOST}.conf"
        if self._front_backup is None:
            completed = _run(
                ["docker", "exec", FRONT_CONTAINER, "cat", target],
                check=False,
                timeout=30,
            )
            self._front_backup = completed.stdout
        with tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(self._front_conf())
            source = handle.name
        try:
            _run(
                ["docker", "cp", source, f"{FRONT_CONTAINER}:{target}"],
                timeout=30,
            )
            _run(
                ["docker", "exec", FRONT_CONTAINER, "nginx", "-s", "reload"],
                timeout=30,
            )
        finally:
            Path(source).unlink(missing_ok=True)

    def restore_front(self) -> None:
        if self._front_backup is None:
            return
        target = f"/etc/nginx/conf.d/eval-target-{FRONT_HOST}.conf"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(self._front_backup)
            source = handle.name
        try:
            _run(
                ["docker", "cp", source, f"{FRONT_CONTAINER}:{target}"],
                timeout=30,
            )
            _run(
                ["docker", "exec", FRONT_CONTAINER, "nginx", "-s", "reload"],
                timeout=30,
            )
        finally:
            Path(source).unlink(missing_ok=True)

    def down(self) -> None:
        if not self.started:
            return
        _run(
            ["./scripts/targetctl", "down", self.spec.name],
            cwd=EVAL_ROOT,
            check=False,
            timeout=300,
        )

    def web_container(self) -> str:
        completed = _run(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={self.port}",
                "--format",
                "{{.Names}}",
            ],
            timeout=30,
        )
        for name in completed.stdout.splitlines():
            if name.startswith(self.container_prefix):
                return name
        raise E2EError(
            f"no {self.spec.name} web container publishes port {self.port}"
        )

    def network_gateway(self) -> str:
        container = self.web_container()
        completed = _run(
            [
                "docker",
                "inspect",
                container,
                "--format",
                "{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}",
            ],
            timeout=30,
        )
        for value in completed.stdout.split():
            if value:
                return value
        return "172.17.0.1"


class ProjectApi:
    """The app API the scaffold uses to create and inspect the project."""

    def __init__(self, base: str = API_BASE) -> None:
        self._client = httpx.Client(base_url=base, timeout=60)

    def close(self) -> None:
        self._client.close()

    def create(self, name: str) -> str:
        response = self._client.post("/projects", json={"name": name})
        response.raise_for_status()
        return str(response.json()["project_id"])

    def settings(self, project_id: str, target_host: str) -> None:
        response = self._client.put(
            f"/projects/{project_id}/settings",
            json={
                "recon": {
                    "target_seed": target_host,
                    "streaming_analysis": False,
                }
            },
        )
        response.raise_for_status()

    def place_bytes(
        self, project_id: str, artifact: str, filename: str, data: bytes
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/projects/{project_id}/data-dependencies/{artifact}",
            files={"file": (filename, data, "application/octet-stream")},
        )
        response.raise_for_status()
        return response.json()

    def write_auth_file(
        self, project_id: str, filename: str, data: bytes
    ) -> None:
        """Write one auth file directly to the project's mounted data root.

        The deployed API validates the overview with its older record schema;
        the runtime auth feed reads the same file from the mount. This keeps
        the oracle field in the source the crawl actually consumes, without
        forking the store.
        """
        destination = f"/srv/data/{project_id}/auth"
        _run(
            ["docker", "exec", AGENT_CONTAINER, "mkdir", "-p", destination],
            timeout=30,
        )
        local = Path(tempfile.gettempdir()) / f"steel-crawl-{project_id}-{filename}"
        local.write_bytes(data)
        try:
            _run(
                [
                    "docker",
                    "cp",
                    str(local),
                    f"{AGENT_CONTAINER}:{destination}/{filename}",
                ],
                timeout=30,
            )
            _run(
                [
                    "docker",
                    "exec",
                    AGENT_CONTAINER,
                    "chmod",
                    "600",
                    f"{destination}/{filename}",
                ],
                timeout=30,
            )
        finally:
            local.unlink(missing_ok=True)

    def place_skill(
        self, project_id: str, archive: bytes
    ) -> dict[str, Any]:
        return self.place_bytes(
            project_id, "authn-skill", "authn.tar.gz", archive
        )

    def recon(self, project_id: str, run_id: str) -> dict[str, Any]:
        response = self._client.get(f"/projects/{project_id}/recon/{run_id}")
        response.raise_for_status()
        return response.json()

    def graph(self, project_id: str) -> dict[str, Any]:
        response = self._client.get(f"/projects/{project_id}/graph")
        response.raise_for_status()
        return response.json()

    def auth(self, project_id: str) -> dict[str, Any]:
        response = self._client.get(f"/projects/{project_id}/auth")
        response.raise_for_status()
        return response.json()


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _credentials(target: TargetSpec) -> tuple[dict[str, Any], str, dict[str, Any]]:
    path = DATA_DEPS / target.name / "auth" / "credentials.yaml"
    document = _load_yaml(path)
    accounts = document.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        raise E2EError(f"{path} carries no accounts")
    name = target.account or next(iter(accounts))
    account = accounts.get(name)
    if not isinstance(account, dict):
        raise E2EError(f"{path} has no account {name!r}")
    return document, name, account


def _overview(target: TargetSpec) -> dict[str, Any]:
    path = DATA_DEPS / target.name / "auth" / "overview.yaml"
    document = _load_yaml(path)
    if target.probe:
        document["auth_probe"] = {"url": target.probe}
    else:
        document.pop("auth_probe", None)
    return document


def _skill_overlay(target: TargetSpec, session: str) -> str:
    if target.auth == "none":
        return (
            "# Live-session overlay (e2e)\n\n"
            f"The operator-owned Steel session `{session}` is open for this run.\n"
            "This target has no sign-in, sign-up, or authenticated area: the "
            "overview records `mechanism: none` and every endpoint answers an "
            "anonymous plain HTTP client.\n"
            "Reuse the live session; never start a replacement.\n"
            "The crawl's precondition uses the legacy surface gate, because "
            "there is no `overview.auth_probe.url` to answer for a no-auth "
            "target.\n"
            "Do not call `/api/manager/reboot` or any other lifecycle route.\n"
        )
    return (
        "# Live-session overlay (e2e)\n\n"
        f"The operator-owned Steel session `{session}` is already authenticated "
        "for this run.\n"
        "Reuse it; never start a replacement.\n"
        f"The authenticated-context oracle is `{target.probe}`.\n"
        "It answers 2xx with `redirected: false` only for an authenticated "
        "context; 401, 403, any 3xx, or a followed redirect fails.\n"
        "Confirm the session is live, run the browser oracle, write the "
        "account status, and stop.\n"
        "The bootstrap procedures below are the operator's record; do not "
        "replay them during the crawl.\n\n"
    )


def _write_skill(
    target: TargetSpec, session: str, skill_root: Path
) -> Path:
    skill_dir = DATA_DEPS / target.name / "skills" / "authn"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    overlay = _skill_overlay(target, session)
    if existing.startswith("---\n"):
        end = existing.find("\n---\n", 4)
        if end >= 0:
            head = existing[: end + 5]
            body = existing[end + 5 :]
            text = head + "\n" + overlay + body
        else:
            text = overlay + existing
    else:
        text = (
            "---\n"
            "name: authn\n"
            f"description: >-\n  {target.name} project authentication and the "
            "pre-authenticated live Steel session for the crawl e2e.\n"
            "metadata:\n  version: '1.0-e2e'\n"
            "---\n\n"
            + overlay
            + (existing or "")
        )
    path.write_text(text, encoding="utf-8")
    archive = skill_root / f"{target.name}-authn.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(path, arcname="SKILL.md")
        references = skill_dir / "references"
        if references.is_dir():
            for item in sorted(references.iterdir()):
                if item.is_file():
                    bundle.add(item, arcname=f"references/{item.name}")
    return archive


def _update_account(
    target: TargetSpec,
    account_name: str,
    account: dict[str, Any],
    context: dict[str, Any],
    state_key: str,
) -> dict[str, Any]:
    cookies = [
        {"name": str(item["name"]), "value": str(item["value"])}
        for item in (context.get("cookies") or [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("value"), str)
    ]
    account = dict(account)
    account["origin"] = account.get("origin", "operator")
    account["status"] = "valid"
    account.pop("updated_at", None)
    account["steel"] = {"state": state_key}
    snapshot = dict(account.get("snapshot") or {})
    snapshot["cookies"] = cookies
    snapshot["headers"] = {}
    snapshot["captured_at"] = snapshot.get("captured_at") or ""
    snapshot["captured_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    account["snapshot"] = snapshot
    token_name = (
        "PHPSESSID"
        if target.auth == "siyucms_form"
        else next(
            (
                item["name"]
                for item in cookies
                if item["name"].startswith("PrestaShop-")
            ),
            "",
        )
    )
    if token_name:
        token = dict((account.get("tokens") or {}).get(token_name) or {})
        token.update(
            {
                "value": next(
                    (
                        item["value"]
                        for item in cookies
                        if item["name"] == token_name
                    ),
                    token.get("value", ""),
                ),
                "location": "cookie",
                "target": "/",
            }
        )
        tokens = dict(account.get("tokens") or {})
        tokens[token_name] = token
        account["tokens"] = tokens
    notes = str(account.get("notes") or "").strip()
    account["notes"] = (
        notes
        + "\nE2E live-session overlay: the account holds the session captured "
        "from the pre-authenticated Steel session for this run. The crawl "
        "attaches to that session and never replays the sign-in."
    ).strip()
    return account


def _state_file(
    target: TargetSpec,
    project_id: str,
    state_key: str,
    context: dict[str, Any],
    scratch: Path,
) -> None:
    projected = {
        key: context[key]
        for key in ("cookies", "localStorage", "sessionStorage", "indexedDB")
        if key in context
    }
    local = scratch / f"{target.name}-state.json"
    local.write_text(
        json.dumps(projected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    destination = f"/srv/data/{project_id}/steel-state"
    _run(
        ["docker", "exec", AGENT_CONTAINER, "mkdir", "-p", destination],
        timeout=30,
    )
    _run(
        [
            "docker",
            "cp",
            str(local),
            f"{AGENT_CONTAINER}:{destination}/{state_key}.json",
        ],
        timeout=30,
    )
    _run(
        [
            "docker",
            "exec",
            AGENT_CONTAINER,
            "chmod",
            "600",
            f"{destination}/{state_key}.json",
        ],
        timeout=30,
    )


def _strip_absolute_urls(value: Any) -> Any:
    """Replace deployment origins in operator text with their path.

    The data-dependency contract is deployment-neutral; a bootstrap note that
    names the old host:port goes stale on the next redeploy. This keeps the
    path evidence and drops the origin, without touching a path-only value.
    """
    from urllib.parse import urlsplit

    if isinstance(value, dict):
        return {key: _strip_absolute_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_absolute_urls(item) for item in value]
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"https?://[^\s\"'<>\\]+")
    return pattern.sub(
        lambda match: urlsplit(match.group(0)).path or "/", value
    )


def _install_agent_code(repo: Path) -> None:
    _run(
        ["docker", "exec", AGENT_CONTAINER, "rm", "-rf", AGENT_CODE],
        timeout=60,
    )
    _run(
        ["docker", "exec", AGENT_CONTAINER, "mkdir", "-p", AGENT_CODE],
        timeout=30,
    )
    _run(
        ["docker", "cp", f"{repo}/.", f"{AGENT_CONTAINER}:{AGENT_CODE}"],
        timeout=300,
    )
    _run(
        ["docker", "exec", AGENT_CONTAINER, "mkdir", "-p", "/opt/localbin"],
        timeout=30,
    )
    _run(
        [
            "docker",
            "exec",
            AGENT_CONTAINER,
            "mkdir",
            "-p",
            "/opt/localbin/.steel",
        ],
        timeout=30,
    )
    for source, name in (
        ("/opt/localbin/steel", "steel"),
        ("/opt/localbin/.steel/steel", "steel-real"),
    ):
        local = Path(tempfile.gettempdir()) / f"steel-crawl-{name}"
        _run(
            ["docker", "cp", f"{KALI_CONTAINER}:{source}", str(local)],
            timeout=120,
        )
        _run(
            ["docker", "cp", str(local), f"{AGENT_CONTAINER}:/opt/localbin/{name}"],
            timeout=120,
        )
        if name == "steel-real":
            _run(
                [
                    "docker",
                    "cp",
                    str(local),
                    f"{AGENT_CONTAINER}:/opt/localbin/.steel/steel",
                ],
                timeout=120,
            )
        local.unlink(missing_ok=True)
    _run(
        [
            "docker",
            "exec",
            AGENT_CONTAINER,
            "chmod",
            "755",
            f"{AGENT_CLI}",
            "/opt/localbin/steel-real",
            "/opt/localbin/.steel/steel",
        ],
        timeout=30,
    )


def _edge_token() -> str:
    return f"e2e-{int(time.time())}-{os.getpid()}"


def _run_phase(
    repo: Path,
    project_id: str,
    run_id: str,
    target_url: str,
    *,
    account: str | None,
    edge_root: str,
    result_path: str,
    max_duration_s: int,
    max_actions: int,
) -> dict[str, Any]:
    config = {
        "project_id": project_id,
        "run_id": run_id,
        "target_url": target_url,
        "auth_account": account,
        "edge_root": edge_root,
        "edge_token": _edge_token(),
        "result_path": result_path,
        "seed_base_url": True,
    }
    local_config = Path(tempfile.gettempdir()) / f"steel-crawl-{run_id}.json"
    local_config.write_text(json.dumps(config), encoding="utf-8")
    remote_config = f"/tmp/steel-crawl-{run_id}.json"
    _run(
        ["docker", "cp", str(local_config), f"{AGENT_CONTAINER}:{remote_config}"],
        timeout=30,
    )
    local_config.unlink(missing_ok=True)
    env = {
        "PYTHONPATH": f"{AGENT_CODE}/src:{AGENT_CODE}",
        "STEEL_CRAWL_CLI": AGENT_CLI,
        "STEEL_REAL_BINARY": "/opt/localbin/steel-real",
        "STEEL_CRAWL_MAX_DURATION_S": str(max_duration_s),
        "STEEL_CRAWL_MAX_ACTIONS": str(max_actions),
    }
    typesafe = _env_value(INSTANCE_ENV, "API_KEY_TYPESAFE")
    if typesafe:
        env["API_KEY_TYPESAFE"] = typesafe
    command = [
        "docker",
        "exec",
        *[f"-e={key}={value}" for key, value in env.items()],
        AGENT_CONTAINER,
        "python",
        f"{AGENT_CODE}/eval/steel-crawl-e2e/phase_runner.py",
        "--config",
        remote_config,
    ]
    completed = _run(command, timeout=max_duration_s + 1200, check=False)
    if not completed.stdout.strip():
        remote = _run(
            ["docker", "exec", AGENT_CONTAINER, "cat", result_path],
            timeout=30,
            check=False,
        ).stdout
        raise E2EError(
            "the phase runner produced no JSON: "
            f"stdout={completed.stdout[-500:]!r} "
            f"stderr={completed.stderr[-1500:]!r} "
            f"result={remote[-1500:]!r}"
        )
    payload = _json_line(completed.stdout)
    if not payload.get("ok"):
        raise E2EError(
            f"the phase runner failed: {payload.get('error')}; "
            f"{payload.get('traceback', '')[-1000:]}"
        )
    return payload


def _copy_run_dir(project_id: str, run_id: str, scratch: Path) -> Path:
    source = f"/srv/data/{project_id}/steel-crawl/{run_id}"
    destination = scratch / run_id
    _run(
        ["docker", "cp", f"{AGENT_CONTAINER}:{source}", str(destination)],
        timeout=120,
    )
    return destination


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _secret_values(target: TargetSpec, account: dict[str, Any], context: dict[str, Any]) -> tuple[str, ...]:
    """The values that must never reach the model-visible evidence.

    A username is an identifier, not a secret: it legitimately appears in
    admin URLs (`/admin/...`) and route names. The password, every session
    cookie, and every stored token are secrets.
    """
    values: list[str] = []
    credentials = account.get("credentials")
    if isinstance(credentials, dict):
        password = credentials.get("password")
        username = credentials.get("username")
        # The seeded SiyuCMS administrator uses the degenerate credential
        # password == username == "admin". "admin" is also a legitimate path
        # segment (/index.php/admin/...), so an occurrence cannot prove a
        # password leak. The identifier itself is public; the cookie and the
        # token remain the strict, unambiguous secrets.
        if (
            isinstance(password, str)
            and len(password) >= 4
            and password != username
        ):
            values.append(password)
    for cookie in context.get("cookies") or []:
        if isinstance(cookie, dict) and isinstance(cookie.get("value"), str):
            value = cookie["value"]
            if len(value) >= 8:
                values.append(value)
    for token in (account.get("tokens") or {}).values():
        if isinstance(token, dict) and isinstance(token.get("value"), str):
            value = token["value"]
            if len(value) >= 8:
                values.append(value)
    return tuple(dict.fromkeys(values))


def _prestashop_container_ready(container: str, port: int) -> None:
    """Wait for the target's web container, then make its cache writable.

    A fresh PrestaShop target ships a Symfony production cache under
    `var/cache/prod`, and its PHP `max_execution_time` is 30s. On the emulated
    amd64 host the admin container compile exceeds that limit, so every modern
    admin controller answers 500 until the cache is rebuilt by the web user.
    This is target runtime setup, not crawl behaviour: raise the limit, hand
    the shipped cache to `www-data` (never delete it: a rebuild that starts
    from an absent directory can fail on the class-index dump), and let the
    first authenticated request finish the compile.
    """
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        status = _run(
            ["docker", "inspect", container, "--format", "{{.State.Status}}"],
            timeout=30,
            check=False,
        ).stdout.strip()
        if status == "running":
            break
        time.sleep(2)
    current = _run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            "grep -E '^max_execution_time' /usr/local/etc/php/php.ini | "
            "head -1 | cut -d= -f2",
        ],
        timeout=30,
        check=False,
    ).stdout.strip()
    try:
        limit = int(current)
    except ValueError:
        limit = 0
    if limit < 300:
        _run(
            [
                "docker",
                "exec",
                container,
                "sed",
                "-i",
                "s/^max_execution_time = .*/max_execution_time = 300/",
                "/usr/local/etc/php/php.ini",
            ],
            timeout=30,
        )
        _run(["docker", "restart", container], timeout=120, check=False)
    _run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            "chown -R www-data:www-data /var/www/html/var",
        ],
        timeout=120,
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/admin-dev/index.php",
                follow_redirects=False,
                timeout=10,
            )
            if response.status_code < 500:
                return
        except Exception:  # noqa: BLE001 - readiness is a poll
            pass
        time.sleep(2)
    raise E2EError("the PrestaShop admin page did not become ready")


def _prestashop_warm_path(
    container: str,
    egress: str,
    cookie_name: str,
    cookie_value: str,
    path: str,
) -> None:
    """Build one admin page with an authenticated target-local request.

    The Steel CLI's CDP navigate has a fixed, short command timeout, while the
    first authenticated admin request can take about 100s to compile the
    Symfony container on the emulated host. The warm request runs in the
    target container as `www-data` (so the cache stays writable) and keeps the
    compile out of both the CLI's timeout and the crawl's traversal budget.
    """
    script = r"""
$ctx = stream_context_create(["http" => [
    "header" => "Host: prestashop\r\n"
        . "X-Forwarded-For: " . getenv("PS_XFF") . "\r\n"
        . "Cookie: " . getenv("PS_COOKIE") . "\r\n",
    "timeout" => 300,
    "ignore_errors" => true,
]]);
$body = @file_get_contents(
    "http://127.0.0.1" . getenv("PS_PATH"),
    false,
    $ctx
);
$status = isset($http_response_header[0]) ? $http_response_header[0] : "";
echo $status . "\n" . strlen($body ?: "") . "\n";
"""
    last = ""
    for attempt in range(2):
        completed = _run(
            [
                "docker",
                "exec",
                "-u",
                "www-data",
                "-e",
                "HOME=/tmp",
                "-e",
                f"PS_XFF={egress}",
                "-e",
                f"PS_COOKIE={cookie_name}={cookie_value}",
                "-e",
                f"PS_PATH={path}",
                container,
                "php",
                "-d",
                "default_socket_timeout=300",
                "-r",
                script,
            ],
            timeout=360,
            check=False,
        )
        lines = [line for line in completed.stdout.splitlines() if line]
        last = (lines[0] if lines else completed.stderr.strip()[-300:]) or "no status"
        if completed.returncode == 0 and lines and " 200 " in lines[0]:
            return
        if attempt == 0:
            time.sleep(5)
    raise E2EError(
        f"the PrestaShop page {path} did not warm to 200: {last}"
    )


def _prestashop_warm(
    container: str, egress: str, cookie_name: str, cookie_value: str
) -> None:
    """Warm the crawl entry AND the oracle page before the browser navigates."""
    spec = TARGETS["prestashop"]
    for path in dict.fromkeys(
        item for item in (spec.entry, spec.probe) if item
    ):
        _prestashop_warm_path(
            container, egress, cookie_name, cookie_value, path
        )


def _run_prestashop_login(
    stack: TargetStack,
    steel: SteelCli,
    session: str,
    account: dict[str, Any],
    scratch: Path,
) -> None:
    credentials = account.get("credentials") or {}
    username = str(credentials.get("username") or "")
    password = str(credentials.get("password") or "")
    if not username or not password:
        raise E2EError("the PrestaShop account carries no credentials")
    namespace = DATA_DEPS / "prestashop" / "skills" / "authn" / "references"
    script = namespace / "mint-bo-session.php"
    create = namespace / "create-employee.php"
    if not script.is_file():
        raise E2EError(f"the PrestaShop mint script is missing at {script}")
    if not create.is_file():
        raise E2EError(
            f"the PrestaShop create-employee script is missing at {create}"
        )
    container = stack.web_container()
    _prestashop_container_ready(container, int(stack.port or 0))
    for source, name in (
        (create, "create-employee.php"),
        (script, "mint-bo-session.php"),
    ):
        _run(
            ["docker", "cp", str(source), f"{container}:/tmp/{name}"],
            timeout=30,
        )
    created = _run(
        [
            "docker",
            "exec",
            "-u",
            "www-data",
            "-e",
            f"PS_NEW_EMAIL={username}",
            "-e",
            f"PS_NEW_PASS={password}",
            "-e",
            "PS_NEW_PROFILE=1",
            "-e",
            "HOME=/tmp",
            container,
            "php",
            "/tmp/create-employee.php",
        ],
        timeout=300,
        check=False,
    )
    if created.returncode != 0:
        raise E2EError(
            "the PrestaShop synthetic employee could not be created: "
            f"{(created.stderr or created.stdout).strip()[-500:]}"
        )

    egress = ""
    try:
        steel.navigate(session, f"http://{FRONT_HOST}/_ip")
        egress = str(steel.eval(session, "document.body.innerText") or "").strip()
    except Exception:  # noqa: BLE001 - the front probe is diagnostic
        egress = ""
    if not egress:
        egress = "192.33.91.87"
    minted = _run(
        [
            "docker",
            "exec",
            "-u",
            "www-data",
            "-e",
            "PS_HOST=prestashop",
            "-e",
            f"PS_REMOTE={egress}",
            "-e",
            f"PS_EMAIL={username}",
            "-e",
            f"PS_PASS={password}",
            "-e",
            "HOME=/tmp",
            container,
            "php",
            "/tmp/mint-bo-session.php",
        ],
        timeout=300,
        check=False,
    )
    lines = [line for line in minted.stdout.splitlines() if line]
    if minted.returncode != 0 or len(lines) < 2:
        raise E2EError(
            "the PrestaShop back-office session could not be minted: "
            f"{(minted.stderr or minted.stdout).strip()[-500:]}"
        )
    name, value = lines[-2], lines[-1]
    _prestashop_warm(container, egress, name, value)
    steel.set_cookie(session, name, value)

    # The warm request above built the Symfony container; the browser
    # navigation is now the fast path. It proves the session reaches the
    # dashboard, not the login page.
    steel.navigate(
        session,
        f"http://{FRONT_HOST}{TARGETS['prestashop'].entry}",
        timeout=180,
    )
    data = steel.run("get", "url", session=session).get("data")
    url = data if isinstance(data, str) else str((data or {}).get("url", ""))
    if "AdminLogin" in url:
        raise E2EError(f"the minted cookie landed on {url or 'no url'}")


def _run_siyucms_login(
    steel: SteelCli,
    session: str,
    account: dict[str, Any],
) -> None:
    credentials = account.get("credentials") or {}
    username = str(credentials.get("username") or "")
    password = str(credentials.get("password") or "")
    if not username or not password:
        raise E2EError("the SIYUCMS account carries no credentials")
    steel.navigate(session, f"http://{FRONT_HOST}/")
    script = (
        "(async()=>{"
        "const base=location.origin;"
        "const page=await fetch(base+'/index.php/admin/Login/index.html',"
        "{credentials:'include',cache:'no-store'});"
        "const html=await page.text();"
        "const m=html.match(/name=\"__token__\" value=\"([^\"]+)\"/);"
        "if(!m)return JSON.stringify({ok:false,stage:'token',status:page.status});"
        "const body=new URLSearchParams({username:"
        + json.dumps(username)
        + ",password:"
        + json.dumps(password)
        + ",__token__:m[1]});"
        "const login=await fetch(base+'/index.php/admin/Login/checkLogin.html',"
        "{method:'POST',credentials:'include',"
        "headers:{'Content-Type':'application/x-www-form-urlencoded'},body});"
        "const payload=await login.json().catch(()=>({}));"
        "const consolePage=await fetch(base+'/index.php/admin/Index/index.html',"
        "{credentials:'include',cache:'no-store'});"
        "const text=await consolePage.text();"
        "return JSON.stringify({ok:payload.error==='0'&&"
        "text.includes('控制台'),status:consolePage.status,"
        "login:payload,title:(text.match(/<title>([^<]*)<\\/title>/)||[])[1]||''});"
        "})()"
    )
    raw = steel.eval(session, script)
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        raise E2EError("the SIYUCMS login returned no JSON") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise E2EError(
            f"the SIYUCMS admin login failed: {result if isinstance(result, dict) else raw}"
        )


def _verify_oracle(steel: SteelCli, session: str, probe: str | None) -> None:
    if not probe:
        return
    script = (
        "(async()=>{"
        "if(document.readyState!=='complete'){"
        "await new Promise(r=>window.addEventListener('load',r,{once:true}));}"
        "const c=new AbortController();"
        "const timer=setTimeout(()=>c.abort(),60000);"
        "try{"
        f"const r=await fetch({json.dumps(probe)},"
        "{redirect:'follow',credentials:'include',cache:'no-store',"
        "signal:c.signal});"
        "return JSON.stringify({status:r.status,redirected:r.redirected,url:r.url});"
        "}catch(e){return JSON.stringify({error:String(e)});}"
        "finally{clearTimeout(timer);}"
        "})()"
    )
    last: dict[str, Any] = {}
    for attempt in range(3):
        raw = steel.eval(session, script)
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise E2EError("the oracle probe returned no JSON") from exc
        if not isinstance(result, dict):
            raise E2EError("the oracle probe returned no object")
        last = result
        if not result.get("error"):
            break
        if attempt < 2:
            time.sleep(2)
    if last.get("error"):
        raise E2EError(f"the oracle probe failed: {last['error']}")
    if last.get("redirected") is True or not (
        200 <= int(last.get("status") or 0) < 300
    ):
        raise E2EError(
            f"the oracle probe did not pass: status={last.get('status')} "
            f"redirected={last.get('redirected')}"
        )


def _restore_white_jotter_front() -> None:
    """Restore the shared alias to the White Jotter target after a run.

    The alias is shared deployment state; the scaffold must leave it where the
    other eval runs expect it. The port is read from the running White Jotter
    container, with the last observed port as the fallback.
    """
    completed = _run(
        ["docker", "port", "web_white_jotter-wj-1", "8443"],
        timeout=30,
        check=False,
    )
    match = re.search(r":(\d+)\s*$", completed.stdout.strip())
    port = match.group(1) if match else "46271"
    conf = (
        "server {\n"
        f"    server_name {FRONT_HOST};\n"
        "    listen 80;\n"
        "    location / {\n"
        f"        proxy_pass http://host.docker.internal:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
        "}\n"
    )
    target = f"/etc/nginx/conf.d/eval-target-{FRONT_HOST}.conf"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".conf", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(conf)
        source = handle.name
    try:
        _run(
            ["docker", "cp", source, f"{FRONT_CONTAINER}:{target}"],
            timeout=30,
            check=False,
        )
        _run(
            ["docker", "exec", FRONT_CONTAINER, "nginx", "-s", "reload"],
            timeout=30,
            check=False,
        )
    finally:
        Path(source).unlink(missing_ok=True)


def run_target(
    target_name: str,
    *,
    repo: Path,
    keep: bool = False,
    max_duration_s: int = 900,
    max_actions: int = 300,
    project_name: str | None = None,
) -> RunEvidence:
    """Run one authenticated (or no-auth) live walkthrough end to end."""
    spec = TARGETS[target_name]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    project_name = project_name or f"steel-crawl-e2e-{spec.name}-{stamp}"
    run_id = f"e2e-{spec.name}-{stamp}"
    session_name = ""
    scratch = Path(tempfile.mkdtemp(prefix=f"steel-crawl-{spec.name}-"))
    stack = TargetStack(spec)
    steel = SteelCli()
    api = ProjectApi()
    project_id = ""
    context: dict[str, Any] = {}
    evidence: RunEvidence | None = None
    try:
        stack.up()
        _install_agent_code(repo)
        target_url = f"http://{FRONT_HOST}{spec.entry}"
        project_id = api.create(project_name)
        api.settings(project_id, FRONT_HOST)
        session_name = f"steel-crawl-{project_id}"
        steel.start(session_name)
        if spec.auth == "prestashop_cookie":
            # The back-office entry cannot be loaded before the session exists:
            # a fresh target needs the cookie and the one-time cache warm-up
            # first. The PrestaShop bootstrap navigates /_ip, mints the cookie,
            # and then loads the dashboard.
            document, account_name, account = _credentials(spec)
            _run_prestashop_login(stack, steel, session_name, account, scratch)
        else:
            try:
                steel.navigate(session_name, f"http://{FRONT_HOST}{spec.entry}")
            except E2EError as exc:
                if "ERR_NAME_NOT_RESOLVED" not in str(exc):
                    raise
                # The shared alias is static, but the runtime's per-session
                # resolver occasionally keeps a negative answer; a fresh
                # session gets a fresh browser and the same /etc/hosts mapping.
                steel.stop(session_name)
                steel.start(session_name)
                steel.navigate(session_name, f"http://{FRONT_HOST}{spec.entry}")
            if spec.auth == "none":
                document = {"accounts": {}}
                account_name = ""
                account = {}
            else:
                document, account_name, account = _credentials(spec)
                if spec.auth == "siyucms_form":
                    _run_siyucms_login(steel, session_name, account)
        _verify_oracle(steel, session_name, spec.probe)
        session_id = steel.session_id(session_name)
        catalogue_before = steel.catalogue()
        context = steel.context(session_id)
        if spec.auth != "none":
            state_key = f"e2e-{spec.name}"
            _state_file(spec, project_id, state_key, context, scratch)
            account = _update_account(
                spec, account_name, account, context, state_key
            )
            document.setdefault("accounts", {})[account_name] = account
            _dump_yaml(
                DATA_DEPS / spec.name / "auth" / "credentials.yaml", document
            )
        overview = _strip_absolute_urls(_overview(spec))
        _dump_yaml(
            DATA_DEPS / spec.name / "auth" / "overview.yaml", overview
        )
        archive = _write_skill(spec, session_name, scratch)
        overview_api = {
            key: value for key, value in overview.items() if key != "auth_probe"
        }
        overview_bytes = yaml.safe_dump(
            overview, sort_keys=False, allow_unicode=True
        ).encode("utf-8")
        try:
            api.place_bytes(
                project_id,
                "auth-overview",
                "overview.yaml",
                yaml.safe_dump(
                    overview_api, sort_keys=False, allow_unicode=True
                ).encode("utf-8"),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
        api.write_auth_file(project_id, "overview.yaml", overview_bytes)
        credentials_bytes = yaml.safe_dump(
            document, sort_keys=False, allow_unicode=True
        ).encode("utf-8")
        try:
            api.place_bytes(
                project_id,
                "auth-credentials",
                "credentials.yaml",
                credentials_bytes,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            api.write_auth_file(
                project_id, "credentials.yaml", credentials_bytes
            )
        api.place_skill(project_id, archive.read_bytes())
        operator_kb = DATA_DEPS / spec.name / "operator_kb.md"
        api.place_bytes(
            project_id,
            "l1",
            "operator_kb.md",
            operator_kb.read_bytes(),
        )
        phase = _run_phase(
            repo,
            project_id,
            run_id,
            target_url,
            account=account_name or None,
            edge_root=f"/tmp/steel-crawl-edge/{run_id}",
            result_path=f"/tmp/steel-crawl-edge/{run_id}/result.json",
            max_duration_s=max_duration_s,
            max_actions=max_actions,
        )
        run_dir = _copy_run_dir(project_id, run_id, scratch)
        manifest = _read_json(run_dir / "manifest.json")
        summary = _read_json(run_dir / "summary.json")
        ledger = _read_jsonl(run_dir / "ledger.jsonl")
        recon = api.recon(project_id, run_id)
        graph = api.graph(project_id)
        auth = api.auth(project_id)
        catalogue = steel.catalogue()
        secrets = _secret_values(spec, account, context)
        evidence = RunEvidence(
            target=spec.name,
            project_id=project_id,
            run_id=run_id,
            session_name=session_name,
            target_url=target_url,
            phase=phase,
            manifest=manifest,
            summary=summary,
            ledger_entries=ledger,
            recon=recon,
            graph=graph,
            auth=auth,
            session_catalogue=catalogue,
            session_catalogue_before=catalogue_before,
            secrets=secrets,
            extra={"run_dir": str(run_dir), "scratch": str(scratch)},
        )
        return evidence
    finally:
        api.close()
        if not keep:
            steel.stop(session_name)
            if evidence is not None:
                evidence.session_catalogue_after = steel.catalogue()
        stack.restore_front()
        _restore_white_jotter_front()
        if not keep:
            stack.down()


__all__ = [
    "E2EError",
    "RunEvidence",
    "SteelCli",
    "TARGETS",
    "TargetSpec",
    "TargetStack",
    "run_target",
]
