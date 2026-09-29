"""#238 follow-up - the E2E harness/overlay contracts, checked offline.

These tests need no live stack: they validate the fixtures the functional tier
sends through the PUBLIC API, and the Compose/harness wiring the live gate
depends on. A live stack that is unreachable must never be the reason a fixture
shape is wrong.
"""
from __future__ import annotations

from pathlib import Path

from polymerhus.app.auth.records import validate_account, validate_overview

from tests.e2e.harness import driver

ROOT = Path(__file__).resolve().parents[2]


# --- A1: the operator auth seed the smoke/functional runs store -------------------


def test_smoke_auth_fixture_is_public_contract_valid():
    """The seed the functional tier PUTs must pass the REAL public contract.

    #238 A1: the driver's `SMOKE_OVERVIEW` carried `target`/`auth-surface` (not
    overview fields) and nested the accounts one level too deep, so every live
    scenario died at seed time with `auth_invalid: overview.target is not a
    known overview field`.
    """
    validate_overview(driver.SMOKE_OVERVIEW)
    assert driver.SMOKE_ACCOUNTS, "the seed must carry at least one account"
    for name, account in driver.SMOKE_ACCOUNTS.items():
        assert isinstance(name, str) and name
        validate_account(account)
    # The account map is the mapping the API expects, NOT a `{"accounts": ...}`
    # wrapper (which `store_auth` adds): double nesting is what the API refused.
    assert "accounts" not in driver.SMOKE_ACCOUNTS
