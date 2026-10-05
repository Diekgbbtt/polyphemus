"""The operator-only ground-truth API (separate from the shared read API).

This package serves the benchmark reference an operator sees beside a Trial's
verdicts. It is deliberately not part of `read_api`: it reads a different
source (the benchmark checkout), and the discovery agent must never reach it.
"""
