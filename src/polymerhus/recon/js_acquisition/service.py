"""Private lead resolution and bounded JavaScript fetching."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from polymerhus.app.auth.store import AuthStore
from polymerhus.recon.js_acquisition.capture import SteelCaptureStore
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import JsIntakeReader


@dataclass(frozen=True)
class AcquisitionLimits:
    max_file_bytes: int = 8 * 1024 * 1024
    max_run_bytes: int = 64 * 1024 * 1024
    max_redirects: int = 5
    timeout_s: float = 30.0


class AcquisitionError(RuntimeError):
    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class AcquisitionResult:
    lead_id: str
    body: bytes
    status_code: int
    content_type: str
    size: int
    sha256: str
    work_file_ref: str

    def public_metadata(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "status": "fetched_pending_work_file",
            "content_type": self.content_type,
            "size": self.size,
            "sha256": self.sha256,
            "work_file_ref": self.work_file_ref,
        }


@dataclass(frozen=True)
class FetchedMap:
    body: bytes
    final_url: str
    content_type: str
    status_code: int


_JS_CONTENT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/node",
    "application/x-javascript",
    "text/ecmascript",
    "text/javascript",
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    return (
        parts.scheme.lower(),
        (parts.hostname or "").lower(),
        parts.port,
    )


def _host_in_scope(host: str, domains: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _load_auth_headers(
    project_id: str, context_ref: str, *, store: AuthStore
) -> dict[str, str]:
    if not context_ref:
        return {}
    from polymerhus.recon.control.auth_feed import (
        project_request_auth,
        resolve_account,
        resolve_overview,
    )

    account = resolve_account(project_id, context_ref, store=store)
    if not account:
        return {}
    material = project_request_auth(
        account, resolve_overview(project_id, store=store)
    )
    headers: dict[str, str] = {}
    cookies = material.get("cookies") or []
    cookie_value = "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if isinstance(cookie, dict)
        and isinstance(cookie.get("name"), str)
        and isinstance(cookie.get("value"), str)
    )
    if cookie_value:
        headers["Cookie"] = cookie_value
    for name, value in material.items():
        if name in {"cookies", "credentials", "roles", "default_role", "realm"}:
            continue
        if isinstance(name, str) and isinstance(value, str) and value:
            headers[name] = value
    return headers


class AcquisitionService:
    def __init__(
        self,
        *,
        root: str | Path | None = None,
        work_root: str | Path = "/work/js-analysis",
        limits: AcquisitionLimits | None = None,
        auth_headers_for: Callable[[str, str], dict[str, str]] | None = None,
        capture_store: SteelCaptureStore | None = None,
    ) -> None:
        self._root = root
        self._work_root = Path(work_root)
        self._limits = limits or AcquisitionLimits()
        self._intake = JsIntakeReader(root=root)
        self._auth_store = AuthStore(root_dir=root)
        self._auth_headers_for = auth_headers_for
        self._capture_store = capture_store or SteelCaptureStore(root=root)

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=self._limits.max_run_bytes,
        )

    def _deliver(
        self,
        *,
        manifest: AcquisitionManifest,
        project_id: str,
        run_id: str,
        lead_id: str,
        context_ref: str,
        body: bytes,
        content_type: str,
        final_url: str,
        auth_state_source: str,
        auth_state_equivalent: bool,
        capture_id: str | None = None,
        record: dict | None = None,
        sourcemap_header: str | None = None,
        x_sourcemap_header: str | None = None,
    ) -> AcquisitionResult:
        digest = hashlib.sha256(body).hexdigest()
        work_ref = f"/work/js-analysis/{run_id}/{digest}.js"
        pending_record = {
            **(record or {}),
            "context_ref": context_ref,
            "final_url": final_url,
            "http_status": 200,
            "content_type": content_type,
            "auth_state_source": auth_state_source,
            "auth_state_equivalent": auth_state_equivalent,
            "auth_gap": None,
            "capture_id": capture_id,
            "sourcemap_header": sourcemap_header,
            "x_sourcemap_header": x_sourcemap_header,
        }
        if not manifest.reserve(
            lead_id=lead_id,
            record=pending_record,
            work_file_ref=work_ref,
            sha256=digest,
            size=len(body),
        ):
            raise AcquisitionError("quota_exhausted")
        return AcquisitionResult(
            lead_id=lead_id,
            body=body,
            status_code=200,
            content_type=content_type,
            size=len(body),
            sha256=digest,
            work_file_ref=work_ref,
        )

    def fetch(self, *, reference: str, lead_id: str) -> AcquisitionResult:
        lead, scope = self._intake.get_private(
            reference=reference, lead_id=lead_id
        )
        exact_url = str(lead.get("exact_url") or "")
        manifest = self._manifest(scope.project_id, scope.run_id)
        record = manifest.get().setdefault("leads", {}).get(lead_id) or {}
        auth_context_ref = str(lead.get("auth_context_ref") or "")
        label = lead.get('auth_context_label')
        if label not in {'anonymous', 'authenticated'} or (label == 'authenticated') != bool(auth_context_ref):
            manifest.update(lambda value: value['leads'].__setitem__(lead_id, {
                'lead_id': lead_id, 'context_ref': scope.context_ref, 'status': 'failed',
                'available': False, 'failure_reason': 'auth_context_missing',
            }))
            raise AcquisitionError('auth_context_missing')

        if not scope.allow_http_replay and record.get('status') == 'acquired' and record.get('available') and (record.get('context_ref') or '') == scope.context_ref:
            digest=str(record.get('sha256') or '')
            if re.fullmatch('[0-9a-f]{64}',digest):
                local=self._work_root / scope.run_id / (digest + '.js')
                if local.is_file() and local.stat().st_size == record.get('size') and local.stat().st_size <= self._limits.max_file_bytes:
                    body=local.read_bytes()
                    if hashlib.sha256(body).hexdigest()==digest:
                        return self._deliver(manifest=manifest,project_id=scope.project_id,run_id=scope.run_id,
                            lead_id=lead_id,context_ref=scope.context_ref,body=body,
                            content_type=record.get('content_type') or 'application/javascript',
                            final_url=record.get('final_url') or exact_url,
                            auth_state_source=record.get('auth_state_source') or 'verified_local',
                            auth_state_equivalent=bool(record.get('auth_state_equivalent')),record=record)
        captures = (
            self._capture_store.find_by_lead(
                project_id=scope.project_id,
                run_id=scope.run_id,
                pod_id=str(lead.get("source_pod") or ""),
                auth_context_ref=auth_context_ref or None,
                exact_url=exact_url,
                lead_id=lead_id,
            )
            if lead.get("source_tool") == "steel_crawl"
            else []
        )
        if captures:
            stored = [
                occurrence
                for occurrence in captures
                if occurrence.get("status") == "stored"
            ]
            versions = {
                str(occurrence.get("sha256"))
                for occurrence in stored
                if occurrence.get("sha256")
            }
            if len(versions) > 1:
                manifest.update(
                    lambda value: value["leads"].__setitem__(
                        lead_id,
                        {
                            **record,
                            "lead_id": lead_id,
                            "context_ref": scope.context_ref,
                            "status": "failed",
                            "failure_reason": "multiple_capture_versions",
                            "capture_ids": [
                                occurrence["capture_id"] for occurrence in stored
                            ],
                            "capture_version_count": len(versions),
                            "auth_state_source": "steel_response_capture",
                            "auth_state_equivalent": True,
                            "final_url": exact_url,
                        },
                    )
                )
                raise AcquisitionError("multiple_capture_versions")
            if stored:
                occurrence = stored[0]
                try:
                    body = self._capture_store.read_bytes(
                        project_id=scope.project_id,
                        run_id=scope.run_id,
                        occurrence=occurrence,
                    )
                except ValueError:
                    manifest.update(
                        lambda value: value["leads"].__setitem__(
                            lead_id,
                            {
                                **record,
                                "lead_id": lead_id,
                                "context_ref": scope.context_ref,
                                "status": "failed",
                                "failure_reason": "capture_unavailable",
                                "capture_id": occurrence.get("capture_id"),
                                "auth_state_source": "steel_response_capture",
                                "auth_state_equivalent": True,
                                "final_url": exact_url,
                            },
                        )
                    )
                    raise AcquisitionError("capture_unavailable") from None
                return self._deliver(
                    manifest=manifest,
                    project_id=scope.project_id,
                    run_id=scope.run_id,
                    lead_id=lead_id,
                    context_ref=scope.context_ref,
                    body=body,
                    content_type=str(
                        occurrence.get("content_type")
                        or "application/javascript"
                    ),
                    final_url=exact_url,
                    auth_state_source="steel_response_capture",
                    auth_state_equivalent=True,
                    capture_id=str(occurrence["capture_id"]),
                    record=record,
                )
            gap_reason = str(
                captures[-1].get("failure_reason") or "capture_unavailable"
            )
            manifest.update(
                lambda value: value["leads"].__setitem__(
                    lead_id,
                    {
                        **record,
                        "lead_id": lead_id,
                        "context_ref": scope.context_ref,
                        "status": "failed",
                        "failure_reason": "capture_unavailable",
                        "capture_gap_reason": gap_reason,
                        "capture_ids": [
                            occurrence["capture_id"] for occurrence in captures
                        ],
                        "auth_state_source": "steel_response_capture",
                        "auth_state_equivalent": True,
                        "final_url": exact_url,
                    },
                )
            )
            raise AcquisitionError("capture_unavailable")

        if not scope.allow_http_replay:
            raise AcquisitionError('browser_only_capture_required')

        # A Steel lead can be an HTTP observation or a debugger-only script.
        # Neither may be replayed with anonymous/request-material fallback when
        # the authenticated browser capture is absent.
        if auth_context_ref and lead.get("source_tool") == "steel_crawl":
            manifest.update(
                lambda value: value["leads"].__setitem__(
                    lead_id,
                    {
                        **record,
                        "lead_id": lead_id,
                        "context_ref": scope.context_ref,
                        "status": "failed",
                        "failure_reason": "browser_auth_state_not_captured",
                        "auth_state_source": "unavailable",
                        "auth_state_equivalent": False,
                        "auth_gap": "browser_session_updates_not_synced",
                        "final_url": exact_url,
                    },
                )
            )
            raise AcquisitionError("browser_auth_state_not_captured")

        if auth_context_ref:
            auth_headers = (
                self._auth_headers_for(
                    scope.project_id, auth_context_ref
                )
                if self._auth_headers_for is not None
                else _load_auth_headers(
                    scope.project_id,
                    auth_context_ref,
                    store=self._auth_store,
                )
            )
            if not auth_headers:
                manifest.update(
                    lambda value: value["leads"].__setitem__(
                        lead_id,
                        {
                            **record,
                            "lead_id": lead_id,
                            "context_ref": scope.context_ref,
                            "status": "failed",
                            "failure_reason": "auth_context_unavailable",
                            "auth_state_source": "unavailable",
                            "auth_state_equivalent": False,
                            "auth_gap": "auth_context_unavailable",
                            "final_url": exact_url,
                        },
                    )
                )
                raise AcquisitionError("auth_context_unavailable")
            auth_state_source = (
                "injected_request_material"
                if self._auth_headers_for is not None
                else "auth_store_request_material"
            )
            auth_state_equivalent = True
            auth_gap = None
        else:
            auth_headers = {}
            auth_state_source = "anonymous"
            auth_state_equivalent = True
            auth_gap = None
        current_url = exact_url
        initial_origin = _origin(exact_url)
        initial_host = (urlsplit(exact_url).hostname or "").lower()
        initial_host_in_scope = (
            not scope.scope_domains
            or _host_in_scope(initial_host, scope.scope_domains)
        )
        response = None
        sourcemap_header = None
        x_sourcemap_header = None
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=self._limits.timeout_s,
                trust_env=False,
            ) as client:
                for hop in range(self._limits.max_redirects + 1):
                    request_headers = (
                        auth_headers
                        if (
                            initial_host_in_scope
                            and _origin(current_url) == initial_origin
                        )
                        else {}
                    )
                    with client.stream(
                        "GET", current_url, headers=request_headers
                    ) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            if hop >= self._limits.max_redirects:
                                raise AcquisitionError("too_many_redirects")
                            location = response.headers.get("location")
                            if not location:
                                raise AcquisitionError("redirect_without_location")
                            next_url = urljoin(current_url, location)
                            next_host = (urlsplit(next_url).hostname or "").lower()
                            initial_host = (urlsplit(exact_url).hostname or "").lower()
                            if not (
                                next_host == initial_host
                                or _host_in_scope(next_host, scope.scope_domains)
                            ):
                                raise AcquisitionError("redirect_out_of_scope")
                            current_url = next_url
                            continue

                        content_type = (
                            response.headers.get("content-type") or ""
                        ).split(";", 1)[0].strip().lower()
                        if response.status_code != 200:
                            raise AcquisitionError(
                                f"http_status_{response.status_code}",
                                status_code=response.status_code,
                            )
                        if content_type not in _JS_CONTENT_TYPES:
                            raise AcquisitionError(
                                "non_js_content_type",
                                status_code=response.status_code,
                            )
                        declared_length = response.headers.get("content-length")
                        if (
                            declared_length
                            and declared_length.isdigit()
                            and int(declared_length) > self._limits.max_file_bytes
                        ):
                            raise AcquisitionError("file_too_large")
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > self._limits.max_file_bytes:
                                raise AcquisitionError("file_too_large")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        sourcemap_header = response.headers.get("sourcemap")
                        x_sourcemap_header = response.headers.get("x-sourcemap")
                        break
                else:
                    raise AcquisitionError("too_many_redirects")

        except AcquisitionError as exc:
            final_url = (
                str(response.url) if response is not None else current_url
            )
            content_type = (
                response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if response is not None
                else None
            )
            manifest.update(
                lambda value: value["leads"].__setitem__(
                    lead_id,
                    {
                        **record,
                        "lead_id": lead_id,
                        "context_ref": scope.context_ref,
                        "status": "failed",
                        "failure_reason": exc.reason,
                        "http_status": exc.status_code,
                        "final_url": final_url,
                        "content_type": content_type,
                        "auth_state_source": auth_state_source,
                        "auth_state_equivalent": auth_state_equivalent,
                        "auth_gap": auth_gap,
                    },
                )
            )
            raise
        except httpx.RequestError:
            manifest.update(
                lambda value: value["leads"].__setitem__(
                    lead_id,
                    {
                        **record,
                        "lead_id": lead_id,
                        "context_ref": scope.context_ref,
                        "status": "failed",
                        "failure_reason": "transport_error",
                        "final_url": current_url,
                        "auth_state_source": auth_state_source,
                        "auth_state_equivalent": auth_state_equivalent,
                        "auth_gap": auth_gap,
                    },
                )
            )
            raise AcquisitionError("transport_error") from None

        return self._deliver(
            manifest=manifest,
            project_id=scope.project_id,
            run_id=scope.run_id,
            lead_id=lead_id,
            context_ref=scope.context_ref,
            body=body,
            content_type=content_type,
            final_url=current_url,
            auth_state_source=auth_state_source,
            auth_state_equivalent=auth_state_equivalent,
            record=record,
            sourcemap_header=sourcemap_header,
            x_sourcemap_header=x_sourcemap_header,
        )

    def _fetch_authorized_resource(
        self,
        *,
        reference: str,
        lead_id: str,
        resource_url: str,
        max_bytes: int,
        require_json: bool,
    ) -> FetchedMap:
        lead, scope = self._intake.get_private(
            reference=reference, lead_id=lead_id
        )
        if not scope.allow_http_replay:
            raise AcquisitionError('browser_only_http_replay_forbidden')
        acquired = (
            self._manifest(scope.project_id, scope.run_id)
            .get()
            .get("leads", {})
            .get(lead_id)
            or {}
        )
        if acquired.get("status") != "acquired" or not acquired.get("available"):
            raise AcquisitionError("lead_not_acquired")
        auth_context_ref = str(lead.get("auth_context_ref") or "")
        if (
            auth_context_ref
            and lead.get("source_tool") == "steel_crawl"
        ):
            raise AcquisitionError("browser_auth_state_not_captured")
        if auth_context_ref:
            auth_headers = (
                self._auth_headers_for(scope.project_id, auth_context_ref)
                if self._auth_headers_for is not None
                else _load_auth_headers(
                    scope.project_id,
                    auth_context_ref,
                    store=self._auth_store,
                )
            )
            if not auth_headers:
                raise AcquisitionError("auth_context_unavailable")
        else:
            auth_headers = {}
        parts = urlsplit(resource_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise AcquisitionError("unsupported_map_url")
        initial_origin = _origin(resource_url)
        initial_host = parts.hostname.lower()
        initial_host_in_scope = (
            not scope.scope_domains
            or _host_in_scope(initial_host, scope.scope_domains)
        )
        current_url = resource_url
        response = None
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=self._limits.timeout_s,
                trust_env=False,
            ) as client:
                for hop in range(self._limits.max_redirects + 1):
                    headers = (
                        auth_headers
                        if (
                            initial_host_in_scope
                            and _origin(current_url) == initial_origin
                        )
                        else {}
                    )
                    with client.stream("GET", current_url, headers=headers) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if not location:
                                raise AcquisitionError("redirect_without_location")
                            if hop >= self._limits.max_redirects:
                                raise AcquisitionError("too_many_redirects")
                            next_url = urljoin(current_url, location)
                            next_host = (urlsplit(next_url).hostname or "").lower()
                            if not (
                                next_host == initial_host
                                or _host_in_scope(next_host, scope.scope_domains)
                            ):
                                raise AcquisitionError("redirect_out_of_scope")
                            current_url = next_url
                            continue
                        content_type = (
                            response.headers.get("content-type") or ""
                        ).split(";", 1)[0].strip().lower()
                        if response.status_code != 200:
                            raise AcquisitionError(
                                f"http_status_{response.status_code}",
                                status_code=response.status_code,
                            )
                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > max_bytes:
                            raise AcquisitionError(
                                "map_size_limit"
                                if require_json
                                else "source_size_limit"
                            )
                        chunks = []
                        total = 0
                        for chunk in response.iter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise AcquisitionError(
                                    "map_size_limit"
                                    if require_json
                                    else "source_size_limit"
                                )
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        if require_json:
                            try:
                                decoded = json.loads(body)
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                raise AcquisitionError(
                                    "non_json_map_response"
                                    if content_type == "text/html"
                                    or body.lstrip().startswith(b"<")
                                    else "invalid_map_json"
                                ) from None
                            if not isinstance(decoded, dict):
                                raise AcquisitionError("invalid_map_json")
                        elif (
                            content_type == "text/html"
                            and body.lstrip().startswith(b"<")
                        ):
                            raise AcquisitionError("html_login_fallback")
                        return FetchedMap(
                            body=body,
                            final_url=str(response.url),
                            content_type=content_type,
                            status_code=200,
                        )
                raise AcquisitionError("too_many_redirects")
        except httpx.RequestError:
            raise AcquisitionError("transport_error") from None

    def fetch_map(
        self,
        *,
        reference: str,
        lead_id: str,
        map_url: str,
        max_bytes: int,
    ) -> FetchedMap:
        return self._fetch_authorized_resource(
            reference=reference,
            lead_id=lead_id,
            resource_url=map_url,
            max_bytes=max_bytes,
            require_json=True,
        )

    def fetch_missing_source(
        self,
        *,
        reference: str,
        lead_id: str,
        source_url: str,
        max_bytes: int,
    ) -> FetchedMap:
        return self._fetch_authorized_resource(
            reference=reference,
            lead_id=lead_id,
            resource_url=source_url,
            max_bytes=max_bytes,
            require_json=False,
        )

    def confirm(
        self,
        *,
        reference: str,
        lead_id: str,
        size: int,
        sha256: str,
        work_file_ref: str,
    ) -> dict:
        lead, scope = self._intake.get_private(
            reference=reference, lead_id=lead_id
        )
        manifest = self._manifest(scope.project_id, scope.run_id)
        outcome = manifest.confirm(
            lead_id=lead_id,
            size=size,
            sha256=sha256,
            work_file_ref=work_file_ref,
        )
        if outcome == "confirmation_mismatch":
            raise AcquisitionError("confirmation_mismatch")
        current = manifest.get().get("leads", {}).get(lead_id) or {}
        if current.get("capture_id"):
            self._capture_store.release_lead(
                project_id=scope.project_id,
                run_id=scope.run_id,
                pod_id=str(lead.get("source_pod") or ""),
                lead_id=lead_id,
            )
        return {
            "lead_id": lead_id,
            "status": "acquired",
            "size": size,
            "sha256": sha256,
            "work_file_ref": work_file_ref,
            "idempotent": outcome == "already_acquired",
        }

    def fail(
        self,
        *,
        reference: str,
        lead_id: str,
        failure_reason: str,
    ) -> dict:
        _, scope = self._intake.get_private(
            reference=reference, lead_id=lead_id
        )
        manifest = self._manifest(scope.project_id, scope.run_id)
        outcome = manifest.fail(
            lead_id=lead_id,
            failure_reason=failure_reason,
        )
        return {
            "lead_id": lead_id,
            "status": outcome["status"],
            "failure_reason": failure_reason,
            "keep_work_file": outcome["keep_work_file"],
            "reconcile_required": outcome["reconcile_required"],
        }
