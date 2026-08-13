from pathlib import Path
from urllib.parse import quote
import hashlib
import ipaddress
import urllib.parse


class SourceValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def content_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_source_path(path: Path, *, allowed_root: Path) -> Path:
    resolved_path = path.resolve()
    resolved_root = allowed_root.resolve()
    if not resolved_path.exists():
        raise SourceValidationError("SOURCE_NOT_FOUND", "Source file does not exist")
    if not resolved_path.is_file():
        raise SourceValidationError("UNSUPPORTED_FORMAT", "Source path is not a file")
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SourceValidationError(
            "SOURCE_OUTSIDE_ALLOWED_ROOT",
            "Source path is outside the allowed ingestion root",
        ) from exc
    return resolved_path


def build_source_key(path: Path, *, allowed_root: Path) -> str:
    resolved_path = validate_source_path(path, allowed_root=allowed_root)
    relative = resolved_path.relative_to(allowed_root.resolve()).as_posix()
    return f"file:{quote(relative, safe='/.-_ ')}"


# ---------------------------------------------------------------------------
# URL identity (Milestone 4)
# ---------------------------------------------------------------------------

_URL_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalize_percent_encoding(value: str) -> str:
    """Normalize %-escapes: uppercase hex digits and decode unreserved bytes."""
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        if i + 2 >= len(value):
            raise SourceValidationError("URL_INVALID", "Invalid percent-encoding")
        hi = value[i + 1]
        lo = value[i + 2]
        if hi not in "0123456789abcdefABCDEF" or lo not in "0123456789abcdefABCDEF":
            raise SourceValidationError("URL_INVALID", "Invalid percent-encoding")
        hex_digits = (hi + lo).upper()
        byte_val = int(hex_digits, 16)
        decoded = chr(byte_val)
        if decoded in _URL_UNRESERVED:
            out.append(decoded)
        else:
            out.append("%" + hex_digits)
        i += 3
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4 dot-segment removal, preserving repeated slashes."""
    input_buf = path
    output: list[str] = []
    while input_buf:
        if input_buf.startswith("../"):
            input_buf = input_buf[3:]
        elif input_buf.startswith("./"):
            input_buf = input_buf[2:]
        elif input_buf.startswith("/./"):
            input_buf = "/" + input_buf[3:]
        elif input_buf == "/.":
            input_buf = "/"
        elif input_buf.startswith("/../"):
            input_buf = "/" + input_buf[4:]
            if output:
                output.pop()
        elif input_buf == "/..":
            input_buf = "/"
            if output:
                output.pop()
        elif input_buf in (".", ".."):
            input_buf = ""
        else:
            if input_buf.startswith("/"):
                idx = input_buf.find("/", 1)
                if idx == -1:
                    segment = input_buf
                    input_buf = ""
                else:
                    segment = input_buf[:idx]
                    input_buf = input_buf[idx:]
            else:
                idx = input_buf.find("/")
                if idx == -1:
                    segment = input_buf
                    input_buf = ""
                else:
                    segment = input_buf[:idx]
                    input_buf = input_buf[idx:]
            output.append(segment)
    return "".join(output)


def _is_valid_hostname(host: str) -> bool:
    """RFC-valid DNS hostname (no trailing dot, labels <=63, no leading/trailing hyphen)."""
    if not host or len(host) > 253:
        return False
    if host.endswith("."):
        host = host[:-1]
    if not host:
        return False
    for label in host.split("."):
        if not label or len(label) > 63:
            return False
        if label.startswith("-") or label.endswith("-"):
            return False
        for ch in label:
            if not (ch.isascii() and (ch.isalnum() or ch == "-")):
                return False
    return True


def _parse_legacy_ipv4_component(component: str) -> int | None:
    """Parse one legacy IPv4 component using decimal, 0x-hex, or leading-zero octal."""
    if not component:
        return None
    lower = component.lower()
    if lower.startswith("0x"):
        rest = lower[2:]
        if not rest or any(ch not in "0123456789abcdef" for ch in rest):
            return None
        return int(rest, 16)
    if component[0] == "0" and len(component) > 1:
        # Legacy leading-zero octal
        if any(ch not in "01234567" for ch in component[1:]):
            return None
        return int(component, 8)
    if not component.isdigit():
        return None
    return int(component, 10)


def _parse_legacy_ipv4(host: str) -> list[int] | None:
    """Return legacy IPv4 values if `host` is a valid historical IPv4 form, else None.

    Supported widths:
    - 1 component: 32 bits
    - 2 components: 8 + 24 bits
    - 3 components: 8 + 8 + 16 bits
    - 4 components: 8 + 8 + 8 + 8 bits
    """
    parts = host.split(".")
    if not parts or len(parts) > 4:
        return None

    values: list[int] = []
    for part in parts:
        value = _parse_legacy_ipv4_component(part)
        if value is None:
            return None
        values.append(value)

    widths = {
        1: (32,),
        2: (8, 24),
        3: (8, 8, 16),
        4: (8, 8, 8, 8),
    }
    width_args = widths.get(len(parts))
    if width_args is None:
        return None

    for value, bits in zip(values, width_args):
        if value < 0 or value > (1 << bits) - 1:
            return None

    return values


def _is_canonical_ipv4_decimal(host: str) -> bool:
    """Return True only for canonical four-component decimal IPv4."""
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        if len(part) > 1 and part[0] == "0":
            return False
        try:
            value = int(part)
        except ValueError:
            return False
        if not (0 <= value <= 255):
            return False
    return True


def _looks_like_alternative_ipv4(host: str) -> bool:
    """Return True for numeric legacy IPv4 alternatives that are not canonical."""
    if not host:
        return False

    legacy_values = _parse_legacy_ipv4(host)
    if legacy_values is None:
        return False

    if _is_canonical_ipv4_decimal(host):
        return False

    return True


def _normalize_host(host: str) -> str:
    """Return canonical host: lowercase ASCII domain or IP literal (IPv6 bracketed)."""
    if not host:
        raise SourceValidationError("URL_HOST_INVALID", "Missing host")
    # Strip surrounding brackets if they were accidentally passed (e.g. from netloc parsing)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    # Reject alternative IPv4 notation before falling back to DNS hostname validation.
    if _looks_like_alternative_ipv4(host):
        raise SourceValidationError("URL_HOST_INVALID", "Alternative IPv4 notation is not allowed")

    try:
        ip = ipaddress.ip_address(host)
        if ip.version == 4:
            return str(ip)
        return f"[{ip}]"
    except ValueError:
        pass

    try:
        ascii_host = host.lower().encode("idna").decode("ascii")
    except UnicodeError:
        raise SourceValidationError("URL_HOST_INVALID", "Invalid internationalized host")
    if not ascii_host:
        raise SourceValidationError("URL_HOST_INVALID", "Empty host after IDNA")
    if not _is_valid_hostname(ascii_host):
        raise SourceValidationError("URL_HOST_INVALID", "Invalid hostname")
    return ascii_host


def canonicalize_url(raw: str) -> str:
    """Canonicalize an HTTP(S) URL for identity purposes.

    Raises SourceValidationError with one of the documented stable error codes.
    """
    if raw != raw.strip():
        raise SourceValidationError("URL_INVALID", "Leading/trailing whitespace not allowed")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        raise SourceValidationError("URL_INVALID", "Control characters not allowed")

    parsed = urllib.parse.urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise SourceValidationError("URL_UNSUPPORTED_SCHEME", "Only http and https are supported")

    if parsed.username is not None or parsed.password is not None:
        raise SourceValidationError("URL_CREDENTIALS_FORBIDDEN", "Userinfo is forbidden")

    try:
        host_raw = parsed.hostname
        port_raw = parsed.port
    except ValueError:
        raise SourceValidationError("URL_INVALID", "Invalid authority")

    if host_raw is None:
        raise SourceValidationError("URL_HOST_INVALID", "Missing host")

    allowed_port = 80 if scheme == "http" else 443
    if port_raw is not None:
        if port_raw != allowed_port:
            raise SourceValidationError("URL_PORT_FORBIDDEN", f"Non-default port not allowed for {scheme}")
        # default port is stripped

    host_canonical = _normalize_host(host_raw)

    path = parsed.path or ""
    if path == "":
        path = "/"
    path = _remove_dot_segments(path)
    path = _normalize_percent_encoding(path)

    query = parsed.query
    # Preserve the query component exactly as submitted, including byte case,
    # percent escapes, duplicate keys, separators, and order. Empty and absent
    # query components intentionally canonicalize to the same URL.

    netloc = host_canonical  # port is always omitted after validation
    result = f"{scheme}://{netloc}{path}"
    if query:
        result += f"?{query}"
    return result


def build_url_source_key(url: str) -> str:
    """Stable URL identity key: exactly 'url:<canonical-requested-url>'."""
    return f"url:{canonicalize_url(url)}"
