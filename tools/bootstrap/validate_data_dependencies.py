#!/usr/bin/env python3
"""Shape validator for a target's pre-eval data dependencies.

Validates the three N12 work items of one target against the contract in
`tools/bootstrap/DATA-DEPENDENCIES.md`:

  1. `operator_kb.md`  - parses through the real platform scaffold (`src/polymerhus/analysis/scaffold.py`)
     into at least one Service and at least the three linchpin Systems, and
     carries the structured `## Overview` block (fenced ```yaml: domain,
     description, >= 2 journeys of >= 3 steps, <= 250 rendered words).
  2. `l1-surface.yaml` - the graph-ready RDF dataset: valid labels, identity
     keys matching the graph schema, resolvable edge endpoints, unique
     identities.
  3. `auth/{overview.yaml,credentials.yaml}` + `skills/authn/SKILL.md` -
     present and structurally shaped (presence + field shape; full semantic
     validity is the authn skill's own P6 gate).

Usage:
  PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py <target_dir> [<target_dir> ...]
  PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --all <kbs_root>
  PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --auth-only \
      --staging <staging_root> <project_id>   # authn-first, before L1 exists

Exit 0 when every target passes; 1 with a per-target error list otherwise.
Import performs no I/O beyond reading the given paths.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# L1 labels this dataset may carry (services + systems, per the operator scope).
L1_LABELS = {"Service", "System"}

# Graph identity keys, exactly as the L1 write boundary keys them.
IDENTITY_KEYS = {
    "Service": ("business_function_slug",),
    "System": ("kind", "discriminator"),
}

# The L1 relation vocabulary the surface may use.
EDGE_RELS = {
    "EXPOSED_VIA", "AUTHENTICATED_BY", "AUTHORIZED_BY", "CONSUMES", "PRODUCES",
}

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _system_kinds() -> set[str]:
    """The controlled System-kind vocabulary, single-sourced from the platform."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS

    return {kind for kind, _desc in SYSTEM_KINDS}


def check_operator_kb(path: Path) -> list[str]:
    """Parse the KB through the real scaffold and assert a usable skeleton."""
    errors: list[str] = []
    if not path.is_file():
        return [f"operator_kb.md missing at {path}"]
    try:
        from polymerhus.analysis.scaffold import build_shells_from_path as build_shells  # the platform parser

        services, systems, _dispositions = build_shells(path)
    except Exception as exc:  # noqa: BLE001 - surface any parse failure
        return [f"operator_kb.md failed to parse: {exc}"]
    if not services:
        errors.append("operator_kb.md parsed zero Services (a blocked scaffold)")
    # NOTE: the three auth linchpins (services and systems) are HARD-forced by the
    # platform scaffold, so an unauthenticated target legitimately omits them from
    # the KB. Grounding them is a COVERAGE judgement (the batch critic), not a
    # shape error, so it is deliberately not enforced here.
    return errors


def check_overview(path: Path) -> list[str]:
    """The structured `## Overview` block: the strict, deterministic gate (Q3).

    The runtime parser (`analysis.scaffold.parse_overview`) fails OPEN - a
    legacy prose block maps to `description`, malformed YAML degrades to empty -
    because the platform must never break the skeleton over framing. THIS check
    does not fail open: the KB must carry a fenced ```yaml Overview with a
    non-empty `domain`, a non-empty `description`, at least two canonical
    journeys of at least three steps each, and at most
    `OVERVIEW_WORD_BUDGET` words over the rendered plain text. The budget is
    the SAME constant and the SAME count the creator self-checks and the critic
    judges with (`polymerhus.analysis.overview`), so the three sites cannot
    drift."""
    if not path.is_file():
        return [f"operator_kb.md missing at {path} (Overview not checkable)"]
    from polymerhus.analysis.overview import (  # noqa: PLC0415
        OVERVIEW_WORD_BUDGET,
        overview_word_count,
    )
    from polymerhus.analysis.scaffold import parse_overview  # noqa: PLC0415

    overview = parse_overview(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if not overview.get("domain"):
        errors.append(
            "Overview: 'domain' missing (a legacy prose block is not the "
            "structured entity - the fenced ```yaml form is required)"
        )
    if not overview.get("description"):
        errors.append("Overview: 'description' missing")
    journeys = overview.get("journeys") or []
    if len(journeys) < 2:
        errors.append(
            f"Overview: needs at least 2 journeys (found {len(journeys)})"
        )
    for journey in journeys:
        name = journey.get("name") or "(unnamed)"
        if not journey.get("name"):
            errors.append("Overview: a journey has no 'name'")
        steps = journey.get("steps") or []
        if len(steps) < 3:
            errors.append(
                f"Overview journey {name!r}: needs at least 3 steps "
                f"(found {len(steps)})"
            )
    count = overview_word_count(overview)
    if count > OVERVIEW_WORD_BUDGET:
        errors.append(
            f"Overview: {count} words exceeds the {OVERVIEW_WORD_BUDGET}-word "
            "budget"
        )
    return errors


def check_l1_surface(path: Path) -> list[str]:
    """Validate the graph-ready RDF dataset shape."""
    errors: list[str] = []
    if not path.is_file():
        return [f"l1-surface.yaml missing at {path}"]
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"l1-surface.yaml is not valid YAML: {exc}"]
    if not isinstance(doc, dict):
        return ["l1-surface.yaml must be a mapping"]
    if not doc.get("target"):
        errors.append("l1-surface.yaml: missing 'target'")
    if "base_url" in doc:
        errors.append(
            "l1-surface.yaml: 'base_url' is not allowed; a deployment address "
            "goes stale the moment the target is redeployed, and the app "
            "resolves the project's canonical origin "
            "(settings.recon.target_seed) instead")
    units = doc.get("units")
    if not isinstance(units, list) or not units:
        return errors + ["l1-surface.yaml: 'units' must be a non-empty list"]

    vocab = _system_kinds()
    seen: set[tuple] = set()
    identities: set[tuple] = set()
    for i, unit in enumerate(units):
        where = f"units[{i}]"
        if not isinstance(unit, dict):
            errors.append(f"{where}: not a mapping")
            continue
        label = unit.get("label")
        if label not in L1_LABELS:
            errors.append(f"{where}: label {label!r} not in {sorted(L1_LABELS)}")
            continue
        identity = unit.get("identity")
        if not isinstance(identity, dict):
            errors.append(f"{where}: missing 'identity' mapping")
            continue
        for key in IDENTITY_KEYS[label]:
            if not identity.get(key):
                errors.append(f"{where} ({label}): identity missing key {key!r}")
        if label == "System" and identity.get("kind") not in vocab:
            errors.append(
                f"{where}: kind {identity.get('kind')!r} not in SYSTEM_KINDS"
            )
        ident = (label, tuple(sorted(identity.items())))
        if ident in seen:
            errors.append(f"{where}: duplicate identity {identity}")
        seen.add(ident)
        identities.add(ident)
        if not isinstance(unit.get("props", {}), dict):
            errors.append(f"{where}: 'props' must be a mapping")

    for i, unit in enumerate(units):
        if not isinstance(unit, dict):
            continue
        for side in ("outbound_edges", "inbound_edges"):
            for j, edge in enumerate(unit.get(side, []) or []):
                where = f"units[{i}].{side}[{j}]"
                if not isinstance(edge, dict):
                    errors.append(f"{where}: not a mapping")
                    continue
                rel = edge.get("rel")
                if rel not in EDGE_RELS:
                    errors.append(f"{where}: rel {rel!r} not in {sorted(EDGE_RELS)}")
                t_label = edge.get("target_label") if side == "outbound_edges" else edge.get("source_label")
                t_ident = edge.get("target_identity") if side == "outbound_edges" else edge.get("source_identity")
                if t_label not in L1_LABELS:
                    errors.append(f"{where}: endpoint label {t_label!r} not an L1 label")
                elif isinstance(t_ident, dict):
                    key = (t_label, tuple(sorted(t_ident.items())))
                    if key not in identities:
                        errors.append(f"{where}: unresolvable endpoint {t_label} {t_ident}")
    return errors


# --- Arm L (#384): the data-dependency auth context is deployment-NEUTRAL ----

# A pre-built AuthContext must carry no deployment origin: a bootstrap capture
# (host:port) goes stale the moment the target is redeployed, which is exactly
# how the arm K white-jotter auth gateway thrashed. Paths only; the app
# resolves the project's canonical origin (`settings.recon.target_seed`) at the
# auth read seam, and back-fills the informational `domain` from it.
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>\\]+")


def _absolute_urls(value, where: str):
    """Yield `(path, url)` for every absolute URL found in a nested value."""
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _absolute_urls(nested, f"{where}.{key}")
    elif isinstance(value, list):
        for i, nested in enumerate(value):
            yield from _absolute_urls(nested, f"{where}[{i}]")
    elif isinstance(value, str):
        match = _URL_IN_TEXT_RE.search(value)
        if match:
            yield where, match.group(0)


def _credential_sets(record: dict):
    """The credential-set mappings of one account record: the default set and
    every `roles.<role>` set (each role maps to a credential set directly)."""
    credentials = record.get("credentials")
    if isinstance(credentials, dict):
        yield "credentials", credentials
    roles = record.get("roles")
    if isinstance(roles, dict):
        for role_name, role_set in roles.items():
            if isinstance(role_set, dict):
                yield f"roles.{role_name}", role_set


def _auth_origin_errors(name: str, account: dict) -> list[str]:
    """Refuse deployment origins in one data-dependency account: `login_url`
    must be a path (resolved at read), `domain` must be absent (back-filled at
    read), and no other attribute may carry an absolute URL with a host."""
    errors: list[str] = []
    for where, credentials in _credential_sets(account):
        login_url = credentials.get("login_url")
        if isinstance(login_url, str) and "://" in login_url:
            errors.append(
                f"credentials.yaml: account {name!r} {where}.login_url "
                f"{login_url!r} is absolute; store a path such as '/api/login' "
                f"and let the app resolve the project's canonical origin")
        if "domain" in credentials:
            errors.append(
                f"credentials.yaml: account {name!r} {where}.domain is not "
                f"allowed; the app back-fills it from the project's canonical "
                f"origin at read")
    for where, url in _absolute_urls(account, f"account {name!r}"):
        if where.endswith(".login_url"):
            continue  # the specific rule above already names this defect
        errors.append(
            f"credentials.yaml: {where} carries an absolute URL {url!r}; a "
            f"data dependency stays deployment-neutral (paths only)")
    return errors


def check_auth(project_dir: Path) -> list[str]:
    """Presence + structural shape of the AuthContext and the authn skill.

    `project_dir` is the staging upload source. It holds `auth/` for the app
    data root and `skills/authn/` for the live skills root's
    `target-specific-procedure/<project_id>/` branch. It is not a runtime data
    root, and the data root never carries skills.

    The structural checks are backed by the app's OWN T1 seam
    (`records.validate_overview` / `records.validate_account`), the exact
    validation the placement endpoints apply before writing. Without this the
    validator accepted artifacts the endpoint then refused (list `roles`, a
    mapping `snapshot.cookies`, non-token header names, null overview fields) -
    see `docs/design/eval-data-dependency-placement-decisions.md`.
    """
    from polymerhus.app.auth.records import (
        AuthInvalidError,
        validate_account,
        validate_overview,
    )

    errors: list[str] = []
    overview = project_dir / "auth" / "overview.yaml"
    credentials = project_dir / "auth" / "credentials.yaml"
    skill = project_dir / "skills" / "authn" / "SKILL.md"

    for p in (overview, credentials):
        if not p.is_file():
            errors.append(f"{p.name} missing at {p}")
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{p.name} is not valid YAML: {exc}")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{p.name} must be a mapping")

    if overview.is_file():
        try:
            doc = yaml.safe_load(overview.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            doc = None
        if isinstance(doc, dict):
            try:
                validate_overview(doc)
            except AuthInvalidError as exc:
                errors.append(f"overview.yaml: {exc}")
            for where, url in _absolute_urls(doc, "overview"):
                errors.append(
                    f"overview.yaml: {where} carries an absolute URL {url!r}; "
                    f"a data dependency stays deployment-neutral (paths only)")

    has_accounts = False
    if credentials.is_file():
        try:
            doc = yaml.safe_load(credentials.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            doc = {}
        accounts = doc.get("accounts") if isinstance(doc, dict) else None
        if accounts is None:
            errors.append("credentials.yaml: missing 'accounts' mapping")
        elif not isinstance(accounts, dict):
            errors.append("credentials.yaml: 'accounts' must be a mapping")
        else:
            has_accounts = bool(accounts)
            for name, acct in accounts.items():
                if not isinstance(acct, dict):
                    errors.append(f"credentials.yaml: account {name!r} not a mapping")
                    continue
                if "credentials" not in acct:
                    errors.append(f"credentials.yaml: account {name!r} has no 'credentials'")
                try:
                    validate_account({**acct, "origin": acct.get("origin", "operator")})
                except AuthInvalidError as exc:
                    errors.append(f"credentials.yaml: account {name!r}: {exc}")
                errors.extend(_auth_origin_errors(name, acct))

    # A target with no authentication surface legitimately records an empty
    # `accounts` and no authn skill (the eval marks its auth-bootstrap
    # not-required); require the skill only when accounts exist.
    if not skill.is_file():
        if has_accounts:
            errors.append(f"authn SKILL.md missing at {skill} (accounts are recorded)")
    else:
        text = skill.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            errors.append("authn SKILL.md has no valid frontmatter block")
        else:
            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError as exc:
                fm = None
                errors.append(f"authn SKILL.md frontmatter invalid: {exc}")
            if isinstance(fm, dict):
                if fm.get("name") != "authn":
                    errors.append("authn SKILL.md: frontmatter name must be 'authn'")
                if not fm.get("description"):
                    errors.append("authn SKILL.md: frontmatter missing 'description'")
                if not (fm.get("metadata") or {}).get("version"):
                    errors.append("authn SKILL.md: frontmatter missing metadata.version")
    return errors


def check_target(
    target_dir: Path,
    *,
    auth_dir: Path | None = None,
    l1_only: bool = False,
    auth_only: bool = False,
) -> dict[str, list[str]]:
    """Run every check for one target; returns {section: [errors]}.

    `l1_only` skips the AuthContext + authn-skill checks (the L1 surface is
    authored before the authn artifacts exist).
    `auth_only` skips the L1 surface checks: under the authn-first order the
    AuthContext + authn skill are authored BEFORE the L1 surface, so `target_dir`
    may not exist yet and only the auth artifacts are checkable.
    `auth_dir` is the project data dir holding the auth artifacts (defaults to
    `target_dir`, the legacy co-located layout); normally it is the staging
    project dir `<staging>/<project_id>/`.
    """
    report: dict[str, list[str]] = {}
    if not auth_only:
        kb_path = target_dir / "operator_kb.md"
        report["operator_kb"] = check_operator_kb(kb_path)
        report["overview"] = check_overview(kb_path)
        report["l1_surface"] = check_l1_surface(target_dir / "l1-surface.yaml")
    if not l1_only:
        report["auth"] = check_auth(auth_dir or target_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="*", help="target directory(ies)")
    ap.add_argument("--all", metavar="KBS_ROOT", help="validate every child directory")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--l1-only",
        action="store_true",
        help="skip the AuthContext + authn-skill checks (L1 authored first)",
    )
    mode.add_argument(
        "--auth-only",
        action="store_true",
        help="skip the L1 surface checks; validate only the AuthContext + authn "
        "skill (authn-first order, before <target_dir> exists)",
    )
    ap.add_argument(
        "--staging",
        metavar="STAGING_ROOT",
        help="staging data root; auth for <target> is checked at "
        "<STAGING_ROOT>/<target>/{auth,skills} (default: co-located under the target dir)",
    )
    args = ap.parse_args(argv)

    dirs = list(args.targets)
    if args.all:
        dirs += sorted(str(p) for p in Path(args.all).iterdir() if p.is_dir())
    if not dirs:
        ap.error("no targets given (pass directories or --all <kbs_root>)")

    failed = 0
    for d in dirs:
        target_dir = Path(d)
        auth_dir = Path(args.staging) / target_dir.name if args.staging else None
        report = check_target(
            target_dir,
            auth_dir=auth_dir,
            l1_only=args.l1_only,
            auth_only=args.auth_only,
        )
        errors = [e for errs in report.values() for e in errs]
        if errors:
            failed += 1
            print(f"FAIL {target_dir}")
            for section, errs in report.items():
                for e in errs:
                    print(f"  [{section}] {e}")
        else:
            print(f"OK   {target_dir}")
    print(f"\n{len(dirs) - failed}/{len(dirs)} target(s) valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
