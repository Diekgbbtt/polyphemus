"""#238 A6 - redact credential material out of durable command strings.

The per-job `recon_jobs.stats["commands"]` records the tool command that ran.
That command can embed the authenticated header or cookie (for example
`-H 'Authorization: Bearer ...'` or `-b 'session=...'`), which must never be
persisted. Two passes, because either alone has a blind spot:

* VALUE-level replacement removes the run's own exact secret values, so a
  credential in a flag with no pattern-matchable key (`-b 'session=...'`) is
  still caught;
* KEY-level masking catches `<sensitive-key>: <value>` / `<key>=<value>` even
  when the caller did not pass the value in.

Pure and dependency-free (CODING_STANDARD section 3): a function of its inputs.
"""
from __future__ import annotations

import re
from typing import Iterable

_SENSITIVE = re.compile(
    r"(?i)(authorization|cookie|x-api-key|api[-_]?key|token|password|secret|session)"
    r"(\s*[:=]\s*|\s+)([^\s;'\"]+)"
)
"""`<sensitive-key>: <value>` or `<sensitive-key>=<value>` (no whitespace)."""

_MIN_VALUE_LEN = 4
"""Value-level replacement only fires above this length: blindly replacing a
one- or two-character "secret" would corrupt unrelated parts of the command
(and a real credential is never that short). The KEY-level mask still catches
a short value that sits behind a sensitive key."""

_PLACEHOLDER = "[redacted]"


def redact_command(command: str, secret_values: Iterable[str]) -> str:
    """Return `command` with every known secret value and keyed credential
    replaced by a placeholder. Never raises; an empty command is returned as-is."""
    if not command:
        return command
    redacted = command
    for value in sorted(
        {v for v in secret_values if v and len(v) >= _MIN_VALUE_LEN},
        key=len,
        reverse=True,
    ):
        redacted = redacted.replace(value, _PLACEHOLDER)
    return _SENSITIVE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{_PLACEHOLDER}", redacted
    )


def secret_values_from_auth_context(material: object) -> list[str]:
    """Every exact credential value in a `project_request_auth` projection.

    The projection's shape is `{"cookies": [{"name", "value"}, ...], <header>:
    <value>, ...}`; both the cookie names/values and the header values are
    secret-bearing transport, so all of them are returned for value-level
    redaction. Tolerant by construction: a non-mapping yields no values.
    """
    values: list[str] = []
    if not isinstance(material, dict):
        return values
    for key, value in material.items():
        if key == "cookies" and isinstance(value, list):
            for cookie in value:
                if isinstance(cookie, dict):
                    for slot in ("name", "value"):
                        item = cookie.get(slot)
                        if isinstance(item, str) and item:
                            values.append(item)
        elif isinstance(value, str) and value:
            values.append(value)
    return values


__all__ = ["redact_command", "secret_values_from_auth_context"]
