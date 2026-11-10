"""Kali-side bounded stream writer for one acquired JavaScript lead."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_component(value: str, what: str) -> str:
    if not value or not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"{what} is not a safe opaque component")
    return value


def _post_json(
    url: str,
    reference: str,
    payload: dict,
    *,
    timeout_s: float,
) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "X-JS-Intake-Reference": reference,
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=timeout_s) as response:
        body = response.read()
    try:
        value = json.loads(body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _record_failure(
    agent_url: str,
    reference: str,
    lead_id: str,
    reason: str,
    *,
    timeout_s: float,
) -> dict:
    response_payload = {}
    broker_reachable = False
    try:
        response_payload = _post_json(
            f"{agent_url}/recon/js-analysis/fail",
            reference,
            {"lead_id": lead_id, "failure_reason": reason},
            timeout_s=timeout_s,
        )
        broker_reachable = True
    except Exception:
        pass
    result = {
        "lead_id": lead_id,
        "status": str(response_payload.get("status") or "failed"),
        "failure_reason": reason,
        "broker_reachable": broker_reachable,
        "keep_work_file": (
            bool(response_payload.get("keep_work_file"))
            if broker_reachable
            else True
        ),
        "reconcile_required": (
            bool(response_payload.get("reconcile_required"))
            if broker_reachable
            else True
        ),
    }
    return result


def _write_reconcile_marker(
    *,
    run_dir: Path,
    lead_id: str,
    work_file_ref: str,
    sha256: str,
    size: int,
    reason: str,
) -> None:
    marker_dir = run_dir / ".reconcile"
    marker_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=marker_dir, prefix=f".{lead_id}.", suffix=".tmp"
    )
    destination = marker_dir / f"{lead_id}.json"
    payload = {
        "lead_id": lead_id,
        "work_file_ref": work_file_ref,
        "sha256": sha256,
        "size": size,
        "reason": reason,
        "recorded_at": int(time.time()),
    }
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def acquire_lead_to_work_file(
    *,
    agent_url: str,
    reference: str,
    lead_id: str,
    work_root: str | Path = "/work/js-analysis",
    timeout_s: float = 60.0,
) -> dict:
    _safe_component(lead_id, "lead_id")
    agent_url = agent_url.rstrip("/")
    request = Request(
        f"{agent_url}/recon/js-analysis/acquire/{lead_id}",
        headers={"X-JS-Intake-Reference": reference},
    )
    try:
        response = urlopen(request, timeout=timeout_s)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except Exception:
            payload = {}
        reason = str(payload.get("failure_reason") or f"http_status_{exc.code}")
        return {
            "lead_id": lead_id,
            "status": "failed",
            "failure_reason": reason,
        }
    except Exception:
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "transfer_failed",
            timeout_s=timeout_s,
        )

    run_id = str(response.headers.get("X-JS-Run-Id") or "")
    expected_size = str(response.headers.get("X-JS-Size") or "")
    expected_sha = str(response.headers.get("X-JS-SHA256") or "")
    content_type = str(
        response.headers.get("X-JS-Content-Type") or "application/javascript"
    )
    work_file_ref = str(response.headers.get("X-JS-Work-File-Ref") or "")
    try:
        _safe_component(run_id, "run_id")
        if (not expected_size.isdigit() or int(expected_size) > 8 * 1024 * 1024
                or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)):
            raise ValueError("invalid acquisition metadata")
        expected_name = f"{expected_sha}.js"
        if not work_file_ref.endswith(f"/{run_id}/{expected_name}"):
            raise ValueError("unexpected work-file reference")
    except ValueError:
        response.close()
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "invalid_acquisition_metadata",
            timeout_s=timeout_s,
        )

    run_dir = Path(work_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=run_dir, prefix=f".{lead_id}.", suffix=".part"
    )
    final_path = run_dir / expected_name
    digest = hashlib.sha256()
    size = 0
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                if size > int(expected_size):
                    raise ValueError("transfer exceeds declared size")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        response.close()
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "transfer_failed",
            timeout_s=timeout_s,
        )
    finally:
        response.close()

    actual_sha = digest.hexdigest()
    if size != int(expected_size):
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "transfer_failed",
            timeout_s=timeout_s,
        )
    if actual_sha != expected_sha:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "hash_mismatch",
            timeout_s=timeout_s,
        )

    try:
        os.replace(temp_name, final_path)
    except Exception:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        return _record_failure(
            agent_url,
            reference,
            lead_id,
            "rename_failed",
            timeout_s=timeout_s,
        )

    confirmation = {
        "lead_id": lead_id,
        "size": size,
        "sha256": actual_sha,
        "work_file_ref": work_file_ref,
    }
    try:
        acknowledgement = _post_json(
            f"{agent_url}/recon/js-analysis/confirm",
            reference,
            confirmation,
            timeout_s=timeout_s,
        )
        if acknowledgement.get('status') != 'acquired' or any(
            acknowledgement.get(key) != value for key, value in confirmation.items()
        ):
            raise ValueError('invalid manifest confirmation')
    except Exception:
        failure = _record_failure(
            agent_url,
            reference,
            lead_id,
            "ack_failed",
            timeout_s=timeout_s,
        )
        if not failure.get("broker_reachable"):
            _write_reconcile_marker(
                run_dir=run_dir,
                lead_id=lead_id,
                work_file_ref=work_file_ref,
                sha256=actual_sha,
                size=size,
                reason="ack_unresolved",
            )
            failure.update(
                status="reconcile_required",
                failure_reason="ack_unresolved",
                keep_work_file=True,
                reconcile_required=True,
            )
            return failure
        if failure.get("reconcile_required"):
            failure.update(
                status="reconcile_required",
                failure_reason="confirmation_ack_lost",
                keep_work_file=True,
            )
            return failure
        if not failure.get("keep_work_file"):
            final_path.unlink(missing_ok=True)
        return failure

    return {
        "lead_id": lead_id,
        "status": "acquired",
        "content_type": content_type,
        "size": size,
        "sha256": actual_sha,
        "work_file_ref": work_file_ref,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-url", default="http://agent:8080")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--work-root", default="/work/js-analysis")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    result = acquire_lead_to_work_file(
        agent_url=args.agent_url,
        reference=args.reference,
        lead_id=args.lead_id,
        work_root=args.work_root,
        timeout_s=args.timeout,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "acquired" else 1


if __name__ == "__main__":
    raise SystemExit(main())
