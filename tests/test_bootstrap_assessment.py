"""Unit tier: the bootstrap assessment framework (`tools/bootstrap/assessment`).

`assess.py` is the graded layer ON TOP of the shape validator: per-criterion
ordinal scales (anchors in `tools/bootstrap/assessment/RUBRIC.md`), per-target
metrics, and the portfolio report with baseline deltas. These tests drive it
over a crafted GOOD target and a crafted BAD target and pin the scales, the
metrics, and the failing-criterion reporting - no live DB, no LLM.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools" / "bootstrap" / "assessment" / "assess.py"
)


@pytest.fixture(scope="module")
def assess():
    spec = importlib.util.spec_from_file_location("bootstrap_assess", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD_KB = """# shop 1.0

## Overview

```yaml
domain: shop
description: A small web storefront where shoppers browse a catalogue and pay for a basket.
journeys:
  - name: Buy an item
    steps:
      - Open the storefront page (WebPresentation) and browse the catalogue.
      - Add an item to the basket from the product page (catalogue).
      - Pay at the checkout form (checkout, WebPresentation).
  - name: Track an order
    steps:
      - Open the account page (WebPresentation) and submit the sign-in form (checkout).
      - Read the order list page (catalogue).
      - Open one order page and inspect its status (checkout).
```

## Services

### checkout
- contract: Take a basket to a paid order and own order records.
- exposure: authenticated

### catalogue
- contract: Browse products, categories and their product details.
- exposure: public

## Systems

### RESTApi - store-api
- description: JSON API the storefront calls.

### WebPresentation - storefront
- description: Server-rendered storefront pages.

### AuthenticationMechanism - session-cookie
- description: Session cookie identity.

## Roles

- customer
- operator
"""

GOOD_SURFACE = """target: shop
observed_at: "2026-10-17T00:00:00Z"
units:
  - label: Service
    identity: {business_function_slug: checkout}
    props: {exposure: authenticated, service_contract: Take a basket to a paid order.}
    outbound_edges:
      - rel: AUTHENTICATED_BY
        target_label: System
        target_identity: {kind: AuthenticationMechanism, discriminator: session-cookie}
      - rel: EXPOSED_VIA
        target_label: System
        target_identity: {kind: WebPresentation, discriminator: storefront}
    inbound_edges: []
  - label: Service
    identity: {business_function_slug: catalogue}
    props: {exposure: public, service_contract: Browse products and categories.}
    outbound_edges:
      - rel: EXPOSED_VIA
        target_label: System
        target_identity: {kind: WebPresentation, discriminator: storefront}
    inbound_edges: []
  - label: System
    identity: {kind: WebPresentation, discriminator: storefront}
    props: {description: Server-rendered storefront pages.}
    outbound_edges: []
    inbound_edges:
      - rel: EXPOSED_VIA
        source_label: Service
        source_identity: {business_function_slug: checkout}
      - rel: EXPOSED_VIA
        source_label: Service
        source_identity: {business_function_slug: catalogue}
  - label: System
    identity: {kind: AuthenticationMechanism, discriminator: session-cookie}
    props: {description: Session cookie identity.}
    outbound_edges: []
    inbound_edges:
      - rel: AUTHENTICATED_BY
        source_label: Service
        source_identity: {business_function_slug: checkout}
"""

GOOD_SURFACE_MAP = """# shop - surface map

- GET / and /catalogue - anonymous product browsing.
- GET /product/{id} - product details.
- GET /account - sign-in required.
- POST /account/login - sign-in form submission.
- GET /basket - authenticated basket view.
- POST /checkout - authenticated order placement.
- GET /admin - operator area, sign-in required.
- GET /api/products - JSON catalogue API.
- POST /api/basket/items - authenticated basket mutation.
- GET /api/orders - authenticated order list.
"""

GOOD_NOTES = (
    "shop 1.0 runs Node 20 behind a reverse proxy on port 443. "
    "The storefront is server-rendered; the catalogue and basket pages are "
    "hydrated by a JSON API. Sessions are cookie based. The database is "
    "PostgreSQL 16. The operator area lives under /admin and requires the "
    "operator role. Prices are stored in minor currency units. "
    "The checkout posts a CSRF token issued with the basket page. "
    "The basket is persisted per session and is flushed when an order is "
    "placed. Product images are served from the same origin under /media. "
    "The operator area is a single page application over the JSON API, and "
    "the API is versioned under the /api prefix. Search is served by a "
    "database query; there is no external search service. The store runs "
    "with one currency and one locale, both configured at deploy time."
)

BAD_KB = """# bad 0.1

## Overview

An old prose block describing the solution.

## Services

### checkout
- contract: Handles /api/checkout and ?cart= for orders.
- exposure: authenticated

### orders
- contract: Handles orders and checkout through /api/orders.

## Systems

### FancyWidget - helper
- description: Not a vocabulary kind.
"""

BAD_SURFACE = """target: bad
units:
  - label: Service
    identity: {business_function_slug: checkout}
    props: {exposure: authenticated}
    outbound_edges:
      - rel: EXPOSED_VIA
        target_label: System
        target_identity: {kind: WebPresentation, discriminator: ghost}
    inbound_edges: []
  - label: Service
    identity: {business_function_slug: checkout}
    props: {exposure: public}
    outbound_edges: []
    inbound_edges: []
"""


def _write_good(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "operator_kb.md").write_text(GOOD_KB, encoding="utf-8")
    (root / "l1-surface.yaml").write_text(GOOD_SURFACE, encoding="utf-8")
    (root / "surface-map.md").write_text(GOOD_SURFACE_MAP, encoding="utf-8")
    (root / "research-notes.md").write_text(GOOD_NOTES, encoding="utf-8")
    return root


def _write_bad(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "operator_kb.md").write_text(BAD_KB, encoding="utf-8")
    (root / "l1-surface.yaml").write_text(BAD_SURFACE, encoding="utf-8")
    (root / "surface-map.md").write_text(
        "# bad - surface map\n\n- GET /admin - known CVE-2021-1234 lives here.\n",
        encoding="utf-8")
    return root


def test_good_target_scores_high_on_every_deterministic_family(assess, tmp_path):
    row = assess.assess_target(_write_good(tmp_path / "shop"))
    assert row["A1"]["scale"] == 4
    assert row["A2"]["scale"] == 4
    assert row["A3"]["scale"] == 4
    assert row["A4"]["scale"] == 4
    assert row["B1"]["scale"] == 4
    assert row["B2"]["scale"] == 4
    assert row["B3"]["scale"] == 4
    assert row["B4"]["scale"] == 4
    assert row["C1"]["scale"] == 4
    assert row["C2"]["scale"] == 4
    assert row["C3"]["scale"] == 4
    assert row["E1"]["scale"] == 4
    assert row["E2"]["scale"] == 4
    # no auth bundle staged: the auth criterion degrades loudly, never raises
    assert row["D1"]["scale"] == 0


def test_surface_reference_proxy_counts_singular_and_plural(assess):
    """A step that names its surface part in the enumerable vocabulary grounds.

    The plural counts: `fields`, `pages` and `links` name the same parts a
    singular does, and a proxy that fails on an inflection would punish the
    artifact for prose, not for content.
    """
    rx = assess._SURFACE_REF_RE
    for step in (
        "choose tables and fields",
        "access rule pages bind roles",
        "adjacent-entry links",
        "call the account API endpoints",
        "Open the sign-in form",
        "Open the editor page",
    ):
        assert rx.search(step), step
    assert not rx.search("Load the browser shell from the root")


def test_good_target_metrics_are_reported(assess, tmp_path):
    row = assess.assess_target(_write_good(tmp_path / "shop"))
    assert row["A3"]["metrics"]["words"] <= 150
    assert row["C3"]["metrics"]["auth_edge_coverage"] == 1.0
    assert row["C2"]["metrics"]["orphan_frac"] == 0.0
    assert row["E1"]["metrics"]["endpoint_tokens"] >= 10
    assert row["overall"] > 3.0


def test_bad_target_fails_the_structural_and_integrity_criteria(assess, tmp_path):
    row = assess.assess_target(_write_bad(tmp_path / "bad"))
    assert row["A1"]["scale"] <= 2  # legacy prose: no domain, no journeys
    assert row["A2"]["scale"] == 0
    assert row["A4"]["scale"] == 0
    assert row["B2"]["scale"] <= 2  # path leaks + near-duplicate contracts
    assert row["B3"]["scale"] <= 2  # the system kind is out of vocabulary
    assert row["C1"]["scale"] <= 2  # unresolvable edge endpoint
    assert row["C3"]["scale"] <= 2  # orders missing from the surface
    assert row["E1"]["scale"] <= 2  # no research notes
    assert row["E2"]["scale"] == 0  # CVE marker in surface-map.md
    failing = assess._failing(row)
    assert any("A2" in f for f in failing)
    assert any("E2" in f for f in failing)


def test_portfolio_report_renders_the_table_and_failing_list(assess, tmp_path):
    rows = [
        assess.assess_target(_write_good(tmp_path / "shop")),
        assess.assess_target(_write_bad(tmp_path / "bad")),
    ]
    report = assess.portfolio_report(rows)
    assert "| criterion | mean | min | shop | bad |" in report
    assert "overall" in report
    assert "## Failing criteria (scale <= 1)" in report
    assert "bad: E2 integrity.no_leak" in report
    assert "(target: missing" not in report


def test_portfolio_report_diffs_against_a_baseline(assess, tmp_path):
    rows = [assess.assess_target(_write_good(tmp_path / "shop"))]
    baseline = {"generated": "2026-01-01T00:00:00+00:00",
                "targets": [{"target": "shop", "overall": 2.0}]}
    report = assess.portfolio_report(rows, baseline=baseline)
    assert "## Deltas vs baseline" in report
    assert "+" in report


def test_llm_verdicts_merge_from_the_target_assessment_yaml(assess, tmp_path):
    root = _write_good(tmp_path / "shop")
    (root / "assessment.yaml").write_text(
        "criteria:\n"
        "  L1:\n    scale: 3\n    evidence: the journeys walk real flows\n"
        "  L4:\n    scale: 1\n    evidence: a known class has no servicing unit\n",
        encoding="utf-8")
    row = assess.assess_target(root)
    assert row["L1"]["scale"] == 3
    assert row["L4"]["scale"] == 1
    assert any("L4" in f for f in assess._failing(row))


def test_cli_writes_the_full_result_json(assess, tmp_path, capsys):
    good = _write_good(tmp_path / "shop")
    out = tmp_path / "out" / "portfolio.json"
    rc = assess.main([str(good), "--json", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["targets"][0]["target"] == "shop"
    assert "A1" in payload["targets"][0]
    assert capsys.readouterr().out.startswith("# Bootstrap artifact assessment")
