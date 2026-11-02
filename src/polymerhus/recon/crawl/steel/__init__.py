"""The steel_crawl session client and its per-module siblings.

The module tree is the spec's (`docs/design/steel-crawl-spec.md` section 3.1):
`session.py` owns the catalogue, attach, the CLI envelope, and stop; `state.py`
owns the page instance, the snapshot cache, the consumed set, and ref validity.
"""
