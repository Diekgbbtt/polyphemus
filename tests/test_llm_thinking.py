"""Unit tier: the thinking-effort adaptation substrate (#99, ADR A5, ticket #161).

The increment-3 capability dial mirrors the A1 method negotiation: a pure
selector `negotiate_thinking(declared_level, profile) -> (wire_form, value,
provenance)` adapts a role's DECLARED thinking level to what the provider/model
actually offers, plus the canonical per-level budget ladder `THINKING_BUDGET`.

Ratified semantics (ADR A5, operator 2026-08-22):
- exact match wins; else NEAREST-AT-LEAST-AS-MUCH (lowest offered level >=
  declared; reasoning never silently downgraded);
- `off` declared -> only OMIT or the model's literal `none`/`null` slot;
- toggle-only control, non-off declared -> thinking-ON; off declared -> OMIT;
- budget_tokens-only control -> canonical THINKING_BUDGET clamped to bounds;
- `[]` always-on -> OMIT for any non-off declared;
- unknown profile -> keep the declared baseline (D7 fail-open), observable;
- never parses vendor error strings.

Every test is fully mocked - no live model, no live gateway (CODING_STANDARD
sections 6, 10). The pure-contract style matches the `test_llm_negotiation.py`
method selector tests.
"""
from polymerhus.app.llm import negotiation as N
from polymerhus.app.llm.capability import CapabilityProfile


def _profile(**kw) -> CapabilityProfile:
    """A minimal profile carrying only the A5 thinking surface."""
    return CapabilityProfile(**kw)


# ---------------------------------------------------------------------------
# The canonical budget ladder (operator-ratified) ----------------------------
# ---------------------------------------------------------------------------

def test_thinking_budget_ladder_is_operator_ratified():
    assert N.THINKING_BUDGET == {
        "minimal": 1024,
        "low": 2048,
        "medium": 4096,
        "high": 16384,
        "xhigh": 32768,
        "max": 40000,
    }


def test_thinking_budget_covers_every_declared_non_off_level():
    for level in ("minimal", "low", "medium", "high", "xhigh", "max"):
        assert level in N.THINKING_BUDGET


def test_thinking_forms_are_the_documented_vocabulary():
    assert N.THINKING_FORM_EFFORT == "effort"
    assert N.THINKING_FORM_BUDGET == "budget"
    assert N.THINKING_FORM_TOGGLE == "toggle"
    assert N.THINKING_FORM_OMIT == "omit"


# ---------------------------------------------------------------------------
# Exact match ---------------------------------------------------------------
# ---------------------------------------------------------------------------

def test_effort_exact_match_wins():
    p = _profile(reasoning_control="effort", reasoning_efforts=("low", "medium", "high"))
    form, value, prov = N.negotiate_thinking("medium", p)
    assert (form, value) == ("effort", "medium")
    assert prov == "exact-match"


def test_effort_exact_any_offered_level():
    p = _profile(reasoning_control="effort", reasoning_efforts=("minimal", "high"))
    form, value, _ = N.negotiate_thinking("high", p)
    assert (form, value) == ("effort", "high")


# ---------------------------------------------------------------------------
# NEAREST-AT-LEAST-AS-MUCH fallback (operator-ratified) ---------------------
# ---------------------------------------------------------------------------

def test_fallback_medium_to_high_when_offered_high_max():
    """The exact ADR example: declared `medium`, offered `[high, max]` -> high.
    Reasoning never downgraded below what the operator declared."""
    p = _profile(reasoning_control="effort", reasoning_efforts=("high", "max"))
    form, value, prov = N.negotiate_thinking("medium", p)
    assert (form, value) == ("effort", "high")
    assert prov == "fallback-nearest-at-least-as-much"


def test_fallback_picks_lowest_offered_at_or_above_declared():
    p = _profile(reasoning_control="effort", reasoning_efforts=("high", "xhigh", "max"))
    form, value, _ = N.negotiate_thinking("medium", p)
    assert value == "high"  # the LOWEST offered >= medium


def test_fallback_declared_low_with_only_minimal_offered_goes_medium_via_exact_or_up():
    """Declared `low` (rank 2), offered `[minimal, medium, high]`: minimal < low
    is TOO LOW (never downgrade), so medium wins."""
    p = _profile(reasoning_control="effort", reasoning_efforts=("minimal", "medium", "high"))
    form, value, _ = N.negotiate_thinking("low", p)
    assert value == "medium"


def test_fallback_declared_minimal_to_first_available():
    p = _profile(reasoning_control="effort", reasoning_efforts=("minimal", "high"))
    form, value, prov = N.negotiate_thinking("minimal", p)
    assert (value, prov) == ("minimal", "exact-match")


def test_fallback_never_downgrades_below_declared():
    """Declared `high` with only `[minimal, low, medium]` offered: no offered
    level is at-or-above declared, so the wire OMITS rather than silently
    reasoning lower - the fail clause of the ratified policy."""
    p = _profile(reasoning_control="effort", reasoning_efforts=("minimal", "low", "medium"))
    form, value, prov = N.negotiate_thinking("high", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)
    assert prov == "fallback-none-at-or-above-declared-omit"


# ---------------------------------------------------------------------------
# `off` declared: OMIT or the literal none/null slot ------------------------
# ---------------------------------------------------------------------------

def test_off_on_effort_with_none_slot_maps_to_none():
    p = _profile(reasoning_control="effort", reasoning_efforts=("none", "low", "medium", "high"))
    form, value, prov = N.negotiate_thinking("off", p)
    assert (form, value) == ("effort", "none")
    assert prov == "off-maps-to-offered-none-slot"


def test_off_without_none_slot_omits():
    p = _profile(reasoning_control="effort", reasoning_efforts=("low", "medium", "high"))
    form, value, prov = N.negotiate_thinking("off", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)
    assert prov == "off-omit"


def test_off_always_on_omits():
    p = _profile(reasoning_control="none", reasoning_efforts=())
    form, value, _ = N.negotiate_thinking("off", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)


def test_off_toggle_omits():
    p = _profile(reasoning_control="toggle")
    form, value, _ = N.negotiate_thinking("off", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)


def test_off_unknown_profile_omits():
    form, value, _ = N.negotiate_thinking("off", None)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)


# ---------------------------------------------------------------------------
# toggle-only control --------------------------------------------------------
# ---------------------------------------------------------------------------

def test_toggle_only_non_off_maps_to_toggle_on():
    p = _profile(reasoning_control="toggle")
    form, value, prov = N.negotiate_thinking("medium", p)
    assert (form, value) == ("toggle", "on")
    assert prov == "toggle-on"


def test_toggle_only_high_also_toggle_on():
    p = _profile(reasoning_control="toggle")
    form, value, _ = N.negotiate_thinking("high", p)
    assert (form, value) == ("toggle", "on")


# ---------------------------------------------------------------------------
# budget_tokens-only control -------------------------------------------------
# ---------------------------------------------------------------------------

def test_budget_only_maps_level_through_canonical_ladder():
    p = _profile(reasoning_control="budget_tokens")
    form, value, prov = N.negotiate_thinking("medium", p)
    assert (form, value) == ("budget", 4096)
    assert prov == "budget-canonical-clamped"


def test_budget_only_high_maps_canonical():
    p = _profile(reasoning_control="budget_tokens")
    form, value, _ = N.negotiate_thinking("high", p)
    assert (form, value) == ("budget", 16384)


def test_budget_only_clamps_to_declared_bounds():
    p = _profile(reasoning_control="budget_tokens", thinking_budget_bounds=(2048, 8192))
    form, value, _ = N.negotiate_thinking("xhigh", p)
    assert (form, value) == ("budget", 8192)  # 32768 clamped down to 8192
    form, value, _ = N.negotiate_thinking("low", p)
    assert value == 2048  # canonical low=2048, exactly at the declared min
    form, value, _ = N.negotiate_thinking("medium", p)
    assert value == 4096  # canonical medium=4096 within (2048, 8192)
    form, value, _ = N.negotiate_thinking("minimal", p)
    assert value == 2048  # canonical 1024 clamped UP to the declared min 2048


def test_budget_only_declared_off_omits():
    p = _profile(reasoning_control="budget_tokens")
    form, value, _ = N.negotiate_thinking("off", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)


# ---------------------------------------------------------------------------
# [] always-on / no-caller-control ------------------------------------------
# ---------------------------------------------------------------------------

def test_always_on_non_off_omits():
    """`reasoning_options: []` - the model reasons, the caller cannot control
    it. Nothing to send; never pretend a level."""
    p = _profile(reasoning_control="none")
    form, value, prov = N.negotiate_thinking("high", p)
    assert (form, value) == (N.THINKING_FORM_OMIT, None)
    assert prov == "always-on-or-unknown-omit"


# ---------------------------------------------------------------------------
# combos: effort first-class when present -----------------------------------
# ---------------------------------------------------------------------------

def test_effort_toggle_combo_prefers_effort():
    p = _profile(reasoning_control="effort+toggle", reasoning_efforts=("low", "high"))
    form, value, _ = N.negotiate_thinking("high", p)
    assert (form, value) == ("effort", "high")
    form, value, _ = N.negotiate_thinking("medium", p)
    assert value == "high"


def test_effort_budget_combo_prefers_effort():
    p = _profile(reasoning_control="effort+budget_tokens",
                 reasoning_efforts=("low", "high"), thinking_budget_bounds=(1024, 32768))
    form, value, _ = N.negotiate_thinking("high", p)
    assert (form, value) == ("effort", "high")


def test_toggle_budget_combo_without_effort_uses_budget():
    p = _profile(reasoning_control="toggle+budget_tokens")
    form, value, _ = N.negotiate_thinking("medium", p)
    assert (form, value) == ("budget", 4096)


# ---------------------------------------------------------------------------
# unknown profile: D7 fail-open, keep the declared baseline -----------------
# ---------------------------------------------------------------------------

def test_unknown_profile_keeps_declared_baseline():
    """No authored A5 surface tells the dial nothing - the declared baseline is
    sent unchanged (the legacy unconditional behavior) with an honest
    provenance. Never silently drops reasoning the operator asked for."""
    for profile in (None, _profile()):
        form, value, prov = N.negotiate_thinking("medium", profile)
        assert (form, value) == ("effort", "medium")
        assert prov == "unknown-profile-declared-kept"


def test_unknown_profile_keeps_high_baseline():
    form, value, prov = N.negotiate_thinking("high", _profile())
    assert (form, value) == ("effort", "high")
    assert prov == "unknown-profile-declared-kept"


def test_window_only_profile_is_thinking_unknown():
    """A tagged record carrying ONLY window/provenance fields (no A5 surface)
    is unknown to the thinking dial per Rule 1 - declared baseline kept."""
    p = _profile(context_limit=128000, source="models.dev/x/y")
    form, value, _ = N.negotiate_thinking("medium", p)
    assert (form, value) == ("effort", "medium")


def test_off_declared_never_reaches_an_effort_level():
    """off is a DECLARED state, never a wire effort - except through the
    offered none/null slot."""
    p = _profile(reasoning_control="effort", reasoning_efforts=("low", "medium"))
    form, value, _ = N.negotiate_thinking("off", p)
    assert form == N.THINKING_FORM_OMIT