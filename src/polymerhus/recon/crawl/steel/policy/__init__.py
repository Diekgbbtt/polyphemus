"""The policy: the protocol, the prompt contract, and the Jev adapter.

The module tree is the spec's (`docs/design/steel-crawl-spec.md` section 3.1):
`port.py` owns the `Policy` protocol, the decision request and answer values, and
the two protocol errors; `prompts.py` owns the prompt contract that builds each
request; `jev.py` owns the synchronous decision-client port, the TypeSafe
sync-over-async bridge, the `JevPolicy`, and the provider failure.
"""
