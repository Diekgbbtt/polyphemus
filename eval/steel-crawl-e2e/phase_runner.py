#!/usr/bin/env python3
"""Run one `steel_crawl` recon phase inside the deployed agent container.

This is the in-agent half of the steel-crawl e2e scaffold. It starts the real
HTTP-history edge on a loopback port, seeds the target BaseURL into the graph,
and drives the production `run_pipeline` with `job_subset=["steel_crawl"]`.
The gateway, the auth feed, the crawl pod, the engine, the ledger, the edge,
and the curator are the deployed components; only the target stack, the Steel
session, and the test assertions live outside.

Input is one JSON config file; output is one JSON result file (and the same
object on stdout). No secret is printed: the config carries no credential, and
the account material stays in the app's data root.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# The scaffold is mounted beside the app; the app's own modules resolve first
# from the deployed image, and the e2e's copy of the crawl engine overlays it.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _seed_base_url(project_id: str, target_url: str) -> None:
    from polymerhus.recon.domain.curator import curate
    from polymerhus.recon.domain.types import AssetDelta

    curate(
        [AssetDelta(type="BaseURL", identity={"url": target_url})],
        [],
        project_id,
    )


def _align_app_roots() -> None:
    """Point the overlay code at the deployed app's data and skills roots.

    The scaffold mounts this worktree at `/opt/steel-crawl-e2e`, so the
    package-relative `DATA_ROOT` and `_SKILLS_ROOT` would resolve beside the
    mount instead of the deployed `/srv/data` and `/srv/skills` the API wrote.
    The stores read these module globals at call time, so aligning them here
    keeps the phase process on the same project state as the API.
    """
    from pathlib import Path as _Path

    import polymerhus.app.data_root as data_root

    data_root.DATA_ROOT = _Path("/srv/data")
    import polymerhus.app.auth.store as auth_store

    auth_store.DATA_ROOT = data_root.DATA_ROOT
    import polymerhus.app.llm.skills as skills

    skills._SKILLS_ROOT = _Path("/srv/skills")


def _edge_result(edge_root: str, project_id: str) -> dict:
    from kali.http_history.store import HttpHistoryStore

    store = HttpHistoryStore(edge_root, project_id)
    try:
        status = store.status()
        artifacts: list[dict] = []
        cursor: str | None = None
        while True:
            page = store.search(cursor=cursor, limit=200)
            artifacts.extend(
                {
                    "artifact_id": artifact.artifact_id,
                    "method": artifact.request.method,
                    "url": artifact.request.url,
                    "status": (
                        artifact.response.status if artifact.response else None
                    ),
                    "response_body_ref": (
                        artifact.response.body_ref if artifact.response else None
                    ),
                }
                for artifact in page.artifacts
            )
            cursor = page.next_cursor
            if not cursor:
                break
        return {"status": status, "artifacts": artifacts}
    finally:
        store.close()


def _run_summary(project_id: str, run_id: str) -> dict:
    from polymerhus.app.clients import pg

    return {
        "run": pg.get_run(run_id),
        "jobs": pg.get_run_jobs(run_id),
        "project_id": project_id,
    }


def _static_orchestrator_factory(account: str):
    """A deterministic gateway verdict for the already-minted live session.

    The crawl walkthroughs are about the crawl, not about the LLM gateway's
    turn latency; the gateway's own live path is covered by
    `tests/e2e/test_gateway_*` and `eval/steel-e2e-395`. The engine still runs
    the real authenticated-context oracle against the live session, so the
    crawl's authentication precondition is not mocked.
    """
    from polymerhus.recon.control.authn_loop import GatewayVerdict

    verdict = GatewayVerdict(
        outcome="authenticated",
        account=account,
        branch="browser_only",
        replayability_resolved=False,
        rationale=(
            "e2e static gateway: the scaffold minted and verified the "
            "pre-authenticated live Steel session; the crawl runs the real "
            "authenticated-context oracle before traversal."
        ),
    )

    class _StaticGateway:
        async def run_gateway(self, *, project_id: str | None = None):
            return verdict

        async def stop(self) -> None:
            return None

    return lambda run_id: _StaticGateway()


def _parsed_counts(project_id: str, run_id: str, host: str) -> dict:
    """The parser's endpoint/parameter deltas for the manifest the crawl wrote.

    The graph sink is expected to contain exactly these records; counting them
    here lets the walkthrough assert the sink, without re-deriving the
    manifest's own endpoint set.
    """
    from pathlib import Path as _Path

    from polymerhus.recon.domain.parsers import get_parser

    manifest_path = (
        _Path("/srv/data") / project_id / "steel-crawl" / run_id / "manifest.json"
    )
    if not manifest_path.is_file():
        return {"endpoints": 0, "parameters": 0, "present": False}
    from polymerhus.recon.domain.noise_filter import filter_deltas

    deltas = get_parser("steel_crawl")(manifest_path.read_text(encoding="utf-8"))
    kept = filter_deltas(deltas, scope_domain=host)
    endpoints = {
        (
            delta.identity.get("path"),
            delta.identity.get("method"),
            delta.identity.get("baseurl"),
        )
        for delta in kept
        if delta.type == "Endpoint"
        and _host_of(str(delta.identity.get("baseurl") or "")) == host
    }
    parameters = {
        (
            delta.identity.get("name"),
            delta.identity.get("position"),
            delta.identity.get("endpoint_path"),
            delta.identity.get("baseurl"),
        )
        for delta in kept
        if delta.type == "Parameter"
        and _host_of(str(delta.identity.get("baseurl") or "")) == host
    }
    raw_endpoints = {
        (
            delta.identity.get("path"),
            delta.identity.get("method"),
            delta.identity.get("baseurl"),
        )
        for delta in deltas
        if delta.type == "Endpoint"
        and _host_of(str(delta.identity.get("baseurl") or "")) == host
    }
    return {
        "endpoints": len(endpoints),
        "parameters": len(parameters),
        "raw_endpoints": len(raw_endpoints),
        "present": True,
    }


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    project_id = str(config["project_id"])
    run_id = str(config["run_id"])
    target_url = str(config["target_url"])
    edge_root = str(config["edge_root"])
    edge_token = str(config["edge_token"])
    result_path = Path(config["result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "ok": False,
        "project_id": project_id,
        "run_id": run_id,
        "target_url": target_url,
        "started_at": time.time(),
    }
    server = None
    thread = None
    try:
        _align_app_roots()
        from kali.http_history.edge import StoreCache, create_edge_server

        server = create_edge_server(
            StoreCache(edge_root), edge_token, "127.0.0.1", 0
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_port
        os.environ["KALI_HTTP_HISTORY_EDGE_URL"] = f"http://127.0.0.1:{port}"
        os.environ["KALI_HTTP_HISTORY_EDGE_TOKEN"] = edge_token
        result["edge_url"] = f"http://127.0.0.1:{port}"

        if config.get("seed_base_url", True):
            _seed_base_url(project_id, target_url)

        from polymerhus.recon.control.pipeline import run_pipeline

        account = config.get("auth_account")
        pipeline_kwargs = {
            "run_id": run_id,
            "job_subset": ["steel_crawl"],
            "with_analysis": False,
        }
        if account:
            pipeline_kwargs["orchestrator_factory"] = (
                _static_orchestrator_factory(str(account))
            )
        asyncio.run(run_pipeline(project_id, **pipeline_kwargs))
        result["pipeline"] = _run_summary(project_id, run_id)
        result["parsed"] = _parsed_counts(
            project_id, run_id, _host_of(target_url)
        )
        result["edge"] = _edge_result(edge_root, project_id)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - the result records the failure
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        result["finished_at"] = time.time()
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
