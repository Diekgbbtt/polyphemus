"""Shared state-graph-hunter fixtures (memory integration + e2e tiers).

The state-graph hunter's seams (spec 5, ADR R4): the per-project
`HunterMemoryStore`, the `hunts_store` / `notes` tool seam over it, and the
turn-by-turn ReAct host's `model_factory` (a scripted model emitting REAL tool
calls - the standard tool interface the harness binds request-only). Owned here
so the memory contract catalogue (C1-C28) and the harness-seam catalogue (H1-H6)
speak the SAME canned objects and the duplication stays in one place.
"""
from __future__ import annotations

import yaml
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
HUNT_KEY = f"{UNIT_NAME}__threat-1"


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
    """The canonical threat payload the surfer materialises at dispatch (S2 8.2,
    CVSS 4.0 spec 9) for the `(Service:slug:a, threat-1)` pair - the SAME key set
    `materialise_hunter_payload` emits. The assessment values are the worked
    example's known-good literals (`ITEM_*`), never recomputed here."""
    payload = {
        "dispatch_id": HUNT_KEY,
        "run_id": "run-1",
        "threat_id": "threat-1",
        "unit_id": UNIT_ID,
        "unit_kind": "service",
        "risk": ITEM_RISK,
        "severity_band": "critical",
        "risk_vector": ITEM_VECTOR,
        "factors": dict(ITEM_FACTORS),
        "impact_description": IMPACT_DESCRIPTION,
        "exploitability_description": EXPLOITABILITY_DESCRIPTION,
        "capability": "read another tenant's item",
        "capability_id": f"{UNIT_ID}::p-1",
        "capability_path": [],
        "enabling_precursors": [],
        "assumptions": [{
            "id": "as-1",
            "statement": "The lookup omits the ownership check.",
            "fault_ref": "fault-1",
            "boundary_ref": "ta-1",
            "confidence": "ASSUMED",
            "evidence_refs": ["note:catalogue"],
        }],
        "threat": {
            "id": "threat-1",
            "fault_ref": "fault-1",
            "vulnerability_ref": "v-1",
            "canonical_class": "IDOR",
            "web_vulnerability_class": "idor",
            "impact_ref": "ia-1",
            "enabling_precursors": [],
            "risk": ITEM_RISK,
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
        "vulnerability_rationale": "An anonymous caller reads another user's item.",
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

# The worked example's assessment factors (schema 5): a full-record read from
# an unauthenticated network caller, no defence to beat. `ITEM_RISK` and
# `ITEM_VECTOR` are the `cvss==3.6` CVSS 4.0 values for those factors
# (`AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N` = 9.2); they are
# known-good literals, never recomputed by the tests.
ITEM_FACTORS = {
    "attack_vector": "network",
    "attack_complexity": "low",
    "attack_requirements": "none",
    "privileges_required": "none",
    "user_interaction": "none",
    "confidentiality": "high",
    "integrity": "none",
    "availability": "none",
}
ITEM_RISK = 9.2
ITEM_VECTOR = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:H/SI:N/SA:N"


def _evidence(ref: str = "GET /catalogue") -> dict:
    return {"kind": "request", "ref": ref}


def modeller_gate_payloads() -> dict:
    """The gate payloads, the minimum the completion checker needs.

    The literal content is the T1 fixture shape (a known-good worked example),
    never derived from the code under test. Single home: the modeller's pass
    tests, the runtime wiring tests, and the mover fixtures drive the SAME
    example. The worked example's ONE high-scoring threat references the ONE
    scored assessment row (`ia-1`) that `assessment_args` builds.

    The `IMPACT_ASSESSED` payload is the `assess_impact` ARGS, never a
    `hunts_store` section: schema 5's store surface carries no assessment
    section, because the `assess_impact` tool (ticket #407) is that row's sole
    writer and the persistence derives the score from the factors.
    """
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
                    "statement": "The request handler authorises before the lookup.",
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
        ModelState.PRIOR_ART: {
            "prior_art": {
                # One query per kind the completion check requires (ticket 437):
                # threat, vulnerability, precursor - each with at least one
                # filter - plus the phase note.
                "queries": [
                    {
                        "kind": "precursor",
                        "filters": [{
                            "path": "capability",
                            "regex": "session|item",
                            "flags": "i",
                        }],
                        "result_count": 2,
                    },
                    {
                        "kind": "threat",
                        "filters": [{
                            "path": "threat.web_vulnerability_class",
                            "regex": "session-management",
                            "flags": "i",
                        }],
                        "result_count": 0,
                    },
                    {
                        "kind": "vulnerability",
                        "filters": [{
                            "path": "canonical_class",
                            "regex": "credential",
                            "flags": "i",
                        }],
                        "result_count": 0,
                    },
                ],
                "reused": [{
                    "unit_id": "Service:sign-in",
                    "record_id": "p-2",
                    "kind": "precursor",
                    "reason": "the item-read capability applies to the lookup surface",
                }],
                "notes": "No prior threat matched the item read.",
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
        # The `assess_impact` tool's args own this gate's content (ticket #407).
        ModelState.IMPACT_ASSESSED: assessment_args(),
        ModelState.COMPLETED: {
            "threats": [{
                "fault_ref": "fault-1",
                "vulnerability_ref": "v-1",
                "canonical_class": "IDOR",
                "web_vulnerability_class": "idor",
                "impact_ref": "ia-1",
                "enabling_precursors": [],
                "evidences": [_evidence()],
            }],
        },
    }


# The worked example's one damage claim: the victim is the tenant user, the
# property is the confidentiality of the persisted item data (S2 section 2).
IMPACT_DESCRIPTION = (
    "An anonymous caller reads another tenant's item from the catalogue "
    "database."
)
EXPLOITABILITY_DESCRIPTION = (
    "One unauthenticated request names the item id; no defence stands between "
    "the caller and the lookup, and no victim action is needed."
)


def _assessment_row(index: int = 1, *, risk: float = ITEM_RISK) -> dict:
    return {
        "id": f"ia-{index}",
        "vulnerability_ref": "v-1",
        "disposition": "threat",
        "impact_description": IMPACT_DESCRIPTION,
        "exploitability_description": EXPLOITABILITY_DESCRIPTION,
        "capability": "read another tenant's item",
        "capability_id": f"p-{index}",
        "capability_path": [],
        "evidence_refs": ["GET /catalogue?id=2"],
        "factors": dict(ITEM_FACTORS),
        "risk": risk,
        "risk_vector": ITEM_VECTOR,
    }


def assessment_args(index: int = 1) -> dict:
    """The `assess_impact` ARGS of the worked example's row `index`.

    The derived `risk` and `risk_vector` are dropped: the tool's contract refuses
    both, and the persistence computes them from the authored factors.
    """
    return {
        key: value
        for key, value in _assessment_row(index).items()
        if key not in ("risk", "risk_vector")
    }


def write_gate(surface, state, *, payload=None):
    """Write ONE gate through the BOUND tools.

    The assessment rows have ONE writer, `assess_impact`; every other gate goes
    through `hunts_store`. An EMPTY assessment payload writes nothing, for the
    fixture whose model carries no row at all. `payload` defaults to the worked
    example's content for that gate.
    """
    from polymerhus.attack.hunting.threat_model import ModelState

    content = (
        modeller_gate_payloads()[state] if payload is None else payload)
    if state is ModelState.IMPACT_ASSESSED:
        if not content:
            return None
        return surface["assess_impact"].invoke(dict(content))
    return surface["hunts_store"].invoke({
        "cmd": "write", "state": state.value, "sections": content})


def _coherent_threats(threats):
    """Renumber the supplied threat rows onto their OWN assessment rows (the
    one-threat-one-assessment rule): threat i references `ia-<i>` and `p-<i>`,
    so a fan-out fixture stays a valid COMPLETED model."""
    return [
        {
            **row,
            "impact_ref": f"ia-{index}",
            "enabling_precursors": [],
        }
        for index, row in enumerate(threats, start=1)
    ]


def _seed_assessments(path, rows) -> None:
    """Seed the assessment section of one produced model document.

    The `assess_impact` tool (ticket #406) is the sole writer of a schema-5
    assessment row, through `ThreatModelStore.write_impact_assessment`. This
    fixture seeds the document directly instead, because the worked example's
    fan-out declares its own risk tiers and the real write DERIVES the score
    from the factors. Every other gate, the COMPLETED write, the ranking, and
    the checker still run through the real store.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["state"] = "IMPACT_ASSESSED"
    document["impact_assessment"] = rows
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


# --- the produced-model fixtures (T4b, #387) ------------------------------------
#
# The ONE home of the produced-model ladder: a test that needs a dispatchable
# threat file drives the REAL store, never a copied per-file helper.

def produce_model(
    store,
    *,
    project_id: str,
    unit_id: str,
    run_id: str,
    threats=None,
) -> str:
    """Drive a REAL `ThreatModelStore`'s seven gates to COMPLETED for `unit_id` -
    the produced COMPLETED valid model the mover dispatches from.

    The one home of the worked example's ladder (T4b #387 lifted it out of the
    per-file test helpers, so the retired-config tests could be re-pointed at the
    same produced model): `threats` overrides the COMPLETED write's threat rows
    (the sequencing fan-out fixtures) and the assessment rows are derived per
    threat, so every fan-out row keeps its own claim. The `IMPACT_ASSESSED`
    content is seeded as the `assess_impact` tool will write it (ticket #406);
    every other gate and the COMPLETED commit run through the real store. The
    gate payloads are a KNOWN-GOOD literal (`modeller_gate_payloads`), never
    derived from the code under test."""
    payloads = modeller_gate_payloads()
    from polymerhus.attack.hunting.threat_model import ModelState

    rows = _coherent_threats(threats) if threats is not None else None
    path = None
    for state in ModelState:
        if state is ModelState.IMPACT_ASSESSED:
            # The rows a fan-out declares (each carrying its own score), else
            # the worked example's one row.
            assessment_rows = (
                [
                    _assessment_row(index, risk=float(row.get("risk", ITEM_RISK)))
                    for index, row in enumerate(rows, start=1)
                ]
                if rows is not None else [_assessment_row()]
            )
            _seed_assessments(path, assessment_rows)
            continue
        sections = dict(payloads[state])
        if state is ModelState.COMPLETED and rows is not None:
            # The model's write shape: no authored score.
            sections["threats"] = [
                {key: value for key, value in row.items() if key != "risk"}
                for row in rows
            ]
        path = store.write_sections(
            project_id, unit_id, state, sections, run_id=run_id)
    return unit_id


def threat_row(**overrides) -> dict:
    """One COMPLETED-write threat row (the shared worked example): one
    high-scoring threat over fault-1 / v-1 that references the worked example's
    `ia-1` row. `overrides` carry the sequencing fixtures' distinct rows;
    `produce_model` renumbers a fan-out onto its own rows."""
    row = {
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "canonical_class": "IDOR",
        "web_vulnerability_class": "idor",
        "impact_ref": "ia-1",
        "enabling_precursors": [],
        "evidences": [{"kind": "request", "ref": "GET /catalogue?id=2"}],
    }
    row.update(overrides)
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
    BOUND tools (never the store directly), so a test drives exactly what the
    model drives - `hunts_store` for every gate, `assess_impact` for the
    assessment rows. Returns the tool responses and the turn inputs."""

    def __init__(self, states=None, payloads=None):
        from polymerhus.attack.hunting.threat_model import ModelState

        self.states = list(states if states is not None else ModelState)
        # `payloads` OVERRIDES the worked example's gate payloads (one gate's
        # override, never a replacement of the other gates), so a test that
        # rewrites the COMPLETED write still drives the full ladder.
        self.payloads = {
            **modeller_gate_payloads(), **(payloads if payloads is not None else {}),
        }
        self.turn_inputs: list = []
        self.responses: list = []

    def store_tool(self, turn):
        return next(tool for tool in turn.tools if tool.name == "hunts_store")

    def write_gate(self, turn, state):
        """One gate through the BOUND tools: the assessment row through
        `assess_impact`, every other gate through `hunts_store`."""
        return write_gate({tool.name: tool for tool in turn.tools}, state,
                          payload=self.payloads[state])

    def __call__(self, turn):
        self.turn_inputs.append(turn)
        if turn.phase == "WELLFORMEDNESS":
            notes = next(tool for tool in turn.tools if tool.name == "notes")
            notes.invoke({
                "cmd": "write", "option": "append",
                "note_name": "wellformedness", "kind": "wellformedness",
                "body": "every threat checked; no new assumption",
            })
            # The well-formedness note is the phase exit; PRIOR_ART and
            # IMPACT_ASSESSED follow as their own turns.
            return None
        if turn.state not in self.states:
            return None
        response = self.write_gate(turn, turn.state)
        if response is not None:
            self.responses.append(response)
        return None
