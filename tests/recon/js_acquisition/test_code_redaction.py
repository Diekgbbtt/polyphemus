from pathlib import Path

from polymerhus.recon.js_acquisition.code_redaction import (
    REDACTION_POLICY_ID,
    prepare_redaction,
    redact_window,
)


def test_redacts_secret_literals_queries_comments_and_boundary_fragments():
    source = (
        'const safe = localStorage.getItem("token");\n'
        'const password = "correct-horse-battery-staple";\n'
        '// Authorization: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\n'
        'fetch("/api/items?access_token=SUPERSECRETVALUE&view=full");\n'
        'const longSecret = "'
        + "A" * 5000
        + '";\n'
        'const api = "https://user:pass@example.test/v1?key=SECRETKEY";\n'
    ).encode()

    first = redact_window(source, 0, 120)
    second = redact_window(source, 120, 240)
    middle = redact_window(source, 2500, 2600)
    end = redact_window(source, len(source) - 180, len(source))
    combined = first.display + second.display + middle.display + end.display

    assert first.policy_id == REDACTION_POLICY_ID
    assert 'localStorage.getItem("token")' in first.display
    assert "correct-horse-battery-staple" not in combined
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in combined
    assert "SUPERSECRETVALUE" not in combined
    assert "SECRETKEY" not in combined
    assert "user:pass@" not in combined
    assert "AAAAAAAAAA" not in middle.display
    assert "/api/items" in combined
    assert "access_token=[REDACTED:secret]" in combined
    assert first.redaction_count + second.redaction_count + middle.redaction_count + end.redaction_count >= 5


def test_redaction_uses_original_utf8_offsets_and_preserves_window_metadata():
    source = (
        "const emoji = '😀';\r\n"
        "const cookie = 'session=PRIVATE_COOKIE_VALUE';\r\n"
        "const route = '/api/安全?token=秘密';\r\n"
    ).encode()
    start = source.index("const cookie".encode())
    route_start = source.index("const route".encode())
    end = source.index(b"\r\n", route_start) + 2

    window = redact_window(source, start, end)

    assert window.original_start == start
    assert window.original_end == end
    assert "PRIVATE_COOKIE_VALUE" not in window.display
    assert "秘密" not in window.display
    assert "/api/安全" in window.display
    assert window.original_sha256


def test_empty_window_is_valid_and_does_not_claim_redaction():
    window = redact_window(b"", 0, 0)

    assert window.display == ""
    assert window.original_start == window.original_end == 0
    assert window.redaction_count == 0


def test_repository_fixture_tokens_do_not_leak_from_sliced_windows():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "data/js-analysis-mvp-eval/bundle-structure-comparison/fixtures/esm-controlled.js"
    )
    source = fixture.read_bytes()
    windows = [
        redact_window(source, offset, min(len(source), offset + 37))
        for offset in range(0, len(source), 37)
    ]
    rendered = "".join(window.display for window in windows)
    for marker in ("secret-in-query", "sensitive-token"):
        if marker.encode() in source:
            assert marker not in rendered


def test_prepared_redaction_matches_compatible_window_interface():
    source = (
        "const emoji = '😀';\r\n"
        'const password = "' + ("P" * 6000) + '";\r\n'
        "const route = '/api/安全?token=秘密';\r\n"
    ).encode()
    prepared = prepare_redaction(source)
    ranges = [
        (0, min(len(source), 80)),
        (source.index(b"const password"), source.index(b"const password") + 120),
        (len(source) - 90, len(source)),
    ]

    for start, end in ranges:
        comparable = redact_window(source, start, end)
        optimized = prepared.window(start, end)
        assert optimized == comparable
        assert "PPPPPPPPPP" not in optimized.display
        assert "秘密" not in optimized.display


def test_prepared_redaction_reuses_spans_without_mutating_source():
    source = b"const token = 'SECRET';\r\nconst x = 1;\r\n"
    before = source
    prepared = prepare_redaction(source)
    first = prepared.window(0, 20)
    second = prepared.window(10, len(source))

    assert source == before
    assert prepared.policy_id == REDACTION_POLICY_ID
    assert first.redaction_count == 1
    assert second.redaction_count == 1
    assert "SECRET" not in first.display + second.display
