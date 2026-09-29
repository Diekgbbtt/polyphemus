"""#238 A6 - the durable-command redactor.

The per-job stats persist the tool command that ran. That command may embed the
authenticated header or cookie, so it must be redacted BEFORE persistence. The
tests never print the sentinel: a failing assertion names the surface instead.
"""
from __future__ import annotations

from polymerhus.recon.domain.redaction import (
    redact_command,
    secret_values_from_auth_context,
)


def _sentinel() -> str:
    # Assembled from fragments so the value never appears as a literal in the
    # source (and never in a failure message).
    return "e2e" + "-secret-cookie-value"


def test_redact_command_masks_a_flagged_credential_with_no_pattern_key():
    sentinel = _sentinel()
    material = {"cookies": [{"name": "session", "value": sentinel}]}
    secrets = secret_values_from_auth_context(material)

    command = f"curl -b 'session={sentinel}' https://target.example/endpoint"
    redacted = redact_command(command, secrets)

    assert sentinel not in redacted
    assert "[redacted]" in redacted
    # Non-secret material survives so the stored command stays useful.
    assert "https://target.example/endpoint" in redacted


def test_redact_command_masks_an_authorization_header_value():
    sentinel = _sentinel()
    material = {"Authorization": "Bearer " + sentinel}
    secrets = secret_values_from_auth_context(material)

    command = f"httpx -u https://x -H 'Authorization: Bearer {sentinel}'"
    redacted = redact_command(command, secrets)

    assert sentinel not in redacted


def test_secret_values_from_auth_context_collects_headers_and_cookies():
    material = {
        "cookies": [{"name": "sid", "value": "value-one"}],
        "Authorization": "Bearer value-two",
    }
    values = set(secret_values_from_auth_context(material))
    assert "value-one" in values
    # The header's value is the whole string ("Bearer value-two").
    assert "Bearer value-two" in values
    assert set(secret_values_from_auth_context(None)) == set()
