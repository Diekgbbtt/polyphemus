"""Duck-typed stand-ins for mitmproxy's HTTPFlow (no mitmproxy import)."""
from __future__ import annotations


class FakeHeaders:
    def __init__(self, pairs):
        self._pairs = [(str(name), str(value)) for name, value in pairs]

    def items(self, multi: bool = False):
        return list(self._pairs)

    def get(self, name, default=None):
        for key, value in self._pairs:
            if key.lower() == str(name).lower():
                return value
        return default

    def get_all(self, name):
        return [v for k, v in self._pairs if k.lower() == str(name).lower()]


class FakeMessage:
    def __init__(
        self,
        *,
        method="GET",
        url="https://target.example/",
        http_version="HTTP/2",
        headers=None,
        content=b"",
        timestamp_start=0.0,
        timestamp_end=0.0,
        status=None,
        reason="",
    ):
        self.method = method
        self.url = url
        self.pretty_url = url
        self.http_version = http_version
        self.headers = FakeHeaders(headers or [])
        self.content = content
        self.raw_content = content
        self.timestamp_start = timestamp_start
        self.timestamp_end = timestamp_end
        self.status_code = status
        self.status = status
        self.reason = reason


class FakeConnection:
    def __init__(self, *, peername=None, address=None, tls_established=False, sni=None, alpn=None):
        self.peername = peername
        self.address = address
        self.tls_established = tls_established
        self.sni = sni
        self.alpn = alpn


class FakeError:
    def __init__(self, msg="connection reset"):
        self.msg = msg


class FakeFlow:
    def __init__(
        self,
        *,
        request: FakeMessage | None = None,
        response: FakeMessage | None = None,
        error=None,
        client_conn=None,
        server_conn=None,
        intercepted: bool = True,
    ):
        self.request = request or FakeMessage()
        self.response = response
        self.error = error
        self.client_conn = client_conn or FakeConnection(peername=("172.30.0.2", 40000))
        self.server_conn = server_conn or FakeConnection(
            address=("93.184.216.34", 443), tls_established=True, sni="target.example", alpn="h2"
        )
        self.intercepted = intercepted
