"""Deterministic local HTTP target for the #196 live end-to-end gate.

The target deliberately reflects only non-sensitive markers so the test can
prove capture/replay semantics without pushing cookie or authorization values
into response bodies, sanitized MCP views, or Langfuse-visible output.
"""
from __future__ import annotations

import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit


def _query(path: str) -> dict[str, str]:
    return {name: value for name, value in parse_qsl(urlsplit(path).query, keep_blank_values=True)}


def _cookie_value(header: str, name: str) -> str | None:
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:  # noqa: BLE001 - malformed Cookie simply fails the check
        return None
    morsel = jar.get(name)
    return morsel.value if morsel is not None else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol name
        self._reply()

    def do_HEAD(self) -> None:  # noqa: N802
        self._reply(write_body=False)

    def do_POST(self) -> None:  # noqa: N802
        # The replay-lineage gate needs a CAPTURED request body: only captured
        # bytes are replayable, and the body marker proves the replay kept them.
        # GET stays the documented 5-line body; the echo exists only here.
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        self._reply(request_body=body.replace("\r", "").replace("\n", ""))

    def _reply(
        self, *, write_body: bool = True, request_body: str | None = None
    ) -> None:
        query = _query(self.path)
        cookie_value = _cookie_value(self.headers.get("Cookie", ""), "sid")
        expected_cookie = os.environ.get("KALI_HTTP_E2E_COOKIE_VALUE", "e2e-session")
        marker = self.headers.get("X-E2E-Marker", "")
        auth_present = "1" if self.headers.get("Authorization") else "0"
        cookie_ok = "1" if cookie_value == expected_cookie else "0"
        lines = [
            f"marker={marker}",
            f"query_q={query.get('q', '')}",
            f"query_stable={query.get('stable', '')}",
            f"cookie_ok={cookie_ok}",
            f"auth_header_present={auth_present}",
        ]
        if request_body is not None:
            lines.append(f"body_marker={request_body}")
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-E2E-Target", "http-e2e-target")
        self.end_headers()
        if write_body:
            self.wfile.write(payload)

    def log_message(self, _format: str, *args) -> None:
        pass


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
