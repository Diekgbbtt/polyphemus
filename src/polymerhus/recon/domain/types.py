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

class JobSpec(BaseModel):
    tool: str
    skill: str
    command_template: str
    produces: list[str]
    consumes: str
    consumes_where: AssetSelector | None = None
    batch: bool = False
    # D16 per-endpoint split: this job re-probes the Endpoint population to
    # stamp each Endpoint's own `profile`. Its input set is prepared by
    # `batching.prepare_endpoint_profile_assets` (dedup dynamic routes +
    # materialise a root `/` per BaseURL), mirroring how `batch` gates jsluice's
    # `build_batch_assets`.
    endpoint_profiling: bool = False
    use_auth: bool = False
    configurator_mode: Literal["deterministic", "agent"] = "deterministic"
    eval_criteria: str = "returncode_zero_nonempty"

class PodExport(BaseModel):
    input_asset: dict
    verdict: Literal["success", "failed"]
    assets_merged: int = 0
    observations_merged: int = 0
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
