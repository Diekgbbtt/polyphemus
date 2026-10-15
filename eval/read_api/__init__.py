"""The eval read API (#278): a read-only report over the materialized store.

`projection` turns the authoritative trial trees
`<artifact_store>/<target_id>/<target_run_id>/<trial_id>/` into a JSON snapshot;
`app` is the thin FastAPI that serves `GET /snapshot` and `GET /health`.
Import performs no I/O (CODING_STANDARD section 6).
"""
