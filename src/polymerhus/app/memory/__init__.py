"""Shared memory primitives for the per-project memory stores (the hunting lift).

A shared kernel (see `CONTEXT-MAP.md`): the bounded whole-file store mechanics,
the notes-tool binding contract, and the coded teaching rejection that the
hunting stores and the analysis stores both build on. Import the submodule you
need (`bounds`, `store`, `tool_contract`); this package re-exports nothing, so
importing `bounds` does not pull the langchain-backed tool contract.

This package imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
