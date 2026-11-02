"""The passive raw-CDP capture: flow records, the body store, and the sidecar.

The module tree is the spec's (`docs/design/steel-crawl-spec.md` section 3.1):
`flow.py` owns the frozen flow record and the digest-keyed body store;
`sidecar.py` owns the attach, the event pump, and the page/action correlation.
"""
