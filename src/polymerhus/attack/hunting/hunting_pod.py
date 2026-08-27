"""The real hunting pod (IA-3/IA-4): deterministic HTTP probing of the D4 spec.

The hunting-agent harness calls `pod(spec)` once per dispatched hunt and
expects the D5+D6 envelope: `{"verdict": str, "evidence": {terminal_reason,
clean, iterations, interpretations, init_validation?}}`. This pod executes the
spec's `payload_vector_space` against the target with bounded HTTP probes and
derives the verdict deterministically - no LLM in the execution path.

Bounds and safety:
  * the target URL comes from the injected `target_url` or from the spec's
    `target_identity.url`; absent both, the pod returns an INIT rejection
    (`technical-infeasibility` + `init_validation`) instead of guessing a host;
  * only http/https targets and GET/HEAD vectors are executed; anything else is
    an INIT rejection (the spec must be re-authored);
  * `{id}` placeholders probe a baseline id (`1`) and a tampered id (`124`);
    other vectors run once; requests are bounded (`max_requests`) and
    non-redirecting.

Import performs no I/O: the httpx client is built per call and a transport can
be injected for hermetic tests.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_METHODS = {"GET", "HEAD"}
_BASELINE_ID = "1"
_TAMPERED_ID = "124"
_ID_PATTERN = re.compile(r"\{id\}")


def _target_url(spec: dict, injected: str | None) -> str | None:
    if injected:
        return injected
    identity = ((spec.get("d4_typed_base") or {}).get("target_identity") or {})
    for key in ("url", "base_url", "baseurl"):
        value = identity.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _vectors(spec: dict) -> list[tuple[str, str]]:
    """The `(method, path)` probe pair from the authored `payload_vector_space`.

    Contract (#191): `payload_vector_space` is ONE open dict per spec - the
    typed canonical attributes (`method`, `path`) cited directly, any further
    per-attack-layer keys open. There is NO defaulting for any attribute: a
    dict that does not carry BOTH a `method` and a `path` (and a non-dict)
    yields no vectors, never an invented GET or a url-derived path."""
    pvs = ((spec.get("d4_typed_base") or {}).get("payload_vector_space") or {})
    if not isinstance(pvs, dict):
        return []
    method = str(pvs.get("method") or "").strip().upper()
    path = str(pvs.get("path") or "").strip()
    if not method or not path:
        return []
    return [(method, path)]


def _probe_url(target: str, path: str, probe_id: str) -> str:
    if re.match(r"^https?://", path, re.IGNORECASE):
        return _ID_PATTERN.sub(probe_id, path)
    base = target.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{base}{_ID_PATTERN.sub(probe_id, path)}"


class HuntingHttpPod:
    """The deterministic HTTP probing pod (see module docstring for bounds)."""

    def __init__(
        self,
        *,
        target_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        max_requests: int = 16,
    ):
        self._target_url = target_url
        self._transport = transport
        self._timeout = timeout
        self._max_requests = max_requests

    def __call__(self, spec: dict) -> dict:
        target = _target_url(spec, self._target_url)
        if not target:
            return self._envelope(
                "technical-infeasibility",
                clean=False,
                init_validation=[
                    "no target URL available: populate target_identity.url or "
                    "inject the asset base URL into the pod"
                ],
                interpretations=["target URL missing"],
            )
        if not re.match(r"^https?://", target, re.IGNORECASE):
            return self._envelope(
                "technical-infeasibility",
                clean=False,
                init_validation=[f"unsupported target scheme: {target}"],
                interpretations=["target URL rejected"],
            )
        vectors = _vectors(spec)
        if not vectors:
            return self._envelope(
                "technical-infeasibility",
                clean=False,
                init_validation=["the spec carries no payload_vector_space"],
                interpretations=["empty vector set"],
            )
        unsupported = [m for m, _p in vectors if m not in _METHODS]
        if unsupported:
            return self._envelope(
                "technical-infeasibility",
                clean=False,
                init_validation=[
                    "the pod executes GET/HEAD vectors only; re-author the spec"
                ],
                interpretations=[f"unsupported vector method: {m}" for m in unsupported],
            )

        requests_made = 0
        interpretations: list[dict[str, Any]] = []
        symptom_seen = False
        all_definitive = True
        with httpx.Client(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=False,
        ) as client:
            for method, path in vectors:
                probes = [(_BASELINE_ID, _TAMPERED_ID)] if "{id}" in path else [(None, None)]
                for baseline_id, tampered_id in probes:
                    if requests_made >= self._max_requests:
                        all_definitive = False
                        interpretations.append({"vector": f"{method} {path}", "error": "request budget exhausted"})
                        break
                    statuses: dict[str, int | str] = {}
                    probe_labels = (
                        (("baseline", baseline_id), ("tampered", tampered_id))
                        if baseline_id is not None
                        else (("single", None),)
                    )
                    for label, probe_id in probe_labels:
                        try:
                            requests_made += 1
                            url = _probe_url(target, path, probe_id or "")
                            response = client.request(method, url)
                            statuses[label] = response.status_code
                        except httpx.HTTPError as exc:
                            logger.warning("hunting pod probe %s failed: %s", path, exc)
                            statuses[label] = "error"
                            all_definitive = False
                    interpretations.append({"vector": f"{method} {path}", **statuses})
                    if baseline_id is not None and tampered_id is not None:
                        baseline_allowed = _allowed(statuses.get("baseline"))
                        tampered_allowed = _allowed(statuses.get("tampered"))
                        if baseline_allowed is False and tampered_allowed is True:
                            symptom_seen = True

        if symptom_seen:
            return self._envelope(
                "symptom-confirmed", clean=True,
                interpretations=interpretations, iterations=requests_made,
                verdict="successful",
            )
        return self._envelope(
            "no-symptom-evidence", clean=all_definitive,
            interpretations=interpretations, iterations=requests_made,
        )

    @staticmethod
    def _envelope(
        terminal_reason: str,
        *,
        clean: bool,
        init_validation: list[str] | None = None,
        interpretations: list | None = None,
        iterations: int = 1,
        verdict: str = "unsuccessful",
    ) -> dict:
        evidence: dict[str, Any] = {
            "terminal_reason": terminal_reason,
            "clean": clean,
            "iterations": iterations,
            "interpretations": interpretations or [],
        }
        if init_validation:
            evidence["init_validation"] = init_validation
        return {"verdict": verdict, "evidence": evidence}


def _allowed(status) -> bool | None:
    """True = request allowed (2xx/3xx), False = denied (4xx), None = unknown."""
    if not isinstance(status, int):
        return None
    if 200 <= status < 400:
        return True
    if 400 <= status < 500:
        return False
    return None
