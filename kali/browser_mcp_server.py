#!/usr/bin/env python3
"""Process entrypoint for the browser MCP server.

The Kali image runs this beside ``mcp_server.py``. It reads the deployment
environment, builds the pool manager and session store, and serves the three
agent tools on ``STEEL_MCP_PORT`` (default 8003) at ``/mcp``.

The flat-import fallback keeps the file valid when the image copies
``steel_pool/`` beside it rather than under ``kali/``.
"""
from __future__ import annotations

try:  # package layout
    from kali.steel_pool.server import main
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.server import main  # type: ignore[no-redef]

if __name__ == "__main__":
    raise SystemExit(main())
