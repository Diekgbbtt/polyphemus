import gzip
import hashlib
import ipaddress
import os
import socket
import ssl
import zlib
from pathlib import Path

import pytest

from polymerhus.ingestion import url_downloader
from polymerhus.ingestion.url_downloader import (
    URLDownloadError,
    DownloadLimits,
    DnsPythonResolver,
    H11PinnedTransport,
    UrlDownloader,
    validate_content_type,
)

PUBLIC_CODES = {
    "URL_INVALID",
    "URL_UNSUPPORTED_SCHEME",
    "URL_CREDENTIALS_FORBIDDEN",
    "URL_HOST_INVALID",
    "URL_PORT_FORBIDDEN",
    "URL_ADDRESS_FORBIDDEN",
    "URL_DNS_NO_ANSWER",
    "URL_DNS_RESOLUTION_FAILED",
    "URL_DNS_MIXED_FORBIDDEN",
    "URL_REDIRECT_LOCATION_MISSING",
    "URL_REDIRECT_LOOP",
    "URL_REDIRECT_LIMIT",
    "URL_TIMEOUT",
    "URL_DOWNLOAD_TOO_LARGE",
    "URL_DECOMPRESSION_LIMIT",
    "URL_HTTP_STATUS",
    "URL_CONTENT_TYPE_UNSUPPORTED",
    "URL_CONTENT_TYPE_AMBIGUOUS",
    "URL_CONTENT_ENCODING_UNSUPPORTED",
    "URL_CONTENT_LENGTH_INVALID",
    "URL_TLS_FAILED",
    "URL_CONNECTION_FAILED",
}


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or []
        self._body = body

    def iter_raw(self, chunk_size):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        pass


class FakeTransport:
    def __init__(self):
        self.requests = []
        self.responses = []

    def request(self, req, **kwargs):
        self.requests.append(req)
        if not self.responses:
            raise AssertionError("No fake response queued")
        status, headers, body = self.responses.pop(0)
        return FakeResponse(status, headers, body)


class FakeResolver:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, host, timeout=None):
        self.calls.append((host, timeout))
        return self.mapping.get(host, [])


def make_downloader(resolver_mapping, transport, **limits):
    limits = DownloadLimits(**limits) if limits else DownloadLimits()
    resolver = FakeResolver(resolver_mapping)
    return UrlDownloader(resolver, transport, limits=limits), resolver


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class FakeRData:
    def __init__(self, address):
        self.address = address


class FakeAnswer:
    def __init__(self, rdatas):
        self._rdatas = list(rdatas)

    def __iter__(self):
        return iter(self._rdatas)


class FakeDnsResolverBackend:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def resolve(self, host, rdtype, lifetime=None, search=True):
        self.calls.append((host, rdtype, lifetime, search))
        response = self.responses.get(rdtype)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(host, rdtype, lifetime)
        return response


def make_dns_downloader(monkeypatch, backend, **limits):
    monkeypatch.setattr(url_downloader.dns.resolver, "Resolver", lambda: backend)
    transport = FakeTransport()
    dl = UrlDownloader(None, transport, limits=DownloadLimits(**limits))
    return dl, transport


@pytest.mark.parametrize("ip", [
    ipaddress.ip_address("127.0.0.1"),
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("10.0.0.1"),
    ipaddress.ip_address("100.64.0.1"),
    ipaddress.ip_address("192.0.2.1"),
    ipaddress.ip_address("0.0.0.0"),
    ipaddress.ip_address("169.254.1.1"),
    ipaddress.ip_address("224.0.0.1"),
])
def test_ipv4_forbidden_categories_rejected(ip):
    transport = FakeTransport()
    dl, _ = make_downloader({"example.com": [ip]}, transport)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_ADDRESS_FORBIDDEN"


@pytest.mark.parametrize("ip", [
    ipaddress.ip_address("::1"),
    ipaddress.ip_address("fe80::1"),
    ipaddress.ip_address("fc00::1"),
    ipaddress.ip_address("2001:db8::1"),
    ipaddress.ip_address("::"),
    ipaddress.ip_address("ff00::1"),
])
def test_ipv6_forbidden_categories_rejected(ip):
    transport = FakeTransport()
    dl, _ = make_downloader({"example.com": [ip]}, transport)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_ADDRESS_FORBIDDEN"


def test_canonical_globally_routable_ipv4_literal_downloaded_directly():
    transport = FakeTransport()
    transport.responses.append((200, [("content-type", "text/html")], b"ok"))
    dl, resolver = make_downloader({}, transport)

    result = dl.download("http://8.8.8.8/")

    assert result.final_url == "http://8.8.8.8/"
    assert transport.requests[0].host == "8.8.8.8"
    assert transport.requests[0].ip == "8.8.8.8"
    assert resolver.calls == []


def test_canonical_globally_routable_ipv6_literal_downloaded_directly():
    transport = FakeTransport()
    transport.responses.append((200, [("content-type", "text/html")], b"ok"))
    dl, resolver = make_downloader({}, transport)

    result = dl.download("http://[2606:4700:4700::1111]/")

    assert result.final_url == "http://[2606:4700:4700::1111]/"
    assert transport.requests[0].host == "2606:4700:4700::1111"
    assert transport.requests[0].ip == "2606:4700:4700::1111"
    assert resolver.calls == []


def test_shorthand_ipv4_rejected_by_downloader():
    dl, _ = make_downloader({}, FakeTransport())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://8.8.2056/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_dword_ipv4_rejected_by_downloader():
    dl, _ = make_downloader({}, FakeTransport())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://134744072/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_octal_leading_zero_ipv4_rejected_by_downloader():
    dl, _ = make_downloader({}, FakeTransport())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://010.010.010.010/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_hexadecimal_ipv4_rejected_by_downloader():
    dl, _ = make_downloader({}, FakeTransport())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://0x08080808/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_canonicalization_reuses_source_identity_and_maps_errors():
    dl = UrlDownloader(FakeResolver({}), FakeTransport(), limits=DownloadLimits())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com:8080/")
    assert exc.value.code == "URL_PORT_FORBIDDEN"


def test_unsupported_scheme_uses_specific_code():
    dl = UrlDownloader(FakeResolver({}), FakeTransport(), limits=DownloadLimits())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("ftp://example.com/file")
    assert exc.value.code == "URL_UNSUPPORTED_SCHEME"


def test_url_credentials_use_specific_code():
    dl = UrlDownloader(FakeResolver({}), FakeTransport(), limits=DownloadLimits())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://user:password@example.com/")
    assert exc.value.code == "URL_CREDENTIALS_FORBIDDEN"


def test_invalid_host_uses_specific_code():
    dl = UrlDownloader(FakeResolver({}), FakeTransport(), limits=DownloadLimits())
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://-invalid.example/")
    assert exc.value.code == "URL_HOST_INVALID"


def test_initial_canonical_url_stays_stable_across_redirects():
    transport = FakeTransport()
    transport.responses.extend(
        [
            (302, [("location", "http://example.org/final")], b""),
            (200, [("content-type", "text/html")], b"ok"),
        ]
    )
    dl, resolver = make_downloader(
        {
            "example.com": [ipaddress.ip_address("93.184.216.34")],
            "example.org": [ipaddress.ip_address("93.184.216.35")],
        },
        transport,
    )
    result = dl.download("http://example.com/start")
    assert result.canonical_url == "http://example.com/start"
    assert result.final_url == "http://example.org/final"
    assert result.redirect_chain == ["http://example.com/start"]
    assert [call[0] for call in resolver.calls] == ["example.com", "example.org"]


def test_reentrant_downloads_do_not_share_mutable_metadata():
    class ReentrantURLTransport:
        def __init__(self):
            self.requests = []
            self.nested_result = None
            self.nested_triggered = False

        def request(self, req, **kwargs):
            self.requests.append(req.url)
            if req.url == "http://example.com/start":
                return FakeResponse(302, [("location", "/final")], b"")
            if req.url == "http://example.com/final":
                if not self.nested_triggered:
                    self.nested_triggered = True
                    self.nested_result = dl.download("http://example.org/inner")
                return FakeResponse(200, [("content-type", "text/html")], b"outer")
            if req.url == "http://example.org/inner":
                return FakeResponse(200, [("content-type", "text/html")], b"inner")
            raise AssertionError(f"unexpected request: {req.url}")

    transport = ReentrantURLTransport()
    resolver = FakeResolver(
        {
            "example.com": [ipaddress.ip_address("93.184.216.34")],
            "example.org": [ipaddress.ip_address("93.184.216.35")],
        }
    )
    dl = UrlDownloader(resolver, transport, limits=DownloadLimits())

    outer = dl.download("http://example.com/start")
    inner = transport.nested_result

    assert inner is not None
    assert inner.requested_url == "http://example.org/inner"
    assert inner.canonical_url == "http://example.org/inner"
    assert inner.final_url == "http://example.org/inner"
    assert inner.redirect_chain == []

    assert outer.requested_url == "http://example.com/start"
    assert outer.canonical_url == "http://example.com/start"
    assert outer.final_url == "http://example.com/final"
    assert outer.redirect_chain == ["http://example.com/start"]


def test_mixed_public_and_forbidden_addresses_rejected():
    transport = FakeTransport()
    dl, _ = make_downloader(
        {
            "example.com": [
                ipaddress.ip_address("93.184.216.34"),
                ipaddress.ip_address("127.0.0.1"),
            ]
        },
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DNS_MIXED_FORBIDDEN"


def test_ipv4_mapped_ipv6_rejected():
    transport = FakeTransport()
    mapped = ipaddress.ip_address("::ffff:10.0.0.1")
    dl, _ = make_downloader({"example.com": [mapped]}, transport)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_ADDRESS_FORBIDDEN"


def test_only_http_200_accepted_for_body():
    for status in (200, 204, 301, 302, 400, 404, 500):
        transport = FakeTransport()
        if status == 200:
            transport.responses.append((200, [("content-type", "text/html")], b"ok"))
            dl, _ = make_downloader(
                {"example.com": [ipaddress.ip_address("93.184.216.34")]},
                transport,
            )
            result = dl.download("http://example.com/")
            assert result.downloaded_bytes == 2
        else:
            transport.responses.append((status, [], b""))
            dl, _ = make_downloader(
                {"example.com": [ipaddress.ip_address("93.184.216.34")]},
                transport,
            )
            with pytest.raises(URLDownloadError) as exc:
                dl.download("http://example.com/")
            if status in (301, 302):
                assert exc.value.code == "URL_REDIRECT_LOCATION_MISSING"
            else:
                assert exc.value.code == "URL_HTTP_STATUS"


def test_strict_content_length_duplicates_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html"), ("content-length", "5"), ("content-length", "6")], b"")
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_LENGTH_INVALID"


def test_content_length_sign_or_whitespace_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-length", " 5")],
            b"",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_LENGTH_INVALID"


def test_extremely_long_content_length_uses_specific_code():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-length", "9" * 5000)],
            b"",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_LENGTH_INVALID"


def test_duplicate_content_type_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-type", "text/html")],
            b"ok",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_INVALID"


def test_duplicate_content_encoding_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [
                ("content-type", "text/html"),
                ("content-encoding", "gzip"),
                ("content-encoding", "gzip"),
            ],
            b"",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_INVALID"


def test_unsupported_content_type_uses_specific_code():
    transport = FakeTransport()
    transport.responses.append((200, [("content-type", "image/png")], b"png"))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/image")
    assert exc.value.code == "URL_CONTENT_TYPE_UNSUPPORTED"


def test_ambiguous_content_type_uses_specific_code():
    transport = FakeTransport()
    transport.responses.append((200, [], b"unknown"))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/document")
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


# ---------------------------------------------------------------------------
# Exact MIME policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content_type, final_url, content_disposition, expected",
    [
        ("text/html", "http://example.com/page", None, None),
        ("application/xhtml+xml", "http://example.com/page", None, None),
        ("text/markdown", "http://example.com/page", None, None),
        ("text/markdown; charset=utf-8", "http://example.com/page", None, None),
        ("text/x-markdown", "http://example.com/page", None, None),
        ("text/plain", "http://example.com/page.md", None, None),
        (
            "text/plain",
            "http://example.com/page",
            'attachment; filename="page.md"',
            None,
        ),
        (
            "text/plain",
            "http://example.com/page.txt",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            None,
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "   ",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "\t",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "; charset=utf-8",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "application/octet-stream",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "text/md",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "application/markdown",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "application/x-markdown",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_AMBIGUOUS",
        ),
        (
            "image/png",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_UNSUPPORTED",
        ),
        (
            "application/pdf",
            "http://example.com/page.md",
            None,
            "URL_CONTENT_TYPE_UNSUPPORTED",
        ),
    ],
)
def test_exact_mime_policy_matrix(
    content_type,
    final_url,
    content_disposition,
    expected,
):
    if expected is None:
        validate_content_type(final_url, content_type, content_disposition)
    else:
        with pytest.raises(URLDownloadError) as exc:
            validate_content_type(final_url, content_type, content_disposition)
        assert exc.value.code == expected


@pytest.mark.parametrize(
    "content_disposition",
    [
        'filename="page.md"',
        'attachment; filename="page.md"',
        'attachment;  filename = "page.md"',
        "attachment; filename='page.md'",
        "attachment; filename=page.md",
        'attachment; filename="semi;colon.md"',
        'attachment; FILENAME="page.md"',
        'attachment; x=1; filename="page.md"',
        "attachment; filename*=UTF-8''page.md",
        "attachment; filename*=utf-8''page%2Emd",
        "attachment; filename*=UTF-8'en'page.md",
    ],
)
def test_content_disposition_accepts_exact_filename_parameters(
    content_disposition,
):
    validate_content_type(
        "http://example.com/page",
        "text/plain",
        content_disposition,
    )


@pytest.mark.parametrize(
    "content_disposition",
    [
        'attachment; xfilename="page.md"',
        'attachment; notfilename="page.md"',
        'attachment; myfilename="page.md"',
        'attachment; filename0="page.md"',
        'attachment; filename-x="page.md"',
        'attachment; filename*0=page.md',
        "attachment; xfilename*=UTF-8''page.md",
        "attachment; filename",
        "attachment; filename=",
        "attachment; filename*=UTF-8''",
        'attachment; filename="page.md',
        "attachment; filename='page.md",
        'attachment; filename="page.md" extra',
        'attachment; filename=; filename="page.md"',
        'attachment; note="see filename=page.md"',
        "attachment; filename*=page.md",
        "attachment; filename*=UTF-8'page.md",
        "attachment; filename*='page.md",
        "attachment; filename*=UTF-8''page%ZZ.md",
        "attachment; filename*=UTF-8''page%2.md",
        "attachment; filename*=UTF-8''page%",
        "attachment; filename*=ISO-8859-1''page.md",
        "attachment; filename*=UTF-8''page%FF.md",
        'attachment; filename*="UTF-8\'\'page.md"',
        "attachment; filename*=UTF-8''page\x01.md",
    ],
)
def test_content_disposition_rejects_non_exact_or_malformed_parameters(
    content_disposition,
):
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type(
            "http://example.com/page",
            "text/plain",
            content_disposition,
        )
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


@pytest.mark.parametrize(
    "content_disposition, expected",
    [
        # Valid extended values are only evidence when the decoded filename
        # carries a Markdown suffix.
        ("attachment; filename*=UTF-8''page.md", None),
        ("attachment; filename*=utf-8''page%2Emd", None),
        ("attachment; filename*=UTF-8''%70%61%67%65%2E%6D%64", None),
        ("attachment; filename*=UTF-8''page.txt", "URL_CONTENT_TYPE_AMBIGUOUS"),
        # Malformed values never independently justify Markdown.
        ("attachment; filename*=page.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8'page.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8''page%ZZ.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8''page%2.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8''page%", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=ISO-8859-1''page.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8''page%FF.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ('attachment; filename*="UTF-8\'\'page.md"', "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*=UTF-8''", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; xfilename*=UTF-8''page.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
        ("attachment; filename*0=UTF-8''page.md", "URL_CONTENT_TYPE_AMBIGUOUS"),
    ],
)
def test_extended_filename_is_strict_utf8_evidence_only(
    content_disposition,
    expected,
):
    if expected is None:
        validate_content_type(
            "http://example.com/page",
            "text/plain",
            content_disposition,
        )
    else:
        with pytest.raises(URLDownloadError) as exc:
            validate_content_type(
                "http://example.com/page",
                "text/plain",
                content_disposition,
            )
        assert exc.value.code == expected


def test_declared_unsupported_mime_rejected_even_with_valid_extended_filename():
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type(
            "http://example.com/page",
            "image/png",
            "attachment; filename*=UTF-8''page.md",
        )
    assert exc.value.code == "URL_CONTENT_TYPE_UNSUPPORTED"


# ---------------------------------------------------------------------------
# Milestone 4 remediation: strict, order-independent filename evidence (M1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_disposition",
    [
        # A valid plain filename must not mask malformed extended evidence.
        'attachment; filename="page.md"; filename*=UTF-8\'\'page%ZZ.md',
        # Malformed extended evidence first, valid plain filename second.
        "attachment; filename*=UTF-8''page%ZZ.md; filename=\"page.md\"",
        # Percent-encoded C1 control character (U+0085) in decoded evidence.
        "attachment; filename*=UTF-8''page%C2%85.md",
        # Conflicting plain/extended evidence in either parameter order.
        'attachment; filename="page.md"; filename*=UTF-8\'\'page.txt',
        "attachment; filename*=UTF-8''page.md; filename=\"page.txt\"",
    ],
)
def test_content_disposition_unreliable_mixed_evidence_is_ambiguous(content_disposition):
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type("http://example.com/page", "text/plain", content_disposition)
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


@pytest.mark.parametrize(
    "content_disposition",
    [
        # Percent-encoded C1 control characters.
        "attachment; filename*=UTF-8''page%C2%80.md",
        "attachment; filename*=UTF-8''page%C2%9F.md",
        # Raw decoded control characters in extended evidence.
        "attachment; filename*=UTF-8''page\x1b.md",
        # Raw decoded control characters in plain evidence.
        'attachment; filename="page\x01.md"',
        "attachment; filename=page\x85.md",
    ],
)
def test_content_disposition_rejects_decoded_control_characters(content_disposition):
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type("http://example.com/page", "text/plain", content_disposition)
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


@pytest.mark.parametrize(
    "content_disposition",
    [
        'attachment; filename="page.md"; filename*=UTF-8\'\'page.md',
        "attachment; filename*=UTF-8''page.md; filename=\"page.md\"",
    ],
)
def test_content_disposition_consistent_evidence_accepted_in_either_order(content_disposition):
    validate_content_type("http://example.com/page", "text/plain", content_disposition)


# ---------------------------------------------------------------------------
# Milestone 4 remediation: deterministic MIME evidence (conflicts and controls)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("final_url", "content_disposition"),
    [
        ("http://example.com/page.md", 'attachment; filename="page.txt"'),
        ("http://example.com/page.md", "attachment; filename*=UTF-8''page.txt"),
        ("http://example.com/page.markdown", 'attachment; filename="page.txt"'),
        ("http://example.com/page.txt", 'attachment; filename="page.md"'),
        ("http://example.com/page.txt", "attachment; filename*=UTF-8''page.md"),
        ("http://example.com/page.md", 'attachment; filename="page.md.txt"'),
        ("http://example.com/page.md.txt", 'attachment; filename="page.md"'),
    ],
)
def test_text_plain_conflicting_url_and_disposition_filenames_are_ambiguous(
    final_url, content_disposition
):
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type(final_url, "text/plain", content_disposition)
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


@pytest.mark.parametrize(
    ("final_url", "content_disposition"),
    [
        ("http://example.com/page.md", 'attachment; filename="page.md"'),
        ("http://example.com/page.md", "attachment; filename*=UTF-8''page.md"),
        ("http://example.com/page.markdown", 'attachment; filename="page.md"'),
    ],
)
def test_text_plain_consistent_url_and_disposition_filenames_accepted(
    final_url, content_disposition
):
    validate_content_type(final_url, "text/plain", content_disposition)


@pytest.mark.parametrize(
    "final_url",
    [
        "http://example.com/page%C2%85.md",
        "http://example.com/page%00.md",
        "http://example.com/page%1B.md",
        "http://example.com/page%C2%9F.md",
        "http://example.com/page%7F.md",
    ],
)
def test_text_plain_control_containing_decoded_url_filename_is_not_markdown_evidence(
    final_url,
):
    with pytest.raises(URLDownloadError) as exc:
        validate_content_type(final_url, "text/plain", None)
    assert exc.value.code == "URL_CONTENT_TYPE_AMBIGUOUS"


def test_text_plain_control_containing_url_filename_does_not_conflict_with_disposition():
    validate_content_type(
        "http://example.com/page%C2%85.md",
        "text/plain",
        'attachment; filename="page.md"',
    )


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain; charset=utf-8",
        "text/plain;charset=utf-8",
        "text/markdown; charset=UTF-8",
        "text/x-markdown;charset=iso-8859-1",
    ],
)
def test_content_type_standard_charset_parameter_is_parsed_as_media_type(content_type):
    validate_content_type("http://example.com/page.md", content_type, None)


def test_unsupported_content_encoding_uses_specific_code():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "br")],
            b"encoded",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_ENCODING_UNSUPPORTED"


def test_content_length_short_body_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-length", "10")],
            b"short",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_LENGTH_INVALID"


def test_content_length_long_body_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-length", "2")],
            b"longer",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_CONTENT_LENGTH_INVALID"


def test_gzip_bounded_decoding_and_decompression_limit():
    raw = b"hello world" * 100
    compressed = gzip.compress(raw)
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "gzip")],
            compressed,
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_decoded_bytes=500,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DECOMPRESSION_LIMIT"


def test_deflate_bounded_decoding_and_decompression_limit():
    raw = b"hello world" * 100
    compressed = zlib.compress(raw)
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "deflate")],
            compressed,
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_decoded_bytes=500,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DECOMPRESSION_LIMIT"


def test_malformed_deflate_returns_stable_error():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "deflate")],
            b"\x00\x01\x02\x03",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_INVALID"


def test_truncated_gzip_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "gzip")],
            gzip.compress(b"hello")[:-2],
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_INVALID"


def test_gzip_with_unused_data_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "gzip")],
            gzip.compress(b"hello") + b"EXTRA",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_INVALID"


def test_part_cleanup_on_failure(tmp_path):
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-encoding", "gzip")],
            gzip.compress(b"ok" * 100),
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_decoded_bytes=10,
    )
    with pytest.raises(URLDownloadError):
        dl.download("http://example.com/", artifact_dir=tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_artifact_finalization_cleanup_on_os_replace_failure(tmp_path, monkeypatch):
    import os as _os

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(_os, "replace", fail_replace)
    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html")], b"hello artifact")
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/", artifact_dir=tmp_path)
    assert exc.value.code == "URL_INVALID"
    assert not list(tmp_path.glob("*.part"))
    assert not list(tmp_path.glob("*"))


def test_successful_metadata_sha256_and_artifact(tmp_path):
    body = b"<html>hello</html>"
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [
                ("content-type", "text/html; charset=utf-8"),
                ("etag", "abc123"),
                ("last-modified", "Wed, 21 Oct 2026 07:28:00 GMT"),
            ],
            body,
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    result = dl.download(
        "http://example.com/index.html",
        artifact_dir=tmp_path,
    )
    assert result.content_type == "text/html; charset=utf-8"
    assert result.etag == "abc123"
    assert result.last_modified == "Wed, 21 Oct 2026 07:28:00 GMT"
    assert result.downloaded_bytes == len(body)
    assert result.sha256 == sha256(body)
    assert result.raw_artifact_path
    assert Path(result.raw_artifact_path).read_bytes() == body
    assert result.requested_url == "http://example.com/index.html"
    assert result.canonical_url == "http://example.com/index.html"
    assert result.final_url == "http://example.com/index.html"
    assert result.redirect_chain == []


def test_valid_markdown_download(tmp_path):
    body = b"# Title\n\nsome markdown"
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [
                ("content-type", "text/markdown"),
                ("content-disposition", "attachment; filename=\"test.md\""),
            ],
            body,
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    result = dl.download("http://example.com/test.md", artifact_dir=tmp_path)
    assert result.content_type == "text/markdown"
    assert result.downloaded_bytes == len(body)
    assert result.sha256 == sha256(body)


def test_h11_pinned_transport_connects_to_numeric_ip_only(monkeypatch):
    seen = {}

    def fake_create_connection(address, timeout=None):
        seen["address"] = address
        raise URLDownloadError("URL_TIMEOUT")

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)
    transport = H11PinnedTransport(
        connect_timeout=1,
        read_timeout=1,
        stream_chunk_size=64 * 1024,
    )
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TIMEOUT"
    assert seen["address"] == ("93.184.216.34", 80)
    assert "example.com" not in repr(seen["address"])


def test_https_sni_uses_original_hostname(monkeypatch):
    transport = H11PinnedTransport(
        connect_timeout=1,
        read_timeout=1,
        stream_chunk_size=64 * 1024,
    )
    seen = {}

    class DummySocket:
        def settimeout(self, timeout):
            pass

        def close(self):
            pass

    class DummySSLContext:
        def wrap_socket(self, sock, server_hostname):
            seen["server_hostname"] = server_hostname
            raise ssl.SSLError

    def fake_create_connection(address, timeout=None):
        return DummySocket()

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(
        url_downloader.ssl, "create_default_context", lambda: DummySSLContext()
    )

    req = url_downloader.TransportRequest(
        url="https://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=443,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TLS_FAILED"
    assert seen["server_hostname"] == "example.com"


def test_h11_request_followed_by_end_of_message(monkeypatch):
    sent_items = []

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            self._sent = sent_items

        def send(self, item):
            self._sent.append(item)
            return b"payload"

        def next_event(self):
            return url_downloader.h11.NEED_DATA

    class DummySocket:
        def __init__(self):
            self.sent = []
            self.timeout = None
            self.closed = False

        def settimeout(self, timeout):
            self.timeout = timeout

        def send(self, data):
            self.sent.append(data)
            return len(data)

        def recv(self, chunk_size):
            raise socket.timeout

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        url_downloader.h11,
        "Connection",
        FakeConnection,
    )
    monkeypatch.setattr(
        url_downloader.socket,
        "create_connection",
        lambda address, timeout=None: DummySocket(),
    )

    transport = H11PinnedTransport(
        connect_timeout=1,
        read_timeout=1,
        stream_chunk_size=64 * 1024,
    )
    req = url_downloader.TransportRequest(
        url="http://example.com/a?b=1",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)

    assert len(sent_items) == 2
    assert isinstance(sent_items[0], url_downloader.h11.Request)
    assert isinstance(sent_items[1], url_downloader.h11.EndOfMessage)
    assert exc.value.code == "URL_TIMEOUT"


def test_explicit_empty_query_target(monkeypatch):
    transport = H11PinnedTransport(
        connect_timeout=1,
        read_timeout=1,
        stream_chunk_size=64 * 1024,
    )

    captured = {}

    class DummySocket:
        def settimeout(self, timeout):
            pass

        def send(self, data):
            captured["data"] = data
            return len(data)

        def recv(self, chunk_size):
            raise socket.timeout

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, item):
            if isinstance(item, url_downloader.h11.Request):
                captured["target"] = item.target
            return b""

    monkeypatch.setattr(url_downloader.socket, "create_connection", lambda *a, **k: DummySocket())
    monkeypatch.setattr(url_downloader.h11, "Connection", FakeConnection)

    req = url_downloader.TransportRequest(
        url="http://example.com/path?",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError):
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert captured["target"] == b"/path?"


def test_connect_timeout_maps_to_url_timeout(monkeypatch):
    def fake_sleep(*args, **kwargs):
        raise socket.timeout

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_sleep)

    transport = H11PinnedTransport(
        connect_timeout=0.5,
        read_timeout=1,
        stream_chunk_size=64 * 1024,
    )
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TIMEOUT"


def test_read_timeout_maps_to_url_timeout(monkeypatch):
    def fake_create_connection(address, timeout=None):
        class DummySocket:
            def settimeout(self, timeout):
                pass

            def send(self, data):
                return len(data)

            def recv(self, chunk_size):
                raise socket.timeout

            def close(self):
                pass

        return DummySocket()

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)
    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TIMEOUT"


def test_total_timeout_maps_to_url_timeout_during_connection(monkeypatch):
    def fake_create_connection(address, timeout=None):
        return object()

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)
    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=0.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TIMEOUT"


def test_socket_failure_mapping_and_cleanup(monkeypatch):
    closed = {}

    class DummySocket:
        def __init__(self):
            self.closed = False

        def settimeout(self, timeout):
            pass

        def send(self, data):
            raise OSError("broken pipe")

        def close(self):
            self.closed = True
            closed["closed"] = True

    def fake_create_connection(address, timeout=None):
        return DummySocket()

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)

    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_CONNECTION_FAILED"
    assert closed.get("closed") is True


def test_default_download_limits_use_config_values(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "password")
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://user:pass@localhost/test")
    monkeypatch.setenv("KALI_MCP_URL", "http://kali:8000")

    from polymerhus.app.config import config as app_config

    monkeypatch.setattr(app_config, "URL_DOWNLOAD_CONNECT_TIMEOUT", 1.5)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_READ_TIMEOUT", 2.5)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_TOTAL_TIMEOUT", 3.5)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_MAX_REDIRECTS", 4)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_MAX_WIRE_BYTES", 5000)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_MAX_DECODED_BYTES", 6000)
    monkeypatch.setattr(app_config, "URL_DOWNLOAD_STREAM_CHUNK_SIZE", 7000)

    dl = UrlDownloader(FakeResolver({}), FakeTransport())
    assert dl._limits == DownloadLimits(
        connect_timeout=1.5,
        read_timeout=2.5,
        total_timeout=3.5,
        max_redirects=4,
        max_wire_bytes=5000,
        max_decoded_bytes=6000,
        stream_chunk_size=7000,
    )


def test_default_downloader_builds_configured_h11_pinned_transport():
    limits = DownloadLimits(
        connect_timeout=1.25,
        read_timeout=2.5,
        total_timeout=3.75,
        max_redirects=4,
        max_wire_bytes=5000,
        max_decoded_bytes=6000,
        stream_chunk_size=7000,
    )

    dl = UrlDownloader(limits=limits)

    assert isinstance(dl._transport, H11PinnedTransport)
    assert dl._transport.connect_timeout == 1.25
    assert dl._transport.read_timeout == 2.5
    assert dl._transport.stream_chunk_size == 7000


def test_float_env_rejects_nan_and_infinity(monkeypatch):
    from polymerhus.app import config as config_module

    for bad in ("nan", "inf", "-inf"):
        monkeypatch.setenv("TEST_FLOAT_ENV", bad)
        with pytest.raises(ValueError) as exc:
            config_module._float_env("TEST_FLOAT_ENV", 1.0)
        assert "finite" in str(exc.value)


def test_redirect_limit_respected():
    transport = FakeTransport()
    for location in ("/one", "/two", "/three"):
        transport.responses.append((302, [("location", location)], b""))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_redirects=2,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_REDIRECT_LIMIT"


def test_redirect_loop_detected():
    transport = FakeTransport()
    transport.responses.extend(
        [
            (302, [("location", "/loop")], b""),
            (302, [("location", "/start")], b""),
            (200, [("content-type", "text/html")], b"ok"),
        ]
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_redirects=5,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/start")
    assert exc.value.code == "URL_REDIRECT_LOOP"


def test_redirect_to_forbidden_private_target_rejected():
    transport = FakeTransport()
    transport.responses.append(
        (302, [("location", "http://127.0.0.1/")], b"")
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_ADDRESS_FORBIDDEN"


def test_resolver_output_flows_to_pinned_transport():
    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html")], b"ok")
    )
    resolver_ip = "93.184.216.34"
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address(resolver_ip)]},
        transport,
    )
    dl.download("http://example.com/")
    req = transport.requests[0]
    assert req.ip == resolver_ip
    assert req.host == "example.com"
    assert req.port == 80


def test_genuinely_bounded_dns_timeout():
    class RaiseTimeoutResolver:
        def __call__(self, host, timeout):
            if timeout <= 0:
                raise URLDownloadError("URL_TIMEOUT")
            raise TimeoutError("resolver blocked")

    dl = UrlDownloader(
        RaiseTimeoutResolver(),
        FakeTransport(),
        limits=DownloadLimits(total_timeout=0.1),
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_TIMEOUT"


def test_declared_too_large_content_length_identity():
    transport = FakeTransport()
    transport.responses.append(
        (
            200,
            [("content-type", "text/html"), ("content-length", "999999999")],
            b"",
        )
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_wire_bytes=100,
        max_decoded_bytes=100,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DOWNLOAD_TOO_LARGE"


def test_uncompressed_streamed_wire_limit():
    body = b"x" * 500
    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html")], body)
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_wire_bytes=100,
        max_decoded_bytes=1000,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DOWNLOAD_TOO_LARGE"


def test_uncompressed_streamed_decoded_limit():
    body = b"x" * 500
    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html")], body)
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
        max_wire_bytes=1000,
        max_decoded_bytes=100,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DOWNLOAD_TOO_LARGE"


def test_redirect_resolved_against_previous_canonical():
    transport = FakeTransport()
    transport.responses.extend(
        [
            (302, [("location", "/next")], b""),
            (200, [("content-type", "text/html")], b"ok"),
        ]
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    dl.download("HTTP://EXAMPLE.COM:80/start")
    first_req_url = transport.requests[0].url
    second_req_url = transport.requests[1].url
    assert first_req_url == "http://example.com/start"
    assert second_req_url == "http://example.com/next"


def test_all_emitted_codes_are_allowed():
    scenarios = []

    def capture(code):
        scenarios.append(code)

    transport = FakeTransport()

    def scenario_redirect_missing_location():
        transport.responses.append((302, [], b""))
        dl, _ = make_downloader(
            {"example.com": [ipaddress.ip_address("93.184.216.34")]},
            transport,
        )
        try:
            dl.download("http://example.com/")
        except URLDownloadError as exc:
            capture(exc.code)

    def scenario_bad_url():
        dl = UrlDownloader(FakeResolver({}), FakeTransport(), limits=DownloadLimits())
        try:
            dl.download("http://example.com:8080/")
        except URLDownloadError as exc:
            capture(exc.code)

    def scenario_content_length_mismatch():
        transport.responses.append(
            (200, [("content-type", "text/html"), ("content-length", "4")], b"short")
        )
        dl, _ = make_downloader(
            {"example.com": [ipaddress.ip_address("93.184.216.34")]},
            transport,
        )
        try:
            dl.download("http://example.com/")
        except URLDownloadError as exc:
            capture(exc.code)

    scenario_redirect_missing_location()
    scenario_bad_url()
    scenario_content_length_mismatch()

    assert len(scenarios) == 3
    for code in scenarios:
        assert code in PUBLIC_CODES


def test_raw_filesystem_error_never_escapes(tmp_path):
    class ExplodingResponse:
        status_code = 200
        headers = [("content-type", "text/html")]

        def iter_raw(self, chunk_size):
            yield b"some"
            raise OSError("disk error")

        def close(self):
            pass

    class ExplodingTransport:
        def request(self, req, **kwargs):
            return ExplodingResponse()

    dl = UrlDownloader(
        FakeResolver({"example.com": [ipaddress.ip_address("93.184.216.34")]}),
        ExplodingTransport(),
        limits=DownloadLimits(),
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/", artifact_dir=tmp_path)
    assert exc.value.code in PUBLIC_CODES
    assert not list(tmp_path.glob("*.part"))


def test_raw_socket_ssl_h11_errors_never_escape(monkeypatch):
    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)

    def fake_create_connection(address, timeout=None):
        raise OSError("raw socket failure")

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)

    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_CONNECTION_FAILED"


def test_dns_lifetime_is_passed_to_dnspython_backend(monkeypatch):
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = FakeAnswer([FakeRData("93.184.216.34")])
    backend.responses["AAAA"] = FakeAnswer([FakeRData("2606:2800:220:1::1")])
    dl, transport = make_dns_downloader(monkeypatch, backend)
    transport.responses.append((200, [("content-type", "text/html")], b"ok"))
    dl.download("http://example.com/")
    assert len(backend.calls) == 2
    assert backend.calls[0][3] is False  # search
    assert backend.calls[1][3] is False


def test_dns_no_answer_maps_to_no_answer_code(monkeypatch):
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = url_downloader.dns.resolver.NoAnswer()
    backend.responses["AAAA"] = url_downloader.dns.resolver.NoAnswer()
    dl, _ = make_dns_downloader(monkeypatch, backend)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DNS_NO_ANSWER"


def test_dns_resolution_failure_maps_to_failure_code(monkeypatch):
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = url_downloader.dns.resolver.NoNameservers()
    backend.responses["AAAA"] = url_downloader.dns.resolver.NoNameservers()
    dl, _ = make_dns_downloader(monkeypatch, backend)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_DNS_RESOLUTION_FAILED"


def test_dns_lifetime_timeout_maps_to_timeout_code(monkeypatch):
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = url_downloader.dns.resolver.LifetimeTimeout()
    backend.responses["AAAA"] = url_downloader.dns.resolver.LifetimeTimeout()
    dl, _ = make_dns_downloader(monkeypatch, backend)
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_TIMEOUT"


def test_combined_a_and_aaaa_results_are_deduplicated(monkeypatch):
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = FakeAnswer([
        FakeRData("93.184.216.34"),
        FakeRData("93.184.216.34"),
    ])
    backend.responses["AAAA"] = FakeAnswer([
        FakeRData("2606:2800:220:1::1"),
    ])
    resolver = DnsPythonResolver(resolver_factory=lambda: backend)
    result = resolver("example.com", 5.0)
    assert len(result) == 2
    assert ipaddress.ip_address("93.184.216.34") in result
    assert ipaddress.ip_address("2606:2800:220:1::1") in result


def test_total_dns_lifetime_shared_across_a_and_aaaa(monkeypatch):
    backend = FakeDnsResolverBackend()
    clock_values = iter([0.0, 0.0, 0.1, 0.1])
    resolver = DnsPythonResolver(
        resolver_factory=lambda: backend,
        clock=lambda: next(clock_values),
    )
    backend.responses["A"] = FakeAnswer([FakeRData("93.184.216.34")])
    backend.responses["AAAA"] = FakeAnswer([FakeRData("2606:2800:220:1::1")])
    resolver("example.com", 1.0)
    assert len(backend.calls) == 2
    assert backend.calls[0][2] == 1.0
    assert backend.calls[1][2] == 0.9


def test_stalled_tls_timeout_maps_to_timeout(monkeypatch):
    class DummySocket:
        def settimeout(self, timeout):
            pass

        def send(self, data):
            return len(data)

        def recv(self, chunk_size):
            raise socket.timeout

        def close(self):
            pass

    class DummySSLContext:
        def wrap_socket(self, sock, server_hostname):
            return DummySocket()

    def fake_create_connection(address, timeout=None):
        return DummySocket()

    monkeypatch.setattr(url_downloader.socket, "create_connection", fake_create_connection)
    monkeypatch.setattr(url_downloader.ssl, "create_default_context", lambda: DummySSLContext())
    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)
    req = url_downloader.TransportRequest(
        url="https://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=443,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_TIMEOUT"


def test_h11_protocol_failure_maps_to_connection_failed(monkeypatch):
    class DummySocket:
        def settimeout(self, timeout):
            pass

        def send(self, data):
            return len(data)

        def recv(self, chunk_size):
            raise socket.timeout

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, item):
            return b""

        def next_event(self):
            raise url_downloader.h11.RemoteProtocolError("bad protocol")

    monkeypatch.setattr(url_downloader.socket, "create_connection", lambda *a, **k: DummySocket())
    monkeypatch.setattr(url_downloader.h11, "Connection", FakeConnection)
    transport = H11PinnedTransport(connect_timeout=1, read_timeout=1, stream_chunk_size=64 * 1024)
    req = url_downloader.TransportRequest(
        url="http://example.com/",
        method="GET",
        headers={},
        host="example.com",
        port=80,
        ip="93.184.216.34",
    )
    with pytest.raises(URLDownloadError) as exc:
        transport.request(req, deadline=10.0, clock=lambda: 0.0)
    assert exc.value.code == "URL_CONNECTION_FAILED"


def test_redirect_close_failure_does_not_escape(tmp_path):
    class CloseRaisesResponse(FakeResponse):
        def close(self):
            raise OSError("close failed")

    class CloseRaisesTransport(FakeTransport):
        def request(self, req, **kwargs):
            self.requests.append(req)
            return CloseRaisesResponse(302, [("location", "/next")], b"")

    transport = CloseRaisesTransport()
    transport.responses.append((302, [("location", "/next")], b""))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code in PUBLIC_CODES


def test_redirect_to_relative_empty_query_preserves_request_url():
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", "/next?")], b""),
        (200, [("content-type", "text/html")], b"ok"),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    result = dl.download("http://example.com/start")
    assert transport.requests[1].url == "http://example.com/next?"
    assert result.final_url == "http://example.com/next"
    assert result.redirect_chain == ["http://example.com/start"]


def test_initial_empty_query_preserved_in_request_url():
    transport = FakeTransport()
    transport.responses.append((200, [("content-type", "text/html")], b"ok"))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    result = dl.download("http://example.com/path?")
    assert transport.requests[0].url == "http://example.com/path?"
    assert result.requested_url == "http://example.com/path?"
    assert result.canonical_url == "http://example.com/path"
    assert result.final_url == "http://example.com/path"


def test_missing_redirect_location_uses_specific_code():
    transport = FakeTransport()
    transport.responses.append((302, [], b""))
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/")
    assert exc.value.code == "URL_REDIRECT_LOCATION_MISSING"


def test_dns_python_resolver_iterates_rdata_directly():
    backend = FakeDnsResolverBackend()
    backend.responses["A"] = FakeAnswer([FakeRData("93.184.216.34")])
    backend.responses["AAAA"] = FakeAnswer([FakeRData("2606:2800:220:1::1")])
    resolver = DnsPythonResolver(resolver_factory=lambda: backend)
    result = resolver("example.com", 5.0)
    assert len(result) == 2
    assert ipaddress.ip_address("93.184.216.34") in result
    assert ipaddress.ip_address("2606:2800:220:1::1") in result


@pytest.mark.parametrize("location", ["?", "?#fragment"])
def test_query_only_redirect_clears_previous_query(location):
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", location)], b""),
        (200, [("content-type", "text/html")], b"ok"),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    result = dl.download("http://example.com/start?old=1")
    assert transport.requests[1].url == "http://example.com/start?"
    assert result.final_url == "http://example.com/start"
    assert result.redirect_chain == ["http://example.com/start?old=1"]


def test_nonempty_query_ending_in_question_mark_is_not_an_empty_query():
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", "?x=1?")], b""),
        (200, [("content-type", "text/html")], b"ok"),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )

    result = dl.download("http://example.com/start?old=1")

    assert transport.requests[1].url == "http://example.com/start?x=1?"
    assert result.final_url == "http://example.com/start?x=1?"


def test_redirect_from_path_to_explicit_empty_query_is_redirect_loop():
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", "/start?")], b""),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )

    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/start")

    assert exc.value.code == "URL_REDIRECT_LOOP"
    assert [request.url for request in transport.requests] == [
        "http://example.com/start",
    ]


def test_redirect_chain_treats_empty_and_absent_queries_identically():
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", "/middle?")], b""),
        (302, [("location", "/final")], b""),
        (200, [("content-type", "text/html")], b"ok"),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )

    result = dl.download("http://example.com/start")

    assert [request.url for request in transport.requests] == [
        "http://example.com/start",
        "http://example.com/middle?",
        "http://example.com/final",
    ]
    assert result.final_url == "http://example.com/final"
    assert result.redirect_chain == [
        "http://example.com/start",
        "http://example.com/middle",
    ]


@pytest.mark.parametrize("location", ["/start", "/start?"])
def test_loop_detection_treats_empty_and_absent_queries_identically(location):
    transport = FakeTransport()
    transport.responses.extend([
        (302, [("location", "/start?")], b""),
        (302, [("location", location)], b""),
    ])
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )

    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/start")

    assert exc.value.code == "URL_REDIRECT_LOOP"
    assert [request.url for request in transport.requests] == [
        "http://example.com/start",
    ]


def test_fdopen_failure_closes_raw_descriptor_and_cleans_part(tmp_path, monkeypatch):
    captured = {}

    def fake_fdopen(fd, mode="wb"):
        captured["fd"] = fd
        raise OSError("fdopen failed")

    monkeypatch.setattr(url_downloader.os, "fdopen", fake_fdopen)

    transport = FakeTransport()
    transport.responses.append(
        (200, [("content-type", "text/html")], b"hello artifact")
    )
    dl, _ = make_downloader(
        {"example.com": [ipaddress.ip_address("93.184.216.34")]},
        transport,
    )
    with pytest.raises(URLDownloadError) as exc:
        dl.download("http://example.com/", artifact_dir=tmp_path)
    assert exc.value.code in PUBLIC_CODES
    with pytest.raises(OSError):
        os.fstat(captured["fd"])
    assert not list(tmp_path.glob("*.part"))
