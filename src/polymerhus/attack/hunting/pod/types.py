"""The test-executor pod's typed records (D4 in, D5 + D6 out) and its loop state.

The pod consumes the `TestImplementationSpec` (D4) via IA-3 and returns the
`{verdict, evidence}` envelope (D5 + the D6 experiment log) via IA-4 - nothing
else crosses the boundary (spec 1.5: no graph access, no store access).

The Q3-amended terminal vocabulary (operator-ratified 2026-08-04, reconciled
here 2026-08-06) replaces the per-agent spec's four-value `terminal_reason`
(which named `infeasibility-asserted`): the six values below plus the `clean`
flag and `init_validation` are what the parent HuntingAgent's deterministic
verdict derivation reads (hunting-83 contract tests C13-C17).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from pydantic import BaseModel, Field

# --- The Q3-amended terminal_reason vocabulary (D5) ----------------------------
SYMPTOM_CONFIRMED = "symptom-confirmed"
SPACE_EXHAUSTED = "space-exhausted"
TECHNICAL_INFEASIBILITY = "technical-infeasibility"
SPECIFIC_DEFENCE_PREVENTION = "specific-defence-prevention"
NO_SYMPTOM_EVIDENCE = "no-symptom-evidence"
BUDGET_TIMEOUT = "budget-timeout"

TERMINAL_REASONS = frozenset({
    SYMPTOM_CONFIRMED, SPACE_EXHAUSTED, TECHNICAL_INFEASIBILITY,
    SPECIFIC_DEFENCE_PREVENTION, NO_SYMPTOM_EVIDENCE, BUDGET_TIMEOUT,
})

# The observation classes the Triager assigns (spec 6.4 INTERPRET).
SYMPTOM_CONFIRMED_CLASS = "symptom-confirmed"
SYMPTOM_ABSENT_CLASS = "symptom-absent"
NOISE_CLASS = "noise"
INFEASIBILITY_SIGNAL_CLASS = "infeasibility-signal"


class TestImplementationSpec(BaseModel):
    """The D4 handoff (spec section 7): a core NL body over a fundamental typed
    base. The typed base (mandatory) is everything except the two NL fields
    (`rationale`, `interpretation_guidance`; D67-10). Fields default lenient so
    an INIT rejection collects violations gracefully rather than raising - the
    harness verification component (`verification.validate_spec`) is the gate."""

    # Typed base (D67-10) - the INIT schema gate ranges over these.
    target_identity: str = ""
    verification_symptoms: list[str] = Field(default_factory=list)
    testing_pattern: str = ""
    assumptions: list[str] = Field(default_factory=list)
    payload_vector_space: dict = Field(default_factory=dict)
    # NL core (D67-10) - not part of the mandatory typed base.
    rationale: str = ""
    interpretation_guidance: str = ""
    # Variant lineage (D67-08): a derived variant records its parent + why.
    parent_spec_ref: str | None = None
    provenance: dict = Field(default_factory=dict)


class ProbeStep(BaseModel):
    """One tool call in a test's chain: a dependency/setup call or the core
    payload-carrying call. A test is a CHAIN (operator, 2026-08-06), never a
    single request - the `core` call carries the agent-authored testing
    payload; the dependency calls set up state (a session, a token)."""

    role: Literal["dependency", "core"] = "core"
    method: str = "GET"
    url: str = ""
    headers: dict = Field(default_factory=dict)
    body: str = ""
    command: str = ""  # a raw terminal command (exec tool) when method/url is not used


class ProbeChain(BaseModel):
    """The next probe the Runner authors (spec 6.4 PROBE): the ordered
    dependency calls plus the one core payload call, carried against the current
    variant. `signature` is the dedup key (O7/C10) over `(variant_ref, payload)`."""

    variant_ref: str
    steps: list[ProbeStep] = Field(default_factory=list)
    signature: str = ""


class RawObservation(BaseModel):
    """One raw tool output, preserved verbatim (D6). An empty body (O6) or an
    unclassifiable output (O8) is still recorded raw - the trail is honest."""

    probe_ref: str = ""
    variant_ref: str = ""
    request: dict = Field(default_factory=dict)
    status: int | None = None
    headers: dict = Field(default_factory=dict)
    body: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    duration_ms: int = 0


class KbObservation(BaseModel):
    """One KB-retrieve response recorded into the D6 trail (T3/#179): the
    query, the fault/axis join-key context, the returned symptoms/techniques/
    source bundle, and the variant it drove. A first-class typed record
    DISTINCT from an exec `RawObservation` - it captures which KB knowledge
    informed a probe's concretization (the spec's KB-recording work item)."""

    variant_ref: str = ""
    query: str = ""
    fault_id: str = ""
    technological_axis: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list)
    source: str | None = None


class Interpretation(BaseModel):
    """One Triager classification (D6). NL notes the parent's feedback rides on
    (hunting-83: `interpretations` are pure NL, no per-variant machine outcome)."""

    variant: str = ""
    classification: str = ""
    note: str = ""


class VariantSpec(BaseModel):
    """A derived variant spec instance with provenance (D67-08). Recorded in the
    experiment log so the parent has the full lineage."""

    ref: str
    parent_ref: str | None = None
    declined_attribute: str = ""
    spec: dict = Field(default_factory=dict)


class PodExport(BaseModel):
    """The full pod result: D5 (`verdict`, `terminal_reason`, `iterations`,
    `clean`, `init_validation`) + the D6 experiment log (`variant_specs`,
    `raw_observations`, `interpretations`). `to_envelope` renders the exact IA-4
    shape the parent HuntingAgent consumes."""

    verdict: Literal["successful", "unsuccessful"] = "unsuccessful"
    terminal_reason: str = NO_SYMPTOM_EVIDENCE
    iterations: int = 0
    clean: bool = False
    init_validation: list[str] = Field(default_factory=list)
    variant_specs: list[dict] = Field(default_factory=list)
    raw_observations: list[dict] = Field(default_factory=list)
    interpretations: list[dict] = Field(default_factory=list)
    error: str | None = None

    def to_envelope(self) -> dict:
        """The IA-4 return shape: `{verdict, evidence:{...}}`. `evidence` carries
        the D5 fields the parent's derivation reads plus the full D6 log."""
        evidence: dict[str, Any] = {
            "terminal_reason": self.terminal_reason,
            "iterations": self.iterations,
            "clean": self.clean,
            "interpretations": self.interpretations,
            "init_validation": self.init_validation,
            "variant_specs": self.variant_specs,
            "raw_observations": self.raw_observations,
        }
        if self.error:
            evidence["error"] = self.error
        return {"verdict": self.verdict, "evidence": evidence}


class RunnerStep(BaseModel):
    """One turn of the Runner's agentic loop over a probe stretch (the runner is
    the control plane of that stretch). The runner either proposes the next tool
    call (adjusting the kill chain in light of the intra-chain data flow it can
    now see) or concludes the stretch. `conclude` carries the runner's own
    signals: an INIT-gate infeasibility (assumptions unverifiable), an exhaustion
    (no new probe derivable), or a plain "I have an observation to judge"."""

    thought: str = ""
    action: Literal["tool_call", "conclude"] = "conclude"
    tool: Literal["exec", ""] = ""
    command: str = ""          # the terminal command (curl, an installed tool, ...)
    kb_query: str = ""         # (retired) the symptom-technique KB query; kept for schema compat
    # conclude-only signals:
    infeasible: bool = False
    unverified: list[str] = Field(default_factory=list)
    exhausted: bool = False
    observation_note: str = ""


class PodState(TypedDict, total=False):
    """The LangGraph loop state. Injected side-effecting collaborators
    (runner/triager/exec/kb) read and extend it; the terminal node renders the
    `PodExport`. The D6 experiment log lives on the `log` object
    (`context.ExperimentLog`), mutated in place across nodes. The two message
    channels are typed `BaseMessage` lists merged by LangChain `add_messages`
    (D84-4): every node deposits ONLY its turn's appended messages (never the
    full replacement list), and identical (role, content) messages carry the
    same deterministic id, so the reducer dedups them in place. The seams still
    receive the CURATED DICT views converted at the node boundary."""

    spec: dict            # the current variant's spec dict (D4-shaped)
    root_spec: dict       # the original D4 as received
    run_id: str
    log: Any              # context.ExperimentLog (the D6 trail + dedup ledger)
    init_validation: list[str]
    iteration: int        # outer actor-critic lap counter (one per stretch)
    current_variant_ref: str
    feedback: str         # Triager -> Runner declination
    runner_messages: Annotated[list[BaseMessage], add_messages]
    triager_messages: Annotated[list[BaseMessage], add_messages]
    tool_calls: int        # the INNER stretch counter (harness-capped)
    pending_step: dict     # the RunnerStep the runner proposed this turn
    stretch_obs: int       # observations recorded in the current stretch
    last_observation: dict
    decision: dict         # the Triager's per-lap decision
    verdict: str
    terminal_reason: str
    clean: bool
    error: str
    export: dict          # the rendered IA-4 envelope
