#!/usr/bin/env python3
"""End-to-end simulation: receive a QuerySpec, retrieve, generate, read answer.

Two run modes:
  --direct     run the pipeline in-process (add --mock to avoid live services)
  --endpoint   POST the spec to a running app at POST /lightrag/query
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from polymerhus.app.config import config  # noqa: E402
from lightrag.client import LightRAGHttpClient  # noqa: E402
from lightrag.generation import DeepSeekClient  # noqa: E402
from lightrag.pipeline import MockMode, run_query_pipeline  # noqa: E402
from lightrag.query_spec import QuerySpecV1, R_A, R_B  # noqa: E402


def load_spec(path: Path) -> QuerySpecV1:
    return QuerySpecV1.model_validate_json(path.read_text(encoding="utf-8"))


def print_result(result) -> None:
    print("=== RESULT ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default="examples/lightrag-query-simulation/P6B-EASY-01.json",
    )
    parser.add_argument("--config", choices=["R-A", "R-B"], default="R-A")
    parser.add_argument("--mock", action="store_true", help="deterministic offline stand-ins")
    parser.add_argument("--direct", action="store_true", help="run in-process")
    parser.add_argument(
        "--verbose", action="store_true", help="print every stage: query, retrieval, prompt, raw answer"
    )
    parser.add_argument(
        "--endpoint", default=None, help="POST to a running app, e.g. http://127.0.0.1:8080"
    )
    parser.add_argument("--out", default=None, help="write result JSON here")
    args = parser.parse_args()

    spec = load_spec(Path(args.scenario))
    retrieval_config = R_A if args.config == "R-A" else R_B

    if args.endpoint and not args.direct:
        response = httpx.post(
            f"{args.endpoint.rstrip('/')}/lightrag/query?config={args.config}",
            json=spec.model_dump(),
            timeout=300,
        )
        response.raise_for_status()
        result = response.json()
    else:
        if args.mock:
            result = run_query_pipeline(
                spec,
                retrieval_config=retrieval_config,
                mock=MockMode(),
                audit=args.verbose,
            )
        else:
            client = LightRAGHttpClient()
            llm = DeepSeekClient(
                base_url=config.QUERY_LLM_BASE_URL,
                api_key=config.QUERY_LLM_API_KEY,
                model=config.QUERY_LLM_MODEL,
                max_tokens=config.QUERY_LLM_MAX_TOKENS,
                timeout=config.QUERY_LLM_TIMEOUT_SECONDS,
            )
            result = run_query_pipeline(
                spec,
                retrieval_config=retrieval_config,
                client=client,
                llm=llm,
                audit=args.verbose,
            )
        result = result.model_dump()

    if args.verbose and result.get("audit"):
        audit = result["audit"]
        print("=== 1. QUERY RECEIVED (mock agent -> /lightrag/query) ===")
        print(json.dumps(spec.model_dump(), indent=2, ensure_ascii=False))
        print("\n=== 2. PAYLOAD SENT TO LIGHTRAG /query/data ===")
        print(json.dumps(audit["retrieval_payload"], indent=2, ensure_ascii=False))
        print("\n=== 3. CONTEXT RETRIEVED FROM LIGHTRAG ===")
        print(audit.get("retrieved_context_text") or "(empty)")
        print("\nREFERENCE REGISTRY:")
        print("\n".join(audit.get("reference_registry") or []) or "(none)")
        print("\n=== 4. PROMPT SENT TO DEEPSEEK ===")
        print(audit.get("generation_prompt") or "(no generation)")
        print("\n=== 5. RAW DEEPSEEK RESPONSE ===")
        print(json.dumps(audit.get("raw_model_response", {}), indent=2, ensure_ascii=False))
        print()

    print_result(result)
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
