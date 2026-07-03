# agent/recon/types.py
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

class JobSpec(BaseModel):
    tool: str
    skill: str
    command_template: str
    produces: list[str]
    consumes: str
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

class PodState(TypedDict, total=False):
    job: JobSpec
    input_asset: dict
    asset_context: str
    extra: dict
    session_id: str
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
