"""A deterministic WAF *challenge* front for the #196 e2e fixtures.

ModSecurity (the other fixture) produces a BLOCK: a 403 with the engine's
action page. Real CDN WAFs additionally serve a *challenge*: an interstitial
with vendor markers (`cf-ray`, `cf-mitigated: challenge`) that a naive client -
or a naive parser - reads as an ordinary application page.

This shim reproduces that shape on purpose, so the capture plane and the
interpretation path can be tested against it deterministically:

* no `cf_clearance` cookie  -> 403 + interstitial + vendor-style markers;
* with the cookie           -> the request is proxied to the real target.

The cookie is the control group: same request, same fixture, challenge OFF.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BACKEND = os.environ.get("BACKEND", "http://http-e2e-target:80")
COOKIE = os.environ.get("CHALLENGE_COOKIE", "cf_clearance")
RAY = os.environ.get("CHALLENGE_RAY", "8f2c1d4e6a7b9c0d-FRA")

INTERSTITIAL = (
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
    "<h1>Checking your browser before accessing soupmarket.shop</h1>"
    "<p>This process is automatic. Your browser will redirect shortly.</p>"
    "<div id=\"cf-challenge-running\">Verifying you are human</div>"
    "</body></html>"
).encode("utf-8")


def _has_clearance(header: str) -> bool:
    return any(part.split("=", 1)[0].strip() == COOKIE for part in (header or "").split(";"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol name
        self._handle(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(body=False)

    def _handle(self, *, body: bool) -> None:
        cookie_header = self.headers.get("Cookie", "")
        if not _has_clearance(cookie_header):
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=UTF-8")
            self.send_header("Content-Length", str(len(INTERSTITIAL)))
            self.send_header("Server", "cloudflare")
            self.send_header("cf-ray", RAY)
            self.send_header("cf-mitigated", "challenge")
            self.end_headers()
            if body:
                self.wfile.write(INTERSTITIAL)
            return
        try:
            with urllib.request.urlopen(f"{BACKEND}{self.path}", timeout=5) as upstream:
                payload = upstream.read()
                self.send_response(upstream.status)
                self.send_header("Content-Type", upstream.headers.get("Content-Type", "text/plain"))
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if body:
                    self.wfile.write(payload)
        except (urllib.error.URLError, OSError) as exc:
            self.send_response(502)
            detail = f"upstream unavailable: {exc}".encode()
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(detail)))
            self.end_headers()
            if body:
                self.wfile.write(detail)

    def log_message(self, _format: str, *args) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "80"))), Handler).serve_forever()
