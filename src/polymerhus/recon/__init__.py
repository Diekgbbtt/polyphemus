"""Recon - the Layer-0 (observed) bounded context.

Public interface of the context is deliberately slim: `run_pipeline`, the one
entry point the operator surface (project_management) launches. It is exposed
lazily (PEP 562) so `import polymerhus.recon` performs no heavy import and can
never cycle with the control-layer modules that read `polymerhus.recon.config`
at load time.

Internal layering:
- `recon.control`  - the impure orchestration layer (pipeline, jobs, job_agent,
  orchestrator_agent, auth, batching, async_bridge, scope, steering, targeted):
  it decides *when and whether* to run.
- `recon.domain`   - the model and the L0 sole-writer (curator, types, findings,
  pod, graph_read, selectors, noise_filter, skills, parsers): pure where possible.
- `recon.crawl`    - the agentic-crawl subpackage.
"""
from __future__ import annotations

__all__ = ["run_pipeline"]


def __getattr__(name: str):
    if name == "run_pipeline":
        from polymerhus.recon.control.pipeline import run_pipeline
        return run_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
