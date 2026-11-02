"""The policy: the protocol, the prompt contract, and the choice validation.

The module tree is the spec's (`docs/design/steel-crawl-spec.md` section 3.1):
`port.py` owns the `Policy` protocol, the decision request and answer values, and
the two protocol errors; `prompts.py` owns the prompt contract that builds each
request. The Jev adapter (`jev.py`) is the next ticket's.
"""
