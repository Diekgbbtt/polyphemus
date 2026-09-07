# src/polymerhus/recon/domain/types.py
import operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field

class Edge(BaseModel):
    rel: str
    dir: Literal["in", "out"]
    node_type: str
    node_identity: dict

class AssetDelta(BaseModel):
    type: str
    identity: dict
    props: dict = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

class Observation(BaseModel):
    macro_kind: str
    severity: str
    evidence: str
    rationale: str
    anchor: dict            # {"type": str, "identity": dict}
    source_job: str
    source_tool: str

class ExecResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int = 0

class ToolInvocation(BaseModel):
    command: str
    session_id: str

class AssetSelector(BaseModel):
    """Declarative, pure predicate over a read-back asset's identity/prop dict.

    A `JobSpec.consumes_where` narrows a job's input population beyond the bare
    `consumes` label: e.g. jsluice consumes `Endpoint` but only wants the JS
    bundles, expressed as `field="path", op="ends_with", values=[".js",".mjs"]`.
    Kept a data structure (not a callable) so a JobSpec stays a plain model and
    the matching logic lives in one pure, testable place (`selectors.py`)."""
    field: str
    op: Literal["ends_with", "starts_with", "equals", "contains"] = "ends_with"
    values: list[str]

class ConsumptionOptions(BaseModel):
    """How a job's input population derives into pod inputs (#37, option B).

    The single declaration the unified derivation
    (`batching.derive_consumption_set`) interprets - replacing the accreted
    per-job booleans with one composed pipeline: malformed-path exclusion,
    route-cluster dedup (+ optional root `/` materialisation and
    already-profiled skip), restapi-first ordering, then pack into pod inputs.
    All False / `pack="none"` is the plain-job no-op (raw 1:1 assets).
    """
    route_dedup: bool = False
    # `materialise_root` / `skip_profiled` ride the `route_dedup` stage: set
    # alone (without `route_dedup`) they are inert - the seam never materialises
    # or skips outside the dedup pass.
    materialise_root: bool = False
    skip_profiled: bool = False
    drop_malformed: bool = False
    order_restapi_first: bool = False
    pack: Literal["none", "batches", "one_pod", "scan_targets"] = "none"


class JobSpec(BaseModel):
    tool: str
    skill: str
    command_template: str
    produces: list[str]
    consumes: str
    consumes_where: AssetSelector | None = None
    # #37 option B: `consumption` is the SINGLE declaration of how this job's
    # input population derives into pod inputs. The legacy per-job flags below
    # are read-only VIEWS over it (kept so the pod command builder and the
    # pipeline phase planner, which switch on dispatch shape rather than
    # input-set derivation, keep working unchanged).
    consumption: ConsumptionOptions = Field(default_factory=ConsumptionOptions)
    use_auth: bool = False
    configurator_mode: Literal["deterministic", "agent"] = "deterministic"
    eval_criteria: str = "returncode_zero_nonempty"

    # --- legacy dispatch-shape views (#37 option B) ---------------------------
    # Read-only views over `consumption.pack` for the seams that switch on the
    # pod DISPATCH shape (the pod command builder, the pipeline phase planner)
    # rather than on input-set derivation. New code reads `consumption`.
    @property
    def batch(self) -> bool:
        """True when this job packs bundles into batch pods (jsluice)."""
        return self.consumption.pack == "batches"

    @property
    def endpoint_profiling(self) -> bool:
        """True when this job packs its probe set into ONE pod (#208)."""
        return self.consumption.pack == "one_pod"

    @property
    def api_scope(self) -> bool:
        """True when this job collapses endpoints to scan targets (kiterunner)."""
        return self.consumption.pack == "scan_targets"

class PodExport(BaseModel):
    input_asset: dict
    verdict: Literal["success", "failed"]
    assets_merged: int = 0
    observations_merged: int = 0
    # #74: the CURATED (post-gate, actually-merged) deltas this pod wrote, so
    # the pipeline can push them into the analysis feed as an `L0Chunk` without
    # a graph re-read. Populated by the pod's curator node; empty for a failed
    # pod (a failed pod merged nothing).
    assets: list[AssetDelta] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    iterations: int = 0
    error: str | None = None
    stats: dict | None = None

class PodState(TypedDict, total=False):
    job: JobSpec
    input_asset: dict
    asset_context: str
    extra: dict
    session_id: str
    project_id: str
    # The pod's run + phase (#94): carried so the triager node can address its STATEFUL
    # session per concurrent pod instance (PodSession). Optional - a
    # directly-invoked pod graph (tests) omits them and the triager stays stateless.
    run_id: str
    phase: int
    invocation: ToolInvocation
    exec_result: ExecResult
    iteration: int
    assets: list[AssetDelta]
    observations: list[Observation]
    export: PodExport

class ReconState(TypedDict, total=False):
    run_id: str
    project_id: str
    settings: dict
    phase_plan: list[dict]
    current_phase: int
    pod_exports: Annotated[list[PodExport], operator.add]
    status: str
