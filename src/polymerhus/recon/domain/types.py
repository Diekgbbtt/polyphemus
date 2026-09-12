# src/polymerhus/recon/domain/types.py
import operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field, model_validator

class Edge(BaseModel):
    rel: str
    dir: Literal["in", "out"]
    node_type: str
    node_identity: dict

# The per-Endpoint surface classification (D16): the ONLY values
# `Endpoint.profile` (and the `BaseURL.profile` root mirror) may hold. Typed as
# a Literal at the classifier (`classify_profile` returns it) and enforced at
# BOTH write seams: the AssetDelta construction (a delta carrying any other
# value is rejected at parse time - a programmer error, fail-loud) and the
# curator's cypher build (build_asset_cypher raises, curate skips+logs it -
# fail-open at the graph write, per the L0 sole-writer invariants).
Profile = Literal["webapp", "restapi", "graphql_api"]
PROFILE_VALUES: frozenset[str] = frozenset(Profile.__args__)


class AssetDelta(BaseModel):
    type: str
    identity: dict
    props: dict = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _profile_is_typed(self) -> "AssetDelta":
        profile = self.props.get("profile")
        if profile is not None and profile not in PROFILE_VALUES:
            raise ValueError(
                f"invalid {self.type} profile {profile!r}; must be one of "
                f"{sorted(PROFILE_VALUES)}"
            )
        return self

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
    # #196: additive capture metadata. Defaults keep every existing fake and
    # caller working unchanged.
    exec_id: str = ""
    http_artifact_refs: list[str] = Field(default_factory=list)
    capture_warning: str | None = None


class CaptureContext(BaseModel):
    """The runtime correlation metadata carried from the pod to Kali.

    Runtime metadata, never a hunter-spec validation schema: it names the
    project/run/spec/variant a terminal call belongs to so the captured HTTP
    artifacts can be linked back to the D6 observation that caused them.
    """

    project_id: str = ""
    run_id: str = ""
    spec_id: str = ""
    variant_ref: str = ""
    session_id: str = ""

    def as_mcp_args(self) -> dict:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "spec_id": self.spec_id,
            "variant_ref": self.variant_ref,
        }

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
    # #208 one-pod reprofile (D16 per-endpoint split, superseded dispatch): this
    # job re-probes the Endpoint population to stamp each Endpoint's own
    # `profile`. Its probe SET is prepared by
    # `batching.prepare_endpoint_profile_assets` (dedup dynamic routes +
    # materialise a root `/` per BaseURL) and packed into ONE pod_input by the
    # `endpoint_profiling` preprocess branch - the pass dispatches exactly one
    # pod regardless of endpoint count, paying O(1) triager turns per job.
    endpoint_profiling: bool = False
    # D16 per-endpoint split: this job (kiterunner) fuzzes under an evidence-
    # derived API-root prefix. Its input Endpoints (profile==restapi) are grouped
    # per host and collapsed to scan-target prefixes by
    # `batching.build_api_scope_assets` (via `api_scope.derive_scan_targets`).
    api_scope: bool = False
    use_auth: bool = False
    configurator_mode: Literal["deterministic", "agent"] = "deterministic"
    eval_criteria: str = "returncode_zero_nonempty"

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
