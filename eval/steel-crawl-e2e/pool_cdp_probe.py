"""Probe the pool CDP path from the deployed agent container.

The crawl's session client mounts a browser MCP lease and the transport opens
a raw CDP socket to the worker container address with `Host: localhost:3000`.
This script is an E2E setup check, not a test assertion.
"""
from __future__ import annotations

import json
import sys

from polymerhus.recon.crawl.steel.live import LiveCdpTransport
from polymerhus.recon.crawl.steel.session import SteelSessionClient


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "convergence-cdp"
    session = SteelSessionClient.from_mcp("http://kali:8003/mcp")
    try:
        attached = session.attach(name)
        print(
            json.dumps(
                {
                    "session_id": attached.session_id,
                    "cdp_endpoint": session.cdp_endpoint,
                }
            )
        )
        transport = LiveCdpTransport(lambda: session.cdp_endpoint)
        try:
            page = transport.attach_page()
            print(json.dumps({"page": page.get("url")}))
            result = transport.send(
                "Runtime.evaluate",
                {"expression": "document.title", "returnByValue": True},
            )
            print(json.dumps({"title": result.get("result", {}).get("value")}))
        finally:
            transport.close()
    finally:
        try:
            end = session.stop()
            print(json.dumps({"end": end.__dict__}))
        finally:
            session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
