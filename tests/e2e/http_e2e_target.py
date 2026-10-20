"""Deterministic local HTTP target for the #196 live end-to-end gate.

The target deliberately reflects only non-sensitive markers so the test can
prove capture/replay semantics without pushing cookie or authorization values
into response bodies, sanitized MCP views, or Langfuse-visible output.
"""
from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit


WHITE_JOTTER_SESSION_COOKIE = "wj-session"
WHITE_JOTTER_DEFAULT_USER = "admin"
WHITE_JOTTER_DEFAULT_PASSWORD = "123"


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
        if urlsplit(self.path).path in (
            "/api/authentication", "/api/admin/user", "/api/logout",
        ):
            self._white_jotter_get()
            return
        self._reply()

    def do_HEAD(self) -> None:  # noqa: N802
        self._reply(write_body=False)

    def do_POST(self) -> None:  # noqa: N802
        # The replay-lineage gate needs a CAPTURED request body: only captured
        # bytes are replayable, and the body marker proves the replay kept them.
        # GET stays the documented 5-line body; the echo exists only here.
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        if urlsplit(self.path).path == "/api/login":
            self._white_jotter_login(body)
            return
        self._reply(request_body=body.replace("\r", "").replace("\n", ""))

    def _white_jotter_login(self, body: str) -> None:
        """The white-jotter-001 sample surface: `admin`/`123` is accepted.

        The ground truth is
        `/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/white-jotter/white-jotter-001`.
        The wrong-password control returns `code:400`; the default pair
        returns `code:200` and mints the session cookie.
        """
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {}
        username = payload.get("username")
        password = payload.get("password")
        if (username == WHITE_JOTTER_DEFAULT_USER
                and password == WHITE_JOTTER_DEFAULT_PASSWORD):
            self._json_reply(
                200,
                {"code": 200, "message": "登录成功", "result": username},
                cookie=f"{WHITE_JOTTER_SESSION_COOKIE}={username}; Path=/; HttpOnly",
            )
            return
        self._json_reply(200, {"code": 400, "message": "密码错误", "result": None})

    def _white_jotter_get(self) -> None:
        path = urlsplit(self.path).path
        session = _cookie_value(
            self.headers.get("Cookie", ""), WHITE_JOTTER_SESSION_COOKIE)
        authenticated = session == WHITE_JOTTER_DEFAULT_USER
        if path == "/api/logout":
            self._json_reply(
                200,
                {"code": 200, "message": "成功登出", "result": None},
                cookie=f"{WHITE_JOTTER_SESSION_COOKIE}=; Path=/; Max-Age=0",
            )
            return
        if path == "/api/authentication":
            if authenticated:
                self._text_reply(200, "身份认证成功")
            else:
                self._json_reply(401, {"code": 401, "message": "未认证", "result": None})
            return
        if path == "/api/admin/user":
            if not authenticated:
                self._json_reply(401, {"code": 401, "message": "未认证", "result": None})
                return
            self._json_reply(200, {
                "code": 200,
                "message": "查询成功",
                "result": [{
                    "id": 1,
                    "username": WHITE_JOTTER_DEFAULT_USER,
                    "name": "Administrator",
                    "enabled": True,
                    "roles": [{"id": 1, "name": "admin", "nameZh": "管理员"}],
                }],
            })
            return

    def _json_reply(self, status: int, payload: dict, *, cookie: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _text_reply(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
