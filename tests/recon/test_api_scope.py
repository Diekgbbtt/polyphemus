# tests/recon/test_api_scope.py
import pytest

from polymerhus.recon.domain.api_scope import derive_api_prefix, derive_scan_targets


@pytest.mark.parametrize(
    "path,expected",
    [
        # last-noun cut, versions excluded from the prefix
        ("/api/v1/organizations", "/api/"),
        ("/api/users", "/api/"),
        ("/rest/v2/orders", "/rest/"),
        # non-standard mount: the noun is not leading, cut still lands after it
        ("/backend/api/v1/x", "/backend/api/"),
        # multiple nouns: cut at the LAST one
        ("/api/rest/things", "/api/rest/"),
        # no api-noun -> parent-directory fallback
        ("/checkout/summary", "/checkout/"),
        ("/orders/42", "/orders/"),
        # single meaningless segment -> root
        ("/foo", "/"),
        ("/", "/"),
    ],
)
def test_derive_api_prefix(path, expected):
    assert derive_api_prefix(path) == expected


def test_version_token_is_not_a_noun():
    # a bare version path has no noun -> parent-dir fallback, and the version is
    # never itself the cut point (so kiterunner fuzzes the version position).
    assert derive_api_prefix("/v1/users") == "/v1/"  # parent dir of /v1/users
    assert derive_api_prefix("/v2") == "/"


def test_infra_mount_nouns_recognised():
    assert derive_api_prefix("/internal/api/v1/x") == "/internal/api/"
    assert derive_api_prefix("/gateway/orders") == "/gateway/"


def test_derive_scan_targets_groups_and_formats():
    base = "https://shop.example.com"
    paths = ["/api/v1/users", "/api/v1/orders", "/api/v2/x", "/rest/things"]
    targets = derive_scan_targets(base, paths)
    # /api/ (3 endpoints) and /rest/ (1) -> two distinct scan bases
    assert set(targets) == {
        "https://shop.example.com/api/",
        "https://shop.example.com/rest/",
    }


def test_derive_scan_targets_caps_at_three_by_coverage():
    base = "https://h"
    # four distinct api-root prefixes; /api/ covers the most (3), the rest 1 each
    paths = (
        ["/api/a", "/api/b", "/api/c"]
        + ["/rest/x"]
        + ["/gateway/y"]
        + ["/rpc/z"]
    )
    targets = derive_scan_targets(base, paths, cap=3)
    assert len(targets) == 3
    assert "https://h/api/" in targets  # the highest-coverage prefix is kept


def test_derive_scan_targets_deterministic_order():
    base = "https://h"
    paths = ["/rest/x", "/api/a", "/api/b"]
    # stable: coverage desc, then prefix asc
    assert derive_scan_targets(base, paths) == ["https://h/api/", "https://h/rest/"]
