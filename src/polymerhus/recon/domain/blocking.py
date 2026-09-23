"""The blocking-signal vocabulary: the one typed domain spelling of "the
target pushed back".

Recon meets three distinguishable refusal shapes, and collapsing them is a
modelling error with operational consequences: an authentication failure is
not a rate limit, and a rate limit is not a WAF block (`meta/authn-skill-writing`
states the same three-way distinction for the human authoring the auth
procedure). The #238 rate-limit mapping consumes the third: a limiter the
controller can measure and pace around, as opposed to a defence that needs
the browser path.

This module is the SINGLE SOURCE of those names. Runtime classifiers emit the
enum, `RateProfile.signals` carries it, JSON payloads carry its string value,
and the skill/prompt text that names a signal is pinned to it by tests
(`test_authn_skill_writing.py`, `test_rate_limit_types.py`) - so a rename
cannot leave a classifier, a stored profile and a procedure disagreeing about
what a signal is called.

Pure by construction: no I/O at import, no collaborator, no config
(CODING_STANDARD section 6).
"""
from __future__ import annotations

from enum import Enum


class BlockingSignal(str, Enum):
    """A blocking signal witnessed at the target.

    `str` so the enum, its wire form and the prompt text are one spelling
    (no translation table at any seam).

    - `waf_protected`: a WAF or anti-bot defence is present and blocking.
    - `waf_detection`: defensive detection is present without a block.
    - `rate_limited`: an application/edge limiter answered with its refusal
      fingerprint (typically 429, or an equivalent documented retry signal).
    """

    WAF_PROTECTED = "waf_protected"
    WAF_DETECTION = "waf_detection"
    RATE_LIMITED = "rate_limited"


BLOCKING_SIGNALS: tuple[BlockingSignal, ...] = tuple(BlockingSignal)
"""Every signal, in declaration order: the closed set a classifier may emit."""


__all__ = ["BLOCKING_SIGNALS", "BlockingSignal"]
