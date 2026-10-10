#!/usr/bin/env python
"""Session-cache measurement harness for #348 (EV-33).

Drives the REAL stateful session path (`app.llm.session.stateful_turn`) for one
session role, one turn per (fresh, realistic, large) HumanMessage, and reads the
per-model-call cached/uncached split out of the process-wide usage ledger
(`app.llm.usage.usage_ledger()`). It mirrors the production wiring:

- mechanism_typist: the reflection prompt built by
  `analysis.mechanism_typist._reflection_prompt` over a synthetic but realistic
  `Chunk` (Endpoint assets with content_type/title/status/server props plus
  triager Observations), with the role skill as a per-turn SystemMessage - the
  same shape `stateful_invoke_fn` drives.
- hunting_orchestrator: the hypothesise prompt built by
  `attack.hunting.llm._compose_gate_prompt` over a synthetic `GateInput`
  (DeliveredCandidates + fault materialisation), with `_gate_skill()` as the one
  stable system prompt and the union structured decision - the same shape the
  `HuntOrchestratorActor` drives on `HuntingOrchestratorSession`.

Both run with the role's real compaction middleware
(`build_role_compaction_middleware`) so the #348 non-converging-pass mechanism is
exercised. The compaction window is scaled down (see --seed-ctx / --threshold /
--replay-keep-tokens) to reproduce the #348 trigger within a handful of cheap
turns: the exempt replay tail is made to dwarf the budget so a pass that folds
the older region still leaves the thread over budget. That is the same trigger
the ADR's deterministic harness used ("a trail whose exempt tail dwarfs the
budget"), at a fraction of the eval's 200K-token scale.

Run (direct-provider mode; the local gateway is down):
    set -a && source /Users/diekgbbtt/polymerhus/.env && set +a
    env -u LLM_GATEWAY_URL PYTHONPATH=src \
      /Users/diekgbbtt/polymerhus/.venv/bin/python tools/measure_session_cache.py \
      --role mechanism_typist --turns 6 --mode post

`--mode pre` monkey-patches `CompactionManager.apply_staged` to reset the
consecutive-pass streak on every applied pass (the pre-#348 behaviour), so the
same harness can measure the before/after on identical inputs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# The local gateway is DOWN; the harness bypasses it (direct per-provider mode).
os.environ.pop("LLM_GATEWAY_URL", None)
# Mirror the eval deployment's REQUIRED capability override (docker-compose.eval /
# eval/env_preflight.py): the opencode-go relay refuses json_schema + forced
# tool_choice, so structured output must negotiate the tool rung. Without this the
# summariser/structured turns would 400 (the F12 signature) and no pass would apply.
os.environ.setdefault(
    "LLM_CAPABILITY_OVERRIDES",
    '{"opencode-go/deepseek-v4.1-flash": {"supports_structured_output": false, "supports_forced_tool_choice": false}}',
)
# Keep tracing out of the measurement (no Langfuse network, no key needed).
for _k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
    os.environ.pop(_k, None)
# The strict msgpack guard blocks re-hydrating a persisted structured_response
# (GateDecision) across turns; the in-memory MemorySaver harness disables it so
# the resumed trail stays clean (the eval's AsyncPostgresSaver serialises it).
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

PROJECT = os.environ.get("MEASURE_PROJECT", "measure-cache-348")

PROVIDER, MODEL = "opencode-go", "deepseek-v4.1-flash"

_ROLES = ("mechanism_typist", "hunting_orchestrator")


def seed_capability(context_limit: int) -> None:
    """Seed the held capability profile with the eval gateway's real record facts.

    The gateway is down locally, so `resolve_capability` would fall back to the
    150k default and an UNKNOWN reasoning surface - and an unknown
    `reasoning_in_response` makes the D7 exempt replay tail empty, which is
    exactly the condition that hides the #348 trigger. The eval record carries
    `max_input_tokens=1000000` and a reasoning surface; we seed a known profile
    (source set) plus the required override booleans so negotiation and the D7
    tail behave as in the eval. `context_limit` is scaled by the caller.
    """
    from polymerhus.app.llm import capability as cap

    cap._PROFILE_CACHE[(PROVIDER, MODEL)] = cap.CapabilityProfile(
        context_limit=context_limit,
        output_limit=32768,
        supports_tool_calling=True,
        supports_structured_output=False,
        source="models.dev",
        reasoning_in_response=True,
        reasoning_field="reasoning_content",
        supports_forced_tool_choice=False,
    )


# --- realistic message builders ----------------------------------------------

_ENDPOINT_NOUNS = ("users", "orders", "invoices", "payments", "products", "sessions",
                   "tokens", "cart", "checkout", "profile", "settings", "reports",
                   "uploads", "webhooks", "roles", "permissions", "audit", "search")
_TITLES = ("Sign in", "Product detail", "Order history", "Invoice download",
           "Checkout", "Account settings", "Admin console", "User profile",
           "Payment methods", "Report viewer", "Upload manager", "API explorer")
_SERVERS = ("nginx/1.24.0", "openresty/1.21.4", "Apache/2.4.57", "uvicorn", "gunicorn/20.1.0")


def _mechanism_prompt(k: int, target_chars: int, salt: str):
    """A fresh, realistic mechanism-typist reflection prompt, grown to `target_chars`.

    `salt` (the unique run tag) makes every run's content distinct so provider
    prefix caching can never leak across runs - only the byte-stable role skill
    (the leading SystemMessage) may legitimately hit from a previous run."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.analysis.chunking import Chunk
    from polymerhus.analysis.mechanism_typist import _load_skill, _reflection_prompt
    from polymerhus.recon.domain.types import AssetDelta, Observation

    base = f"https://app-{k}-{salt}.target.test"
    assets = []
    observations = []
    i = 0
    prompt = ""
    while len(prompt) < target_chars:
        i += 1
        noun = _ENDPOINT_NOUNS[i % len(_ENDPOINT_NOUNS)]
        path = f"/api/v{k}/{noun}/{i:04d}?filter=active&page={i}"
        assets.append(AssetDelta(
            type="Endpoint",
            identity={"path": path, "baseurl": base},
            props={
                "method": ("GET", "POST", "PUT", "DELETE")[i % 4],
                "content_type": ("application/json", "text/html")[i % 2],
                "title": f"{_TITLES[i % len(_TITLES)]} - tenant {k} record {i}",
                "status_code": (200, 201, 302, 401, 403, 500)[i % 6],
                "server": _SERVERS[i % len(_SERVERS)],
                "content_length": 1024 + (i * 137) % 200000,
                "profile": ("restapi", "webapp")[i % 2],
                "cache_control": "no-store, private",
                "vary": "Accept-Encoding, Cookie, Authorization",
                "x_powered_by": "Express" if i % 3 else "Next.js",
            },
        ))
        observations.append(Observation(
            macro_kind=("broken_access_control", "session_management", "input_validation")[i % 3],
            severity=("high", "medium", "low")[i % 3],
            evidence=(f"response for {noun} record {i} carried a tenant-scoped object "
                      f"id in the body without an ownership check on the {noun} collection"),
            rationale=(f"the {noun} collection endpoint exposes sequential record ids and "
                       f"accepts a numeric path segmentable by an authenticated peer tenant"),
            anchor={"type": "BaseURL", "identity": {"url": base}},
            source_job=f"httpx_reprofile_{k}",
            source_tool="httpx",
        ))
        chunk = Chunk(chunk_id=f"chunk-{k}", source_job=f"job-{k}",
                      assets=tuple(assets), observations=tuple(observations))
        prompt = _reflection_prompt(chunk, {})

    system = SystemMessage(content=_load_skill())
    human = HumanMessage(content=prompt)
    return [system, human], None


def _hunting_prompt(k: int, target_chars: int, salt: str):
    """A fresh, realistic hunt-orchestrator hypothesise prompt, grown to `target_chars`.

    `salt` (the unique run tag) keeps every run's content distinct so provider
    prefix caching cannot leak across runs. The schema is the hypothesise turn's
    OWN decision (`GateDecision`) - the faithful per-turn schema; the actor's
    three-way union is a multi-phase device and its ToolStrategy union was
    rejected (HTTP 400) by the local relay in this harness."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from polymerhus.attack.hunting.hunt_orchestrator import (
        DeliveredCandidate,
        GateDecision,
        GateInput,
        Witness,
    )
    from polymerhus.attack.hunting.llm import _compose_gate_prompt, _gate_skill

    fault = f"CWE-{639 + k}"
    candidates = []
    i = 0
    prompt = ""
    while len(prompt) < target_chars:
        i += 1
        candidates.append(DeliveredCandidate(
            unit_id=f"Service:tenant-{k}-{salt}-{_ENDPOINT_NOUNS[i % len(_ENDPOINT_NOUNS)]}-{i}",
            fault_class=fault,
            applies_witnesses=Witness(
                deterministic=f"service exposes an endpoint family reachable with a peer "
                              f"tenant session (collection {i})",
                llm=f"the {_ENDPOINT_NOUNS[i % len(_ENDPOINT_NOUNS)]} collection at record "
                    f"{i} returns objects keyed only by a sequential id; an authenticated "
                    f"peer tenant can enumerate neighbouring records and read their data",
            ),
            match_verdict="applies",
        ))
        materialisation = {fault: {
            "name": "Authorization Bypass Through User-Controlled Key (IDOR)",
            "description": "The system's authorization does not verify that the resource "
                           "identified by a user-supplied key belongs to the requesting user.",
            "extended_description": (
                "When an application uses user-supplied identifiers to look up objects and "
                "fails to confirm ownership, a peer can substitute the identifier and reach "
                "another tenant's object. " * (4 + k)),
            "alternate_terms": ["IDOR", "insecure direct object reference", "BOLA"],
            "related_attack_patterns": ["CAPEC-87", "CAPEC-676"],
            "likelihood": "high",
            "common_consequences": ["read other tenants' records", "modify foreign records"],
            "potential_mitigations": ["enforce object-level authorization on every access"],
            "functional_areas": ["data access", "session management", "business logic"],
        }}
        inp = GateInput(
            candidates=candidates,
            kb_degraded=False,
            surface=[{"path": f"/api/v1/{_ENDPOINT_NOUNS[(i + j) % len(_ENDPOINT_NOUNS)]}/{j}",
                      "method": "GET", "status": 200} for j in range(6)],
            materialisation=materialisation,
            fold_family={fault: ["CWE-284", "CWE-285", "CWE-863"]},
            prior_minted_keys=[f"Service:tenant-{k}-{j}::{fault}::IDOR" for j in range(4)],
        )
        prompt = _compose_gate_prompt(inp)

    schema = GateDecision
    # The actor passes `system_prompt=_gate_skill()` once; the harness instead
    # prepends the byte-stable skill as a per-turn SystemMessage (the
    # mechanism-typist pattern, `_dedup_system_messages` collapses the copies).
    # This keeps the trail self-contained and avoids the system_prompt /
    # MemorySaver fresh-delta interaction that let the hunting trail grow
    # unbounded. Content is byte-identical to the actor's system prompt.
    return [SystemMessage(content=_gate_skill()), HumanMessage(content=prompt)], schema, None


# --- the run ----------------------------------------------------------------

_EMPTY_ENTRY = {"cached": 0, "uncached": 0, "generated": 0, "calls": 0}


def _entry(role: str, snap: dict) -> dict:
    a = (snap.get("by_agent") or {}).get(role) or {}
    return {
        "cached": (a.get("context_tokens") or {}).get("cached", 0),
        "uncached": (a.get("context_tokens") or {}).get("uncached", 0),
        "generated": sum((a.get("generated_tokens") or {}).values()),
        "calls": a.get("calls", 0),
        "capped": a.get("capped_tokens", 0),
        "total": a.get("total_tokens", 0),
    }


def run(role: str, *, turns: int, mode: str, replay_keep: int, threshold: float,
        seed_ctx: int, target_chars: int, run_tag: str) -> dict:
    os.environ["LLM_COMPACTION_THRESHOLD"] = str(threshold)
    seed_capability(seed_ctx)

    from polymerhus.app.llm import usage as U

    ledger = U.usage_ledger()
    ledger.reset()  # process-wide; isolate this run (pure in-memory, no store attached)

    calls: list[dict] = []
    _orig_record = ledger.record

    def _rec(project_id, agent, usage):
        _orig_record(project_id, agent, usage)
        if usage and (project_id or "unscoped") == PROJECT:
            calls.append(U._axis_totals(usage))

    ledger.record = _rec  # instance attr shadows the bound method

    # Per-run summary-regeneration counter (one per applied compact pass).
    from polymerhus.app.llm.compaction import CompactionManager

    state = {"regen": 0}
    _orig_apply = CompactionManager.apply_staged

    def _apply(self, thread_id, result, delta=None):
        # One call to apply_staged == one running-summary regeneration.
        state["regen"] += 1
        out = _orig_apply(self, thread_id, result, delta)
        if mode == "pre":
            # pre-#348: a successful applied pass ALWAYS reset the streak.
            with self._lock:
                self._streak[thread_id] = 0
                self._escalated.pop(thread_id, None)
                entry = self.ledger.entry(thread_id)
                if entry is not None:
                    entry.escalated = False
        return out

    CompactionManager.apply_staged = _apply

    from langgraph.checkpoint.memory import MemorySaver

    from polymerhus.app.llm import compaction as C
    from polymerhus.app.llm.session import stateful_turn
    from polymerhus.app.llm.session_address import AnalysisSession, HuntingOrchestratorSession

    if role == "mechanism_typist":
        thread = AnalysisSession(run_tag, role)
    else:
        thread = HuntingOrchestratorSession(run_tag)

    checkpointer = MemorySaver()
    mw = C.build_role_compaction_middleware(role)
    mw.manager.replay_keep_tokens = replay_keep

    turn_rows: list[dict] = []
    for k in range(turns):
        if role == "mechanism_typist":
            new_messages, schema = _mechanism_prompt(k, target_chars, run_tag)
            system_prompt = None
        else:
            new_messages, schema, system_prompt = _hunting_prompt(k, target_chars, run_tag)

        before = _entry(role, ledger.snapshot(PROJECT))
        calls_before = len(calls)
        regen_before = state["regen"]
        t0 = time.time()
        stateful_turn(
            role, thread, new_messages,  # type: ignore[arg-type]
            checkpointer=checkpointer, schema=schema, system_prompt=system_prompt,
            middleware=[mw], usage_scope=PROJECT, observe=False,
        )
        dt = time.time() - t0
        after = _entry(role, ledger.snapshot(PROJECT))
        entry = mw.manager.ledger.entry(thread.thread_id)
        report = mw.manager.last_report(thread.thread_id)
        turn_rows.append({
            "turn": k,
            "calls": after["calls"] - before["calls"],
            "unc": after["uncached"] - before["uncached"],
            "cached": after["cached"] - before["cached"],
            "gen": after["generated"] - before["generated"],
            "regen_this_turn": state["regen"] - regen_before,
            "regen_total": state["regen"],
            "occupancy": getattr(entry, "occupancy", None),
            "over_budget": getattr(entry, "over_budget", None),
            "streak": mw.manager.streak(thread.thread_id),
            "escalated": mw.manager.is_escalated(thread.thread_id),
            "summary_status": getattr(report, "summary_status", None),
            "readability": getattr(report, "readability", None),
            "elapsed_s": round(dt, 1),
        })
        print(
            f"  turn {k}: calls={turn_rows[-1]['calls']} "
            f"unc={turn_rows[-1]['unc']} cached={turn_rows[-1]['cached']} "
            f"gen={turn_rows[-1]['gen']} regen={turn_rows[-1]['regen_this_turn']} "
            f"occ={turn_rows[-1]['occupancy']} over={turn_rows[-1]['over_budget']} "
            f"streak={turn_rows[-1]['streak']} ({dt:.1f}s)",
            file=sys.stderr,
        )

    total = _entry(role, ledger.snapshot(PROJECT))
    total_ctx = total["cached"] + total["uncached"]
    cache_fraction = (total["cached"] / total_ctx) if total_ctx else 0.0
    return {
        "role": role,
        "mode": mode,
        "run_tag": run_tag,
        "turns": turns,
        "threshold": threshold,
        "seed_ctx": seed_ctx,
        "budget": int(seed_ctx * threshold),
        "replay_keep_tokens": replay_keep,
        "target_prompt_chars": target_chars,
        "calls": calls,
        "turns_table": turn_rows,
        "totals": total,
        "cache_fraction": cache_fraction,
        "summary_regenerations": state["regen"],
    }


def _print_call_table(result: dict) -> None:
    print(f"\n=== {result['role']} / {result['mode']} (calls: {len(result['calls'])}) ===")
    print(f"{'idx':>3} | {'unc':>8} | {'cached':>8} | {'ctx':>8} | {'gen':>6}")
    for i, c in enumerate(result["calls"]):
        ctx = c["cached"] + c["uncached"]
        gen = c["reasoning"] + c["visible"]
        print(f"{i:>3} | {c['uncached']:>8} | {c['cached']:>8} | {ctx:>8} | "
              f"{gen:>6}")
    t = result["totals"]
    print(f"total unc={t['uncached']} cached={t['cached']} gen={t['generated']} "
          f"calls={t['calls']} cache_fraction={result['cache_fraction']:.3f} "
          f"summary_regens={result['summary_regenerations']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=_ROLES, required=True)
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--mode", choices=("post", "pre"), default="post")
    ap.add_argument("--replay-keep-tokens", type=int, default=2000)
    ap.add_argument("--threshold", type=float, default=0.02)
    ap.add_argument("--seed-ctx", type=int, default=150000)
    ap.add_argument("--target-chars", type=int, default=15000)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    print(f"[{args.role}/{args.mode}] budget={int(args.seed_ctx * args.threshold)} "
          f"replay_keep={args.replay_keep_tokens} turns={args.turns}", file=sys.stderr)
    result = run(
        args.role, turns=args.turns, mode=args.mode,
        replay_keep=args.replay_keep_tokens, threshold=args.threshold,
        seed_ctx=args.seed_ctx, target_chars=args.target_chars,
        run_tag=f"measure-{args.role}-{args.mode}-{int(time.time())}",
    )
    _print_call_table(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
        print(f"\nraw -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
