"""Unit tier: the data-dependency shape validator (`tools/bootstrap`).

The validator is the BUILD GATE for a target's pre-eval data dependencies: the
bootstrap creator/critic agents are advisory, this script is deterministic. The
Overview checks (Q3, 2026-10-17) are the structured entity's strict gate - the
runtime parser (`analysis.scaffold.parse_overview`) fails open, the validator
does not - and the word budget counts through the SAME
`polymerhus.analysis.overview` rule the creator self-checks and the critic
judges with.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools" / "bootstrap" / "validate_data_dependencies.py"
)


@pytest.fixture(scope="module")
def validator():
    spec = importlib.util.spec_from_file_location("bootstrap_validator", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD_KB = """# shop

## Overview

```yaml
domain: shop
description: A small web storefront with a checkout.
journeys:
  - name: Buy an item
    steps:
      - Open / and browse the catalogue.
      - Add an item and open the cart.
      - Pay at the checkout form.
  - name: Register an account
    steps:
      - Open the sign-up form.
      - Submit the registration form.
      - Confirm the confirmation link.
```

## Services

### checkout
- contract: Take a basket to a paid order.
- exposure: public
"""

_THIN_KB = (
    "## Overview\n\n```yaml\n"
    "domain: shop\n"
    "description: A storefront.\n"
    "journeys:\n"
    "  - name: Buy an item\n"
    "    steps:\n"
    "      - Open /.\n"
    "```\n"
)


def _steps(n: int) -> str:
    return "\n".join(f"      - step {i} of the journey." for i in range(n))


def test_overview_checks_pass_the_structured_contract(validator, tmp_path):
    kb = tmp_path / "operator_kb.md"
    kb.write_text(GOOD_KB, encoding="utf-8")
    assert validator.check_overview(kb) == []


def test_overview_checks_reject_a_legacy_prose_block(validator, tmp_path):
    kb = tmp_path / "operator_kb.md"
    kb.write_text("# shop\n\n## Overview\n\nAn old prose block.\n", encoding="utf-8")
    errors = validator.check_overview(kb)
    assert any("domain" in e for e in errors)
    assert any("2 journeys" in e for e in errors)


def test_overview_checks_report_a_missing_block(validator, tmp_path):
    kb = tmp_path / "operator_kb.md"
    kb.write_text("## Services\n\n### a\n- contract: x\n", encoding="utf-8")
    errors = validator.check_overview(kb)
    assert any("missing" in e for e in errors)


def test_overview_checks_reject_thin_content(validator, tmp_path):
    kb = tmp_path / "operator_kb.md"
    kb.write_text(_THIN_KB, encoding="utf-8")
    errors = validator.check_overview(kb)
    assert any("2 journeys" in e for e in errors)
    assert any("3 steps" in e for e in errors)


def test_overview_checks_enforce_the_word_budget(validator, tmp_path):
    kb = tmp_path / "operator_kb.md"
    kb.write_text(
        "## Overview\n\n```yaml\n"
        "domain: shop\n"
        f"description: {' '.join(['word'] * 300)}\n"
        "journeys:\n"
        "  - name: Buy an item\n"
        "    steps:\n" + _steps(3) + "\n"
        "  - name: Register an account\n"
        "    steps:\n" + _steps(3) + "\n"
        "```\n",
        encoding="utf-8",
    )
    errors = validator.check_overview(kb)
    assert any("250" in e and "word" in e for e in errors)


def test_check_target_reports_the_overview_section(validator, tmp_path):
    (tmp_path / "operator_kb.md").write_text(GOOD_KB, encoding="utf-8")
    report = validator.check_target(tmp_path, l1_only=True)
    assert report["overview"] == []
    assert report["operator_kb"] == []
