from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import ssl
import tempfile
import time
import unicodedata
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urljoin, urlunsplit, urlsplit

import dns.exception
import dns.resolver
import h11

from .source_identity import SourceValidationError, canonicalize_url

DEFAULT_USER_AGENT = "PolyphemusURLDownloader/1.0"

HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}
MARKDOWN_MEDIA_TYPES = {
    "text/markdown",
    "text/x-markdown",
}
_AMBIGUOUS_MEDIA_TYPES = {
    "application/octet-stream",
    "application/markdown",
    "application/x-markdown",
    "text/md",
}
_MAX_CONTENT_LENGTH_DECIMAL_DIGITS = 4300


class URLDownloadError(Exception):
    """Stable public downloader error.

    The message is intentionally generic for callers; ``code`` carries the
    stable machine-readable identifier.
    """

    def __init__(self, code: str, message: str = "URL download failed"):
        self.code = code
        self.message = message
        super().__init__(message)


class _DnsTimeoutError(Exception):
    pass


class _DnsNoAnswerError(Exception):
    pass


class _DnsResolutionFailedError(Exception):
    pass


@dataclass(frozen=True)
class DownloadLimits:
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    total_timeout: float = 120.0
    max_redirects: int = 5
    max_wire_bytes: int = 10 * 1024 * 1024
    max_decoded_bytes: int = 10 * 1024 * 1024
    stream_chunk_size: int = 64 * 1024


def build_download_limits_from_config() -> DownloadLimits:
    from ..app.config import config

    return DownloadLimits(
        connect_timeout=config.URL_DOWNLOAD_CONNECT_TIMEOUT,
        read_timeout=config.URL_DOWNLOAD_READ_TIMEOUT,
        total_timeout=config.URL_DOWNLOAD_TOTAL_TIMEOUT,
        max_redirects=config.URL_DOWNLOAD_MAX_REDIRECTS,
        max_wire_bytes=config.URL_DOWNLOAD_MAX_WIRE_BYTES,
        max_decoded_bytes=config.URL_DOWNLOAD_MAX_DECODED_BYTES,
        stream_chunk_size=config.URL_DOWNLOAD_STREAM_CHUNK_SIZE,
    )


@dataclass(frozen=True)
class UrlDownloadResult:
    requested_url: str
    canonical_url: str
    final_url: str
    redirect_chain: list[str]
    content_type: str | None
    content_disposition: str | None
    etag: str | None
    last_modified: str | None
    downloaded_bytes: int
    sha256: str
    raw_artifact_path: str | None
    fetched_at: str


@dataclass(frozen=True)
class TransportRequest:
    url: str
    method: str
    headers: Mapping[str, str]
    host: str
    port: int
    ip: str


class TransportResponse:
    status_code: int
    headers: list[tuple[str, str]]

    def iter_raw(self, chunk_size: int) -> Iterator[bytes]: ...  # pragma: no cover
    def close(self) -> None: ...  # pragma: no cover


def _bracket_ipv6(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def _format_authority(host: str, port: int, scheme: str) -> str:
    is_default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    host_part = _bracket_ipv6(host)
    return host_part if is_default else f"{host_part}:{port}"


def _is_doc_ipv4(ip: ipaddress.IPv4Address) -> bool:
    for net in (
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
    ):
        if ip in net:
            return True
    return False


def _is_doc_ipv6(ip: ipaddress.IPv6Address) -> bool:
    return ip in ipaddress.ip_network("2001:db8::/32")


def is_forbidden_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True when the address must never be connected to."""

    if isinstance(ip, ipaddress.IPv4Address):
        if (
            ip.is_loopback
            or ip.is_unspecified
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        ):
            return True
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
        if ip == ipaddress.IPv4Address("169.254.169.254"):
            return True
        if _is_doc_ipv4(ip):
            return True
        return False

    if (
        ip.is_loopback
        or ip.is_unspecified
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or getattr(ip, "is_site_local", False)
        or _is_doc_ipv6(ip)
    ):
        return True
    if ip.ipv4_mapped is not None:
        return True
    if not getattr(ip, "is_global", True):
        return True
    return False


def _is_token_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in "!#$%&'*+-.^_`|~")


def _read_disposition_value(value: str, start: int) -> tuple[str | None, bool, int]:
    """Read one Content-Disposition parameter value starting after ``=``.

    Quoted values may contain semicolons; anything other than optional
    whitespace between a closing quote and the next semicolon is malformed.
    An empty or unterminated value is returned as ``(None, False)``. The
    second element reports whether the value was a quoted-string and the third
    element is the index just past the parsed value, ready to scan the next
    parameter.
    """
    while start < len(value) and value[start] in " \t":
        start += 1
    if start >= len(value):
        return None, False, len(value)

    if value[start] in ("'", '"'):
        quote = value[start]
        end = value.find(quote, start + 1)
        if end == -1:
            return None, False, len(value)
        tail = value[end + 1 :]
        semicolon = tail.find(";")
        if semicolon == -1:
            if tail.strip():
                return None, False, len(value)
            return value[start + 1 : end], True, len(value)
        elif tail[:semicolon].strip():
            return None, False, len(value)
        return value[start + 1 : end], True, end + 1 + semicolon + 1

    semicolon = value.find(";", start)
    if semicolon == -1:
        return value[start:].strip(), False, len(value)
    return value[start:semicolon].strip(), False, semicolon + 1


def _contains_control(text: str) -> bool:
    """True when the text contains any decoded Unicode control character."""
    return any(unicodedata.category(ch) == "Cc" for ch in text)


def _decode_plain_filename(raw: str) -> str | None:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    if not raw or _contains_control(raw):
        return None
    return raw


_EXT_FILENAME_CHARSET = "utf-8"
_ATTR_CHARS = set("!#$&+-.^_`|~")


def _decode_ext_filename(raw: str) -> str | None:
    """Decode one strict RFC 5987/6266 ``filename*`` value, or return None.

    The extended value must be an unquoted ``charset'language'value`` triple
    using the only supported charset (UTF-8). Language may be empty or an
    RFC 5646-style alphanumeric/hyphen tag. Every raw character in the value
    part must be an ``attr-char``; anything else must be percent-encoded, and
    every ``%`` must start exactly two hexadecimal digits. The percent-decoded
    byte string must decode as the declared charset and the decoded filename
    must be non-empty and control-free.
    """
    raw = raw.strip()
    if not raw:
        return None
    if _contains_control(raw):
        return None

    first_quote = raw.find("'")
    second_quote = raw.find("'", first_quote + 1)
    if first_quote == -1 or second_quote == -1:
        return None
    if raw.find("'", second_quote + 1) != -1:
        return None

    charset = raw[:first_quote]
    language = raw[first_quote + 1 : second_quote]
    value = raw[second_quote + 1 :]

    if charset.lower() != _EXT_FILENAME_CHARSET:
        return None
    if not re.fullmatch(r"[A-Za-z0-9-]*", language):
        return None
    if not value:
        return None

    decoded = _decode_ext_filename_value(value)
    if decoded is None or decoded == "":
        return None
    if _contains_control(decoded):
        return None
    return decoded


def _decode_ext_filename_value(value: str) -> str | None:
    """Percent-decode a strict ``filename*`` value part as the declared charset."""
    out = bytearray()
    index = 0
    while index < len(value):
        ch = value[index]
        if ch == "%":
            if index + 2 >= len(value):
                return None
            high, low = value[index + 1], value[index + 2]
            if high not in "0123456789abcdefABCDEF" or low not in "0123456789abcdefABCDEF":
                return None
            out.append(int(high + low, 16))
            index += 3
            continue
        if not (ch.isascii() and (ch.isalnum() or ch in _ATTR_CHARS)):
            return None
        out.extend(ch.encode("ascii"))
        index += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _filename_from_content_disposition(value: str | None) -> tuple[str | None, bool]:
    """Extract filename evidence from Content-Disposition, order-independent.

    Every exact ``filename`` and ``filename*`` parameter is inspected. The
    returned tuple is ``(filename, unreliable)``: ``filename`` is the single
    decoded value when all evidence is well-formed, non-empty, control-free,
    and mutually consistent; ``unreliable`` is True when any exact parameter
    is malformed, conflicting, or control-containing. Longer names such as
    ``xfilename``, ``notfilename`` or ``filename0`` never match.
    """
    if not value:
        return None, False

    pos = 0
    length = len(value)
    candidates: list[str] = []
    while pos < length:
        # Skip optional whitespace following the start of the value or a ';'.
        while pos < length and value[pos] in " \t":
            pos += 1

        if value[pos : pos + len("filename*")].lower() == "filename*":
            name = "filename*"
            is_ext = True
        elif value[pos : pos + len("filename")].lower() == "filename":
            name = "filename"
            is_ext = False
        else:
            # Unknown parameter: consume its value so a quoted semicolon or a
            # look-alike name inside the value is never misread as evidence.
            equals = value.find("=", pos)
            next_semicolon = value.find(";", pos)
            if equals != -1 and (next_semicolon == -1 or equals < next_semicolon):
                _, _, end = _read_disposition_value(value, equals + 1)
                pos = end
            elif next_semicolon != -1:
                pos = next_semicolon + 1
            else:
                break
            continue

        after_name = pos + len(name)
        # A token character immediately after the name means it is a longer,
        # different parameter name (e.g. "filename0" or "filename-x").
        if after_name < length and _is_token_char(value[after_name]):
            pos = value.find(";", after_name)
            if pos == -1:
                break
            pos += 1
            continue

        pos = after_name
        while pos < length and value[pos] in " \t":
            pos += 1
        if pos >= length or value[pos] != "=":
            # An exact filename parameter without a value is malformed.
            return None, True

        raw, quoted, end = _read_disposition_value(value, pos + 1)
        if raw is None:
            return None, True
        if is_ext:
            if quoted:
                return None, True
            decoded = _decode_ext_filename(raw)
            if decoded is None:
                return None, True
        else:
            decoded = _decode_plain_filename(raw)
            if decoded is None:
                return None, True
        candidates.append(decoded)
        pos = end

    if not candidates:
        return None, False
    if len(set(candidates)) != 1:
        return None, True
    return candidates[0], False


def _url_filename_markdown_evidence(url: str) -> bool | None:
    """Return trustworthy Markdown-suffix evidence from the final URL path.

    ``True`` when the percent-decoded basename carries a ``.md`` or
    ``.markdown`` suffix, ``False`` when it carries a different extension, and
    ``None`` when the URL has no filename, the basename has no extension, the
    percent-decoding is invalid UTF-8, or the decoded filename contains
    control characters (which makes it unusable as evidence). Encoded reserved
    separators are decoded here for evidence inspection only; they never
    become filesystem separators.
    """
    path = urlsplit(url).path.rstrip("/")
    if not path:
        return None
    base = path.rsplit("/", 1)[-1]
    try:
        decoded = unquote(base, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return None
    if _contains_control(decoded):
        return None
    if decoded.lower().endswith((".md", ".markdown")):
        return True
    if "." in decoded:
        return False
    return None


def _disposition_filename_markdown_evidence(
    disposition: str | None,
) -> tuple[bool | None, bool]:
    """Return Markdown-suffix evidence from Content-Disposition filenames.

    The tuple is ``(evidence, unreliable)``. ``evidence`` is ``True`` or
    ``False`` for one well-formed decoded filename, or ``None`` when no exact
    filename parameter exists. ``unreliable`` is ``True`` when any exact
    filename parameter is malformed, conflicting, or control-containing.
    """
    filename, unreliable = _filename_from_content_disposition(disposition)
    if unreliable:
        return None, True
    if not filename:
        return None, False
    return filename.lower().endswith((".md", ".markdown")), False


def _media_type(value: str | None) -> str | None:
    if not value:
        return None
    media = value.split(";", 1)[0].strip().lower()
    return media or None


def validate_content_type(
    final_url: str,
    content_type: str | None,
    content_disposition: str | None,
) -> None:
    media = _media_type(content_type)
    if media is None:
        raise URLDownloadError("URL_CONTENT_TYPE_AMBIGUOUS")

    if media in HTML_MEDIA_TYPES:
        return
    if media in MARKDOWN_MEDIA_TYPES:
        return
    if media == "text/plain":
        url_evidence = _url_filename_markdown_evidence(final_url)
        disposition_evidence, unreliable = _disposition_filename_markdown_evidence(
            content_disposition
        )
        if unreliable:
            raise URLDownloadError("URL_CONTENT_TYPE_AMBIGUOUS")
        if (
            url_evidence is not None
            and disposition_evidence is not None
            and url_evidence != disposition_evidence
        ):
            raise URLDownloadError("URL_CONTENT_TYPE_AMBIGUOUS")
        if url_evidence is True or disposition_evidence is True:
            return
        raise URLDownloadError("URL_CONTENT_TYPE_AMBIGUOUS")
    if media in _AMBIGUOUS_MEDIA_TYPES:
        raise URLDownloadError("URL_CONTENT_TYPE_AMBIGUOUS")
    raise URLDownloadError("URL_CONTENT_TYPE_UNSUPPORTED")


def _rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _map_canonicalization_error(exc: SourceValidationError) -> str:
    mapping = {
        "URL_INVALID": "URL_INVALID",
        "URL_UNSUPPORTED_SCHEME": "URL_UNSUPPORTED_SCHEME",
        "URL_CREDENTIALS_FORBIDDEN": "URL_CREDENTIALS_FORBIDDEN",
        "URL_HOST_INVALID": "URL_HOST_INVALID",
        "URL_PORT_FORBIDDEN": "URL_PORT_FORBIDDEN",
    }
    return mapping.get(exc.code, "URL_INVALID")


def _canonicalize_url(url: str) -> str:
    try:
        return canonicalize_url(url)
    except SourceValidationError as exc:
        raise URLDownloadError(_map_canonicalization_error(exc)) from None


def _has_explicit_empty_query(raw_url: str) -> bool:
    before_fragment = raw_url.split("#", 1)[0]
    if "?" not in before_fragment:
        return False
    return urlsplit(raw_url).query == ""


def _request_url_for_raw(raw_url: str, canonical_url: str) -> str:
    """Build the outgoing request URL for a raw URL.

    An explicit empty query (``path?``) is preserved only here, in the
    outgoing request target. Canonical identity never keeps the empty query
    marker, so empty and absent queries are identical for canonicalization,
    ``final_url``, ``redirect_chain``, and redirect-loop detection.
    """
    if not _has_explicit_empty_query(raw_url):
        return canonical_url

    parts = urlsplit(canonical_url)
    if parts.query:
        return canonical_url

    path = parts.path or "/"
    if not path.endswith("?"):
        path += "?"
    return urlunsplit((parts.scheme, parts.netloc, path, "", parts.fragment))


def _validate_resolved_addresses(
    addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> None:
    if not addresses:
        raise URLDownloadError("URL_DNS_NO_ANSWER")

    forbidden = sum(1 for addr in addresses if is_forbidden_address(addr))
    if forbidden == 0:
        return
    if forbidden == len(addresses):
        raise URLDownloadError("URL_ADDRESS_FORBIDDEN")
    raise URLDownloadError("URL_DNS_MIXED_FORBIDDEN")


def _header_values(headers: list[tuple[str, str]], name: str) -> list[str]:
    return [v for k, v in headers if k.lower() == name.lower()]


_SINGLETON_HEADER_NAMES = (
    "location",
    "content-type",
    "content-encoding",
    "content-disposition",
    "etag",
    "last-modified",
)


def _validated_singleton_headers(response: TransportResponse) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in _SINGLETON_HEADER_NAMES:
        values = _header_values(response.headers, name)
        if len(values) > 1:
            raise URLDownloadError("URL_INVALID")
        result[name] = values[0].strip() if values else None
    return result


def _single_header_strict(headers: list[tuple[str, str]], name: str) -> str | None:
    values = _header_values(headers, name)
    if not values:
        return None
    if len(values) > 1:
        raise URLDownloadError("URL_INVALID")
    return values[0].strip()


def _parse_content_length(headers: list[tuple[str, str]]) -> int | None:
    values = _header_values(headers, "content-length")
    if not values:
        return None
    if len(values) > 1:
        raise URLDownloadError("URL_CONTENT_LENGTH_INVALID")
    value = values[0]
    if not re.fullmatch(r"[0-9]+", value):
        raise URLDownloadError("URL_CONTENT_LENGTH_INVALID")
    if len(value) > _MAX_CONTENT_LENGTH_DECIMAL_DIGITS:
        raise URLDownloadError("URL_CONTENT_LENGTH_INVALID")
    try:
        return int(value)
    except (ValueError, OverflowError):
        raise URLDownloadError("URL_CONTENT_LENGTH_INVALID") from None


class _H11TransportResponse(TransportResponse):
    def __init__(
        self,
        status_code: int,
        headers: list[tuple[str, str]],
        conn: h11.Connection,
        sock: socket.socket,
        deadline: float,
        clock: Callable[[], float],
        read_timeout: float,
        chunk_size: int,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self._conn = conn
        self._sock = sock
        self._deadline = deadline
        self._clock = clock
        self._read_timeout = read_timeout
        self._chunk_size = chunk_size
        self._closed = False

    def _receive_socket_data(self) -> None:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise URLDownloadError("URL_TIMEOUT")
        timeout = min(self._read_timeout, remaining)
        self._sock.settimeout(timeout)
        try:
            data = self._sock.recv(self._chunk_size)
        except ssl.SSLError:
            raise URLDownloadError("URL_TLS_FAILED") from None
        except socket.timeout:
            raise URLDownloadError("URL_TIMEOUT") from None
        except OSError:
            raise URLDownloadError("URL_CONNECTION_FAILED") from None

        if not data:
            self._conn.receive_data(b"")
        else:
            try:
                self._conn.receive_data(data)
            except (h11.ProtocolError, h11.RemoteProtocolError):
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

    def _next_event(self):
        while True:
            try:
                event = self._conn.next_event()
            except (h11.RemoteProtocolError, h11.ProtocolError):
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

            if event is h11.NEED_DATA:
                self._receive_socket_data()
            elif event is h11.PAUSED:
                raise URLDownloadError("URL_CONNECTION_FAILED")
            else:
                return event

    def iter_raw(self, chunk_size: int) -> Iterator[bytes]:
        while True:
            event = self._next_event()
            if isinstance(event, h11.Data):
                yield event.data
            elif isinstance(event, h11.EndOfMessage):
                return
            elif isinstance(event, h11.ConnectionClosed):
                return
            else:
                raise URLDownloadError("URL_CONNECTION_FAILED")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass


class H11PinnedTransport:
    """Explicit HTTP/1.1 transport built on h11.

    Connects only to the already validated numeric IP. The socket must never
    receive a hostname for DNS resolution.
    """

    def __init__(
        self,
        *,
        connect_timeout: float,
        read_timeout: float,
        stream_chunk_size: int,
    ) -> None:
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.stream_chunk_size = stream_chunk_size

    def request(
        self,
        req: TransportRequest,
        *,
        deadline: float,
        clock: Callable[[], float],
    ) -> TransportResponse:
        sock: socket.socket | None = None
        try:
            remaining = deadline - clock()
            if remaining <= 0:
                raise URLDownloadError("URL_TIMEOUT")
            connect_timeout = min(self.connect_timeout, remaining)
            try:
                sock = socket.create_connection((req.ip, req.port), timeout=connect_timeout)
            except socket.timeout:
                raise URLDownloadError("URL_TIMEOUT") from None
            except OSError:
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

            remaining = deadline - clock()
            if remaining <= 0:
                raise URLDownloadError("URL_TIMEOUT")
            sock.settimeout(min(self.read_timeout, remaining))

            if req.url.startswith("https://"):
                remaining = deadline - clock()
                if remaining <= 0:
                    raise URLDownloadError("URL_TIMEOUT")
                sock.settimeout(min(self.read_timeout, remaining))
                try:
                    context = ssl.create_default_context()
                    sock = context.wrap_socket(sock, server_hostname=req.host)
                except ssl.SSLError:
                    raise URLDownloadError("URL_TLS_FAILED") from None
                except socket.timeout:
                    raise URLDownloadError("URL_TIMEOUT") from None
                except OSError:
                    raise URLDownloadError("URL_CONNECTION_FAILED") from None

                remaining = deadline - clock()
                if remaining <= 0:
                    raise URLDownloadError("URL_TIMEOUT")
                sock.settimeout(min(self.read_timeout, remaining))

            conn = h11.Connection(our_role=h11.CLIENT)

            parts = urlsplit(req.url)
            target = parts.path or "/"
            if parts.query:
                target += "?" + parts.query
            elif "?" in req.url:
                target += "?"

            authority = _format_authority(req.host, req.port, parts.scheme)
            request_headers = [
                ("Host", authority),
                ("User-Agent", DEFAULT_USER_AGENT),
                ("Accept-Encoding", "gzip, deflate"),
            ]

            try:
                h11_request = h11.Request(
                    method=req.method,
                    target=target,
                    headers=request_headers,
                )
                data = conn.send(h11_request)
                self._send_bytes(sock, data, deadline, clock)
                end_data = conn.send(h11.EndOfMessage())
                self._send_bytes(sock, end_data, deadline, clock)
            except ssl.SSLError:
                raise URLDownloadError("URL_TLS_FAILED") from None
            except socket.timeout:
                raise URLDownloadError("URL_TIMEOUT") from None
            except OSError:
                raise URLDownloadError("URL_CONNECTION_FAILED") from None
            except (h11.ProtocolError, h11.RemoteProtocolError):
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

            while True:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise URLDownloadError("URL_TIMEOUT")

                event = self._read_h11_event(conn, sock, deadline, clock)
                if isinstance(event, h11.Response):
                    status_code = event.status_code
                    headers = [
                        (k.decode("latin-1"), v.decode("latin-1"))
                        for k, v in event.headers
                    ]
                    response = _H11TransportResponse(
                        status_code=status_code,
                        headers=headers,
                        conn=conn,
                        sock=sock,
                        deadline=deadline,
                        clock=clock,
                        read_timeout=self.read_timeout,
                        chunk_size=self.stream_chunk_size,
                    )
                    sock = None  # ownership transferred to response
                    return response

                raise URLDownloadError("URL_CONNECTION_FAILED")

        except URLDownloadError:
            raise
        except ssl.SSLError:
            raise URLDownloadError("URL_TLS_FAILED") from None
        except socket.timeout:
            raise URLDownloadError("URL_TIMEOUT") from None
        except OSError:
            raise URLDownloadError("URL_CONNECTION_FAILED") from None
        except (h11.ProtocolError, h11.RemoteProtocolError):
            raise URLDownloadError("URL_CONNECTION_FAILED") from None
        except Exception:
            raise URLDownloadError("URL_CONNECTION_FAILED") from None
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _send_bytes(self, sock, data: bytes, deadline: float, clock) -> None:
        view = memoryview(data)
        while view:
            remaining = deadline - clock()
            if remaining <= 0:
                raise URLDownloadError("URL_TIMEOUT")
            sock.settimeout(min(self.read_timeout, remaining))
            try:
                sent = sock.send(view)
            except ssl.SSLError:
                raise URLDownloadError("URL_TLS_FAILED") from None
            except socket.timeout:
                raise URLDownloadError("URL_TIMEOUT") from None
            except OSError:
                raise URLDownloadError("URL_CONNECTION_FAILED") from None
            if sent <= 0:
                raise URLDownloadError("URL_CONNECTION_FAILED")
            view = view[sent:]

    def _read_h11_event(self, conn, sock, deadline, clock):
        while True:
            try:
                event = conn.next_event()
            except (h11.RemoteProtocolError, h11.ProtocolError):
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

            if event is h11.NEED_DATA:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise URLDownloadError("URL_TIMEOUT")
                sock.settimeout(min(self.read_timeout, remaining))
                try:
                    data = sock.recv(self.stream_chunk_size)
                except ssl.SSLError:
                    raise URLDownloadError("URL_TLS_FAILED") from None
                except socket.timeout:
                    raise URLDownloadError("URL_TIMEOUT") from None
                except OSError:
                    raise URLDownloadError("URL_CONNECTION_FAILED") from None
                if not data:
                    try:
                        conn.receive_data(b"")
                    except (h11.ProtocolError, h11.RemoteProtocolError):
                        raise URLDownloadError("URL_CONNECTION_FAILED") from None
                else:
                    try:
                        conn.receive_data(data)
                    except (h11.ProtocolError, h11.RemoteProtocolError):
                        raise URLDownloadError("URL_CONNECTION_FAILED") from None
            elif event is h11.PAUSED:
                raise URLDownloadError("URL_CONNECTION_FAILED")
            else:
                return event


class DnsPythonResolver:
    """Concrete resolver backed by dnspython.

    Resolves A and AAAA records synchronously, inline. No ``getaddrinfo``,
    thread pool, or background thread is used.
    """

    def __init__(
        self,
        *,
        resolver_factory: Callable[[], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolver_factory = resolver_factory or dns.resolver.Resolver
        self._clock = clock

    def __call__(
        self,
        host: str,
        lifetime: float,
    ) -> Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        resolver = self._resolver_factory()
        start = self._clock()
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []

        for rdtype in ("A", "AAAA"):
            remaining = lifetime - (self._clock() - start)
            if remaining <= 0:
                raise _DnsTimeoutError()

            try:
                answer = resolver.resolve(host, rdtype, lifetime=remaining, search=False)
            except dns.resolver.LifetimeTimeout:
                raise _DnsTimeoutError() from None
            except dns.resolver.NXDOMAIN:
                raise _DnsNoAnswerError() from None
            except dns.resolver.NoAnswer:
                continue
            except dns.resolver.NoNameservers:
                raise _DnsResolutionFailedError() from None
            except dns.exception.DNSException:
                raise _DnsResolutionFailedError() from None
            except Exception:
                raise _DnsResolutionFailedError() from None

            for rdata in answer:
                address = getattr(rdata, "address", None)
                if address is None:
                    continue
                try:
                    ip = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if ip not in addresses:
                    addresses.append(ip)

        if not addresses:
            raise _DnsNoAnswerError()
        return addresses


class UrlDownloader:
    def __init__(
        self,
        resolver: Callable[
            [str, float], Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address]
        ]
        | None = None,
        transport: TransportResponse = None,
        *,
        limits: DownloadLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._resolver = resolver if resolver is not None else DnsPythonResolver()
        if limits is None:
            limits = build_download_limits_from_config()
        self._limits = limits
        if transport is None:
            self._transport = H11PinnedTransport(
                connect_timeout=limits.connect_timeout,
                read_timeout=limits.read_timeout,
                stream_chunk_size=limits.stream_chunk_size,
            )
        else:
            self._transport = transport
        self._clock = clock
        self._now = now

    def _resolve_addresses(
        self,
        hostname: str,
        remaining: float,
    ) -> Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            return self._resolver(hostname, remaining)
        except URLDownloadError:
            raise
        except _DnsTimeoutError:
            raise URLDownloadError("URL_TIMEOUT") from None
        except _DnsNoAnswerError:
            raise URLDownloadError("URL_DNS_NO_ANSWER") from None
        except _DnsResolutionFailedError:
            raise URLDownloadError("URL_DNS_RESOLUTION_FAILED") from None
        except TimeoutError:
            raise URLDownloadError("URL_TIMEOUT") from None
        except Exception:
            raise URLDownloadError("URL_DNS_RESOLUTION_FAILED") from None

    def download(
        self,
        requested_url: str,
        *,
        artifact_dir: Path | None = None,
    ) -> UrlDownloadResult:
        deadline = self._clock() + self._limits.total_timeout

        initial_canonical = _canonicalize_url(requested_url)
        self._validate_direct_ip(initial_canonical)

        current_canonical = initial_canonical
        current_request_url = _request_url_for_raw(requested_url, initial_canonical)
        visited = {current_canonical}
        redirect_chain: list[str] = []

        while True:
            if self._clock() > deadline:
                raise URLDownloadError("URL_TIMEOUT")

            parts = urlsplit(current_canonical)
            scheme = parts.scheme
            hostname = parts.hostname
            if not hostname:
                raise URLDownloadError("URL_HOST_INVALID")
            port = parts.port or (443 if scheme == "https" else 80)

            try:
                literal_ip = ipaddress.ip_address(hostname)
                if is_forbidden_address(literal_ip):
                    raise URLDownloadError("URL_ADDRESS_FORBIDDEN")
                addresses = [literal_ip]
            except ValueError:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise URLDownloadError("URL_TIMEOUT")
                addresses = self._resolve_addresses(hostname, remaining)
                if self._clock() > deadline:
                    raise URLDownloadError("URL_TIMEOUT")

            _validate_resolved_addresses(addresses)
            pin = str(addresses[0])

            req = TransportRequest(
                url=current_request_url,
                method="GET",
                headers={},
                host=hostname,
                port=port,
                ip=pin,
            )

            try:
                response = self._transport.request(
                    req, deadline=deadline, clock=self._clock
                )
            except URLDownloadError:
                raise
            except Exception:
                raise URLDownloadError("URL_CONNECTION_FAILED") from None

            try:
                cached_headers = _validated_singleton_headers(response)
                status = response.status_code

                if status in (301, 302, 303, 307, 308):
                    if len(redirect_chain) >= self._limits.max_redirects:
                        raise URLDownloadError("URL_REDIRECT_LIMIT")

                    location = cached_headers["location"]
                    if not location:
                        raise URLDownloadError("URL_REDIRECT_LOCATION_MISSING")

                    new_url = urljoin(current_canonical, location)
                    if _has_explicit_empty_query(location):
                        # urljoin() keeps the previous query for a bare "?" or
                        # "?#fragment" Location. Rebuild with an explicit empty
                        # query so canonical identity and loop detection clear
                        # the old query; only the outgoing request URL keeps
                        # the trailing "?".
                        parts = urlsplit(new_url)
                        path = parts.path or "/"
                        new_url = urlunsplit(
                            (parts.scheme, parts.netloc, path, "", "")
                        ) + "?"
                    new_canonical = _canonicalize_url(new_url)
                    self._validate_direct_ip(new_canonical)

                    if new_canonical in visited:
                        raise URLDownloadError("URL_REDIRECT_LOOP")

                    visited.add(new_canonical)
                    redirect_chain.append(current_canonical)
                    current_canonical = new_canonical
                    # An explicit empty query in the Location is preserved only
                    # in the outgoing request URL; loop detection and the
                    # redirect chain use canonical identity, where empty and
                    # absent queries are the same.
                    current_request_url = _request_url_for_raw(location, new_canonical)
                    continue

                if status != 200:
                    raise URLDownloadError("URL_HTTP_STATUS")

                content_type = cached_headers["content-type"]
                content_disposition = cached_headers["content-disposition"]
                etag = cached_headers["etag"]
                last_modified = cached_headers["last-modified"]
                content_encoding = cached_headers["content-encoding"]

                validate_content_type(
                    current_canonical, content_type, content_disposition
                )

                result = self._read_response(
                    response=response,
                    initial_canonical_url=initial_canonical,
                    final_url=current_canonical,
                    requested_url=requested_url,
                    redirect_chain=redirect_chain,
                    artifact_dir=artifact_dir,
                    deadline=deadline,
                    content_type=content_type,
                    content_disposition=content_disposition,
                    etag=etag,
                    last_modified=last_modified,
                    content_encoding=content_encoding,
                )
                return result
            finally:
                try:
                    response.close()
                except Exception:
                    pass

    def _validate_direct_ip(self, canonical_url: str) -> None:
        host = urlsplit(canonical_url).hostname
        if not host:
            return
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return
        if is_forbidden_address(ip):
            raise URLDownloadError("URL_ADDRESS_FORBIDDEN")

    def _read_response(
        self,
        *,
        response: TransportResponse,
        initial_canonical_url: str,
        final_url: str,
        requested_url: str,
        redirect_chain: list[str],
        artifact_dir: Path | None,
        deadline: float,
        content_type: str | None,
        content_disposition: str | None,
        etag: str | None,
        last_modified: str | None,
        content_encoding: str | None,
    ) -> UrlDownloadResult:
        chunk_size = self._limits.stream_chunk_size

        content_length_header = _parse_content_length(response.headers)

        encoding = (content_encoding or "").strip().lower()
        decoder = None

        if encoding in ("", "identity"):
            if content_length_header is not None:
                if content_length_header > self._limits.max_wire_bytes:
                    raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")
                if content_length_header > self._limits.max_decoded_bytes:
                    raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")
        elif encoding == "gzip":
            if content_length_header is not None and content_length_header > self._limits.max_wire_bytes:
                raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        elif encoding == "deflate":
            if content_length_header is not None and content_length_header > self._limits.max_wire_bytes:
                raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")
            decoder = zlib.decompressobj()
        else:
            raise URLDownloadError("URL_CONTENT_ENCODING_UNSUPPORTED")

        digest = hashlib.sha256()
        wire_bytes = 0
        decoded_bytes = 0
        part_path: str | None = None
        part_file = None
        raw_fd: int | None = None
        input_buffer = bytearray()

        try:
            if artifact_dir is not None:
                os.makedirs(artifact_dir, exist_ok=True)
                raw_fd, part_path = tempfile.mkstemp(
                    prefix="url-download-", suffix=".part", dir=str(artifact_dir)
                )
                try:
                    part_file = os.fdopen(raw_fd, "wb")
                except Exception:
                    try:
                        os.close(raw_fd)
                    except OSError:
                        pass
                    raw_fd = None
                    raise URLDownloadError("URL_INVALID") from None
                raw_fd = None

            for raw_chunk in response.iter_raw(chunk_size):
                if self._clock() > deadline:
                    raise URLDownloadError("URL_TIMEOUT")

                wire_bytes += len(raw_chunk)
                if wire_bytes > self._limits.max_wire_bytes:
                    raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")

                if decoder is None:
                    decoded_bytes += len(raw_chunk)
                    if decoded_bytes > self._limits.max_decoded_bytes:
                        raise URLDownloadError("URL_DOWNLOAD_TOO_LARGE")
                    digest.update(raw_chunk)
                    if part_file:
                        part_file.write(raw_chunk)
                    continue

                input_buffer.extend(raw_chunk)
                while input_buffer:
                    remaining_capacity = (
                        self._limits.max_decoded_bytes - decoded_bytes
                    )
                    max_len = max(1, remaining_capacity + 1)
                    try:
                        data = decoder.decompress(bytes(input_buffer), max_len)
                    except zlib.error:
                        raise URLDownloadError("URL_INVALID") from None

                    consumed = len(input_buffer) - len(decoder.unconsumed_tail)
                    if consumed > 0:
                        del input_buffer[:consumed]
                    else:
                        break

                    if data:
                        decoded_bytes += len(data)
                        if decoded_bytes > self._limits.max_decoded_bytes:
                            raise URLDownloadError("URL_DECOMPRESSION_LIMIT")
                        digest.update(data)
                        if part_file:
                            part_file.write(data)
                    elif decoder.unconsumed_tail:
                        continue
                    elif input_buffer:
                        continue
                    else:
                        break

            if decoder is not None:
                remaining_capacity = self._limits.max_decoded_bytes - decoded_bytes
                try:
                    tail = decoder.flush(max(1, remaining_capacity + 1))
                except zlib.error:
                    raise URLDownloadError("URL_INVALID") from None

                if tail:
                    decoded_bytes += len(tail)
                    if decoded_bytes > self._limits.max_decoded_bytes:
                        raise URLDownloadError("URL_DECOMPRESSION_LIMIT")
                    digest.update(tail)
                    if part_file:
                        part_file.write(tail)

                if not decoder.eof:
                    raise URLDownloadError("URL_INVALID")
                if decoder.unused_data:
                    raise URLDownloadError("URL_INVALID")

            if content_length_header is not None and wire_bytes != content_length_header:
                raise URLDownloadError("URL_CONTENT_LENGTH_INVALID")

        except Exception as exc:
            if part_file is not None:
                try:
                    part_file.close()
                except Exception:
                    pass
            if part_path and os.path.exists(part_path):
                try:
                    os.unlink(part_path)
                except Exception:
                    pass
            if isinstance(exc, URLDownloadError):
                raise
            raise URLDownloadError("URL_INVALID") from None

        sha256_hex = digest.hexdigest()
        final_path: Path | None = None
        if artifact_dir is not None:
            try:
                if part_file is not None:
                    part_file.close()
                final_path = Path(artifact_dir) / sha256_hex
                os.replace(part_path, final_path)
                part_path = None
            except Exception:
                if part_file is not None:
                    try:
                        part_file.close()
                    except Exception:
                        pass
                if part_path and os.path.exists(part_path):
                    try:
                        os.unlink(part_path)
                    except Exception:
                        pass
                raise URLDownloadError("URL_INVALID") from None

        return UrlDownloadResult(
            requested_url=requested_url,
            canonical_url=initial_canonical_url,
            final_url=final_url,
            redirect_chain=redirect_chain,
            content_type=content_type,
            content_disposition=content_disposition,
            etag=etag,
            last_modified=last_modified,
            downloaded_bytes=decoded_bytes,
            sha256=sha256_hex,
            raw_artifact_path=str(final_path) if final_path else None,
            fetched_at=_rfc3339(self._now()),
        )
