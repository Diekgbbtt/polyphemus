"""Shared state-graph-hunter fixtures (memory integration + e2e tiers).

The state-graph hunter's seams (spec 5, ADR R4): the per-project
`HunterMemoryStore`, the `hunts_store` / `notes` tool seam over it, and the
turn-by-turn ReAct host's `model_factory` (a scripted model emitting REAL tool
calls - the standard tool interface the harness binds request-only). Owned here
so the memory contract catalogue (C1-C28) and the harness-seam catalogue (H1-H6)
speak the SAME canned objects and the duplication stays in one place.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunting_agent import build_sync_hunting_agent

PROJECT = "proj-a"
UNIT_ID = "Service:slug:a"
UNIT_NAME = "Service-slug-a"
HUNT_KEY = f"{UNIT_NAME}__loop-1"


class _ScriptedFake(BaseChatModel):
    """A one-reply scripted model: either a REAL tool call (name + args, the
    standard tool interface the harness binds request-only) or a plain answer
    (no tool calls -> the model concluded the hunt). Every message list it was
    handed is appended to the shared `seen` list (the hint assertions read the
    tool responses). The `seen` list rides a pydantic `PrivateAttr` so
    construction never copies it."""

    reply: dict
    call_id: str
    _seen: list = PrivateAttr()

    def __init__(self, *, reply, seen, call_id):
        super().__init__(reply=reply, call_id=call_id)
        self._seen = seen

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append([getattr(m, "content", None) for m in messages])
        answer = self.reply.get("answer")
        if answer is not None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content=answer, tool_calls=[]))])
        name, args = self.reply["tool_call"]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{
                "name": name, "args": args,
                "id": self.call_id, "type": "tool_call",
            }],
        ))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


class _RaisingModel(BaseChatModel):
    """A model whose generation RAISES the given exception verbatim - the REAL
    provider seam. The production turn raises an UNTYPED `openai.RateLimitError`
    / `TimeoutError`, never the harness's `ProviderUnavailableError`, so this
    fake reproduces the raw raise the #312 verifier observed
    (`surfer: hunt graph degraded for ... (429 Too Many Requests)`)."""

    exc: BaseException

    def __init__(self, *, exc: BaseException):
        super().__init__(exc=exc)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise self.exc

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "raising-fake"


def _openai_rate_limit_error(message: str = "429 Too Many Requests"):
    """A REAL `openai.RateLimitError` (429), the untyped raise the production
    hunter turn sees - constructed through the SDK like the gateway does."""
    import httpx  # noqa: PLC0415
    import openai  # noqa: PLC0415

    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError(message, response=response, body=None)


def _hunter_factory(steps, seen=None):
    """A `model_factory` yielding a fresh scripted model per turn, walking the
    script (one build per `arun_session_turn`)."""
    cursor = {"i": 0}
    record = seen if seen is not None else []

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _ScriptedFake(
            reply=steps[min(i, len(steps) - 1)],
            seen=record,
            call_id=f"h-{i}",
        )

    return make


def _tool_call(name, args=None):
    """One scripted REAL tool call the model emits (name + args per schema)."""
    return {"tool_call": (name, args or {})}


def _answer(text):
    """One scripted plain answer - the model concluded the hunt."""
    return {"answer": text}


def _hunter_payload(**overrides) -> dict:
    """The canonical loop payload the surfer materialises at dispatch (S2 8.2)
    for the `(Service:slug:a, loop-1)` pair - the SAME key set
    `materialise_hunter_payload` emits."""
    payload = {
        "dispatch_id": HUNT_KEY,
        "run_id": "run-1",
        "loop_id": "loop-1",
        "unit_id": UNIT_ID,
        "unit_kind": "service",
        "loop": {
            "id": "loop-1",
            "fault_ref": "fault-1",
            "vulnerability_ref": "v-1",
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "likelihood": "high",
            "likelihood_rationale": "An anonymous caller controls the id.",
            "impact": {
                "confidentiality": "low",
                "integrity": "none",
                "availability": "none",
                "end_impact": "A caller reads another tenant's item.",
            },
            "confidence": "INFERRED",
            "evidences": [{"kind": "request", "ref": "GET /api/a"}],
        },
        "technical_sharpening": {
            "interface_agreements": [{
                "id": "ia-1",
                "statement": "The endpoint reads the item id from the query.",
            }],
            "control_flows": [{"id": "cf-1"}],
            "data_flows": [{"id": "df-1"}],
        },
        "trust_agreement": {
            "id": "ta-1",
            "statement": "The lookup trusts the caller's item id.",
        },
        "dynamic_state": None,
        "programming_fault": {
            "id": "fault-1",
            "label": "improper authorisation on the item lookup",
            "description": "The handler does not check item ownership.",
        },
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "evidence": [{"kind": "request", "ref": "GET /api/a"}],
        "likelihood": "high",
        "likelihood_rationale": "An anonymous caller controls the id.",
        "vulnerability_rationale": "An anonymous caller reads another user's item.",
        "confidence": "INFERRED",
        "target_context": {
            "unit_id": UNIT_ID,
            "unit_kind": "service",
            "baseline_refs": ["GET /api/a"],
        },
    }
    payload.update(overrides)
    return payload


def build_memory_store(tmp_path) -> HunterMemoryStore:
    """A real `HunterMemoryStore` rooted on the test's tmp_path (the explicit
    root the module's tests use; the fixed seam root stays production-only)."""
    return HunterMemoryStore(root_dir=tmp_path)


def build_hunter_agent(memory_store, *, run_id="run-1", project_id=PROJECT,
                       steps=None, seen=None, kb_fn=None, overview=None):
    """The REAL turn-by-turn harness with a scripted model - the memory
    walkthroughs' entry seam. The live edge (the LLM session) is driven by the
    scripted `model_factory`; the real store, the real five-tool surface, and
    the real compiled graph ride. `overview` is the value the injected
    settings-only Overview seam returns (None -> no Overview message, so the
    walkthroughs never touch the settings store)."""
    return build_sync_hunting_agent(
        run_id=run_id,
        project_id=project_id,
        memory_store=memory_store,
        kb_fn=kb_fn,
        model_factory=_hunter_factory(steps or [], seen=seen),
        checkpointer=InMemorySaver(),
        middleware=[],
        observe=False,
        overview_fn=lambda project_id: overview,
    )


class _HuntingL1:
    """The fixture L1 read seam: serves the L1 INVENTORY cyphers
    (`read_l1_inventory`'s services/systems reads) and the per-unit projection
    reads, so the modeller's grounding provider runs against one deterministic
    in-memory model."""

    def __init__(self, *, services=(), systems=(), units=()):
        self.services = list(services)
        self.systems = list(systems)
        self.units = dict(units)

    def __call__(self, cypher, params):
        if "L1TestableUnit" in cypher:
            if "type(dr) AS family" in cypher:
                unit = self.units.get(f"{params['kind']}:{params['key']}")
                return [{"family": f} for f in (unit or {}).get("data_rel_families", [])]
            unit = self.units.get(f"{params['kind']}:{params['key']}")
            if unit is None:
                return []
            return [{"labels": unit["labels"], "props": unit["props"],
                     "edges": unit.get("edges", [])}]
        if "L1Service" in cypher:
            return [{"slug": s["slug"], "contract": s.get("contract")}
                    for s in self.services]
        if "L1System" in cypher:
            return [{"kind": s["kind"], "disc": s.get("disc", "__singleton__"),
                     "description": s.get("description")}
                    for s in self.systems]
        return []


def build_hunting_l1():
    """The fixture L1: s1 fronted by a GraphQLApi System, s3 fronted by a
    RESTApi System, plus the two Systems themselves (kind-qualified singleton
    identities, the projection reader's convention)."""
    return _HuntingL1(
        services=[{"slug": "s1"}, {"slug": "s3"}],
        systems=[{"kind": "GraphQLApi", "disc": "__singleton__"},
                 {"kind": "RESTApi", "disc": "__singleton__"}],
        units={
            "Service:s1": {"labels": ["L1Service"],
                           "props": {"business_function_slug": "s1",
                                     "exposure": "public"},
                           "edges": [{"family": "EXPOSED_VIA",
                                      "tlabels": ["L1System"],
                                      "tprops": {"kind": "GraphQLApi"},
                                      "rprops": {}}]},
            "Service:s3": {"labels": ["L1Service"],
                           "props": {"business_function_slug": "s3"},
                           "edges": [{"family": "EXPOSED_VIA",
                                      "tlabels": ["L1System"],
                                      "tprops": {"kind": "RESTApi"},
                                      "rprops": {}}]},
            "GraphQLApi:__singleton__": {"labels": ["L1System"],
                                         "props": {"kind": "GraphQLApi",
                                                   "discriminator": "__singleton__"},
                                         "edges": []},
            "RESTApi:__singleton__": {"labels": ["L1System"],
                                      "props": {"kind": "RESTApi",
                                                "discriminator": "__singleton__"},
                                      "edges": []},
        },
    )


# --- the threat modeller fixtures (T2, #375; the shared worked example) -------

def _evidence(ref: str = "GET /catalogue") -> dict:
    return {"kind": "request", "ref": ref}


def modeller_gate_payloads() -> dict:
    """The five gate payloads, the minimum the completion checker needs.

    The literal content is the T1 fixture shape (a known-good worked example),
    never derived from the code under test. Single home: the modeller's pass
    tests and the runtime wiring tests drive the SAME example."""
    from polymerhus.attack.hunting.threat_model import ModelState

    return {
        ModelState.UNIT_TECHNICAL_SHARP: {
            "technical_sharpening": {
                "interface_agreements": [{
                    "id": "ia-1",
                    "statement": "The catalogue endpoint reads the item id from the query.",
                    "confidence": "OBSERVED",
                    "evidences": [_evidence()],
                }],
                "control_flows": [{
                    "id": "cf-1",
                    "statement": "The handler authorises before the lookup.",
                    "confidence": "INFERRED",
                    "evidences": [_evidence("framework default")],
                }],
                "data_flows": [{
                    "id": "df-1",
                    "statement": "The item body is rendered into the product page.",
                    "confidence": "OBSERVED",
                    "evidences": [_evidence()],
                }],
            },
        },
        ModelState.TRUST_MODELLED: {
            "trust_model": {
                "trust_agreements": [{
                    "id": "ta-1",
                    "boundary": "anonymous caller -> catalogue lookup",
                    "interface_agreement_refs": ["ia-1"],
                    "statement": "The lookup trusts the caller's item id.",
                    "confidence": "INFERRED",
                    "evidences": [_evidence()],
                }],
                "dynamic_state_trust": {
                    "states": [{
                        "id": "ds-1",
                        "variables": ["item_id"],
                        "confidence": "OBSERVED",
                        "evidences": [_evidence()],
                    }],
                    "transitions": [{
                        "id": "tr-1",
                        "source": "ds-1",
                        "target": "ds-1",
                        "guard": "any item id",
                        "confidence": "INFERRED",
                        "evidences": [_evidence()],
                    }],
                    "violations": [{
                        "id": "vi-1",
                        "kind": "trust-transition",
                        "statement": "A caller can force the state before the owner check.",
                        "maps_to_fault": "fault-1",
                        "transition_ref": "tr-1",
                        "confidence": "ASSUMED",
                        "evidences": [_evidence()],
                    }],
                },
            },
        },
        ModelState.TRUST_ASSUMPTIONS_WRITTEN: {
            "assumptions": [{
                "id": "as-1",
                "statement": "The handler omits the ownership check.",
                "fault": {
                    "id": "fault-1",
                    "label": "improper authorisation on the item lookup",
                    "description": "The handler does not check item ownership.",
                },
                "boundary_ref": "ta-1",
                "confidence": "ASSUMED",
                "evidences": [_evidence("note:catalogue")],
            }],
        },
        ModelState.VULNERABILITIES_WRITTEN: {
            "vulnerabilities": [{
                "id": "v-1",
                "fault_ref": "fault-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "characterisation": "An anonymous caller reads another user's item.",
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
        },
        ModelState.COMPLETED: {
            "loops": [{
                "fault_ref": "fault-1",
                "vulnerability_ref": "v-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "likelihood": "high",
                "likelihood_rationale": "An anonymous caller controls the id.",
                "risk_factors": {
                    "attack_vector": "network",
                    "attack_requirements": "none",
                    "privileges_required": "none",
                    "complexity": "low",
                },
                "impact": {
                    "confidentiality": "low",
                    "integrity": "none",
                    "availability": "none",
                    "end_impact": "A caller reads another tenant's item.",
                },
                "confidence": "INFERRED",
                "evidences": [_evidence()],
            }],
        },
    }


# --- the produced-model fixtures (T4b, #387) ------------------------------------
#
# The ONE home of the produced-model ladder: a test that needs a dispatchable
# loop file drives the REAL store, never a copied per-file helper.

def produce_model(
    store,
    *,
    project_id: str,
    unit_id: str,
    run_id: str,
    loops=None,
) -> str:
    """Drive a REAL `ThreatModelStore`'s five gates to COMPLETED for `unit_id` -
    the produced COMPLETED valid model the mover dispatches from.

    The one home of the worked example's ladder (T4b #387 lifted it out of the
    per-file test helpers, so the retired-config tests could be re-pointed at the
    same produced model): `loops` overrides the COMPLETED write's loop rows
    (the sequencing fixtures). The gate payloads are a KNOWN-GOOD literal
    (`modeller_gate_payloads`), never derived from the code under test."""
    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    for state in ModelState:
        sections = dict(payloads[state])
        if state is ModelState.COMPLETED and loops is not None:
            sections["loops"] = loops
        store.write_sections(project_id, unit_id, state, sections, run_id=run_id)
    return unit_id


def loop_row(**overrides) -> dict:
    """One COMPLETED-write loop row (the shared worked example): one `high`
    loop over fault-1 / v-1. `overrides` carry the sequencing fixtures'
    likelihood (or a distinct loop's rows)."""
    row = {
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "likelihood": "high",
        "likelihood_rationale": "The item id is attacker-controlled and unauthenticated.",
        "risk_factors": {
            "attack_vector": "network",
            "attack_requirements": "none",
            "privileges_required": "none",
            "complexity": "low",
        },
        "impact": {
            "confidentiality": "low",
            "integrity": "none",
            "availability": "none",
            "end_impact": "A caller reads another tenant's item.",
        },
        "confidence": "INFERRED",
        "evidences": [{"kind": "request", "ref": "GET /catalogue?id=2"}],
    }
    row.update(overrides)
    if "impact" not in overrides:
        # Keep the fixture's combined risk aligned with its likelihood tier, so
        # a `high` loop is a high-bucket loop in the sequencing tests.
        level = {
            "low": "low", "medium": "medium", "high": "high",
            "critical": "high", "none": "none",
        }.get(str(row.get("likelihood") or "none"), "none")
        row["impact"] = {
            "confidentiality": level,
            "integrity": "none",
            "availability": "none",
            "end_impact": "A caller reads another tenant's item.",
        }
    return row


def intake_unit(unit_id: str, *, live_edges: int = 0, endpoints: int = 0):
    """One frozen intake unit (S1 7.1): the run bootstrap's `intake_units` seam.

    The counts are the run's own snapshot of the live L1 edge count and the
    aggregated endpoint count; the ordering under them is the runtime's."""
    from polymerhus.attack.hunting.unit_intake import IntakeUnit

    return IntakeUnit(
        unit_id=unit_id,
        live_edge_count=live_edges,
        endpoint_count=endpoints,
    )


def build_intake_l1(*, units=(), systems=()):
    """The T3 intake read seam fixture: serves the intake Cyphers.

    `units` are the raw unit rows (`labels`, `props`, `edge_families`,
    `endpoints`); `systems` are the System rows with the Services each is
    connected to over a live L1 edge and those Services' `AGGREGATES`
    out-degrees."""
    def read(cypher, params):
        if "AS edge_families" in cypher:
            return [dict(unit) for unit in units]
        if "AS slug" in cypher:
            return [
                {"kind": system["kind"],
                 "disc": system.get("disc", "__singleton__"),
                 "slug": service["slug"],
                 "endpoints": service.get("endpoints", 0)}
                for system in systems
                for service in system.get("services", ())
            ]
        return []

    return read


class ScriptedModellerTurns:
    """The fake modeller turn seam: each state's turn writes its gate through the
    BOUND `hunts_store` tool (never the store directly), so a test drives exactly
    what the model drives. Returns the tool responses and the turn inputs."""

    def __init__(self, states=None, payloads=None):
        from polymerhus.attack.hunting.threat_model import ModelState

        self.states = list(states if states is not None else ModelState)
        self.payloads = payloads if payloads is not None else modeller_gate_payloads()
        self.turn_inputs: list = []
        self.responses: list = []

    def store_tool(self, turn):
        return next(tool for tool in turn.tools if tool.name == "hunts_store")

    def __call__(self, turn):
        self.turn_inputs.append(turn)
        if turn.state not in self.states:
            return None
        payload = self.payloads[turn.state]
        self.responses.append(self.store_tool(turn).invoke({
            "cmd": "write", "state": turn.state.value, "sections": payload,
        }))
        return None
