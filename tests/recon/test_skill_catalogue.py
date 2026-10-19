"""Unit tier - the skill catalogue (W4: the nested-taxonomy loader; the mount
replacement: the live root is that catalogue).

The taxonomy and naming spec (`docs/design/skills-taxonomy.md` section 6) is the
contract this file pins, against its ratified rules R1-R4 and R8:

- R1: the suite mounts under the logical root `web-vulnerability-testing/`; the
  root is an identity and never appears in a reported skill name.
- R2/R9: discovery walks level 1 for group parents and level 2 for variants.
- R3: a skill resolves by its flat leaf name alone, whichever group holds it.
- R4: names are globally unique; a duplicate is a loud hard error naming both
  colliding paths, never a silent pick.
- R8: `references/` and `scripts/` stay skill-local, resolved under the leaf
  directory at either level.

The mount replacement moved the suite's groups INTO the live root `skills/`, so
the default resolution (`skill_for`/`list_skills`/`skill_meta`/`validate_skill`
with no `catalogue=`) now mounts that root lazily, while an explicit mount still
indexes an explicit root and still wins. The live root also carries the flat
product skills and the path-shaped `meta/` family; a level-2 bundle under a
SKILL.md-bearing parent is a suite variant (flat leaf name), a level-2 bundle
under a plain namespace directory keeps its path-shaped loader name.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from polymerhus.app.llm import skills

# The live catalogue root: the suite's groups (`<group>/SKILL.md` at level 1 and
# `<group>/<variant>/SKILL.md` at level 2), the flat product skills, and the
# `meta/` family. The stream records live in `skills-unspurious/` and carry no
# SKILL.md, so they are not part of the taxonomy.
SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"

# The live root's exact loader-name set (207 names): 41 suite groups plus their
# 124 variant leaves, 39 flat non-suite skills, and the 3 path-shaped meta
# skills. It is hardcoded, not recomputed from the index rule, so the mount
# cannot drop or invent a name without failing this pin.
_EXPECTED_LIVE_NAMES = frozenset(
    {
        "account-recovery", "agent-browser", "archive-zipslip-write",
        "async-boundary-abuse", "authentication-jwt", "authorization-pyramid",
        "aws", "bfla-alternate-path", "bfla-client-identity-trust",
        "bfla-deferred-execution", "blind-parameter-entity-oob-exfiltration",
        "broken-function-level-authorization", "business-logic",
        "cache-poisoning", "cdn-alternate-domain-binding",
        "concurrent-duplication", "context-leakage",
        "cross-service-consistency-race", "crypto-predictable-token",
        "crypto-signing-key-forgery", "crypto-timing-oracle", "crypto-weakness",
        "csrf", "csrf-form-post", "csrf-login-fixation", "csrf-navigation-get",
        "csrf-parser-differential", "csrf-websocket-handshake",
        "cve-exploitation", "dangling-record-resource-claim",
        "default-credential-replay", "defence-bypass",
        "defence-bypass-allowance-gap", "defence-bypass-attempt-batching",
        "defence-bypass-edge-origin-differential",
        "defence-bypass-encoding-differential", "defence-bypass-parser-confusion",
        "defence-bypass-signature-evasion", "defence-bypass-throttle-evasion",
        "deserialization-deferred-trigger", "deserialization-gadget-chain",
        "deserialization-signed-forgery", "differential-oracle-disclosure",
        "direct-injection-override", "django", "email-header-injection",
        "entity-expansion-denial-of-service", "error-verbosity-disclosure",
        "exposed-secret-extraction", "fastapi", "ffuf", "firebase-firestore",
        "generic-redirect-parser-bypass", "graphql", "header-cache-poisoning",
        "header-crlf-splitting", "header-gated-cloud-credential-read",
        "header-host-forward-spoof", "header-injection", "header-method-override",
        "header-request-smuggling", "header-response-value-confusion",
        "http-method-tampering", "http-method-tampering-informational-verb",
        "http-method-tampering-override-smuggling",
        "http-method-tampering-preflight-coercion",
        "http-method-tampering-verb-switch", "http-parameter-pollution",
        "http-request-smuggling", "http-request-smuggling-cross-protocol-desync",
        "http-request-smuggling-h2-desync", "httpx", "idempotency-dedup-bypass",
        "idor", "idor-collection-batch-scope", "idor-context-carrier-substitution",
        "idor-deferred-artifact-redemption", "idor-direct-object-swap",
        "idor-nested-expansion-binding", "idor-second-order-stored-reference",
        "indirect-injection-plant", "information-disclosure",
        "information-disclosure-excessive-data-exposure",
        "insecure-deserialization", "insecure-file-uploads",
        "jwt-claims-confusion", "jwt-flow-lifecycle", "jwt-key-resolution",
        "jwt-signature-forgery", "katana", "kubernetes", "ldap-injection",
        "lfi-include-execution", "lightrag-query", "llm-prompt-injection",
        "low-hanging-fruit", "mass-assignment",
        "mass-assignment-bulk-collection-injection",
        "mass-assignment-bulk-nested-relation-write",
        "mass-assignment-nested-relation-write", "meta/authn-skill-writing",
        "meta/meta-usage-skill", "meta/meta-write-skill", "mfa-bypass", "naabu",
        "nestjs", "nextjs", "nmap", "no-response-egress-inference",
        "nosql-aggregation-pipeline-injection",
        "nosql-command-protocol-smuggling", "nosql-injection",
        "nosql-operator-injection", "nosql-query-language-injection",
        "nosql-server-side-script-injection", "ns-delegation-takeover", "nuclei",
        "oauth", "oauth-code-client-binding", "oauth-device-approval",
        "oauth-pkce-enforcement", "oauth-redirect-uri-relay",
        "oauth-redirect-uri-validation", "oauth-state-nonce-csrf",
        "open-redirect", "optimistic-guard-evasion", "output-handling",
        "path-traversal-lfi-rfi", "prototype-pollution",
        "prototype-pollution-client-side", "prototype-pollution-server-side",
        "proxy-techniques", "proxy-techniques-cache-deception",
        "proxy-techniques-channel-wrapping",
        "proxy-techniques-client-side-path-traversal",
        "proxy-techniques-css-injection", "proxy-techniques-dns-rebinding",
        "proxy-techniques-dom-clobbering", "proxy-techniques-redirect-chain",
        "proxy-techniques-relay-forwarding",
        "proxy-techniques-url-parser-differential", "python",
        "quota-window-slicing", "race-conditions",
        "race-conditions-partial-construction", "rate-limit-bypass", "rce",
        "rce-command-injection", "rce-pipeline-execution",
        "redirector-to-fetcher-pivot", "rfi-remote-include",
        "scheme-translated-command-execution", "semgrep", "session-management",
        "session-token-authority-decode", "single-request-fanout",
        "sql-injection", "sql-injection-second-order",
        "sqli-boolean-blind-extraction", "sqli-error-based-extraction",
        "sqli-oast-exfiltration", "sqli-time-blind-extraction",
        "sqli-union-extraction", "sqlmap", "ssrf", "ssti",
        "ssti-blind-evaluation", "ssti-reflected-evaluation", "steel-browser",
        "stored-artifact-disclosure", "subdomain-takeover",
        "subdomain-takeover-mail-record-claim", "subfinder", "supabase",
        "tool-abuse", "transclusion-without-entity-resolution", "traversal-read",
        "two-principal-authz", "upload-archive-extraction",
        "upload-client-execution", "upload-pipeline-deferred-trust",
        "upload-server-execution", "upload-toolchain-execution",
        "username-enumeration-oracle", "value-domain-manipulation",
        "weak-credential-discovery", "webapp-clientside-semantic-model",
        "webpage-analysis", "webpage-profile", "windows-ad", "windows-ad-auth",
        "windows-ad-unauth", "windows-adcs", "windows-coerce-relay",
        "windows-kerberos", "windows-lateral", "windows-ldap-acl",
        "windows-mssql", "windows-privesc", "windows-smb", "windows-trusts",
        "xpath-injection", "xss", "xss-dom", "xss-stored", "xxe",
        "xxe-local-dtd-error-exfiltration",
    }
)


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


@pytest.fixture()
def suite() -> skills.SkillCatalogue:
    """The live root mounted under the suite's logical root, the default mount."""
    return skills.SkillCatalogue(SKILLS_ROOT)


def _write_bundle(root: Path, *parts: str) -> Path:
    """Write one conformant SKILL.md-bearing directory (a fixture skill) and
    return its bundle directory."""
    bundle = root.joinpath(*parts)
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(
        f"---\nname: {bundle.name}\ndescription: {bundle.name} does things.\n"
        "metadata:\n  version: 1.0.0\n---\n\n# Fixture\n",
        encoding="utf-8",
    )
    return bundle


# --- R1/R2: the mount, the logical root, and the two levels --------------------


def test_the_suite_mounts_under_its_logical_root(suite) -> None:
    # R1/D-T1: the logical root names the whole catalogue; the mount is an
    # identity, and the live root is the explicit physical root.
    assert suite.logical_root == "web-vulnerability-testing"
    assert suite.logical_root == skills.LOGICAL_SUITE_ROOT
    assert suite.root == SKILLS_ROOT
    assert suite.list_skills()  # a vacuous pass proves nothing
    # The suite's group directories are the ones moved into the live root.
    for group in ("authentication-jwt", "defence-bypass", "proxy-techniques"):
        assert (SKILLS_ROOT / group / "SKILL.md").is_file(), group


def test_the_logical_root_must_be_one_identity_component(tmp_path) -> None:
    # R1: the root is an identity, never a path.
    with pytest.raises(ValueError, match="logical_root"):
        skills.SkillCatalogue(tmp_path, logical_root="web-vulnerability-testing/")


def test_a_group_parent_and_its_variants_are_both_loadable(suite) -> None:
    # R2/R9: a level-1 directory carrying SKILL.md is the group parent (the
    # umbrella); a level-2 directory carrying SKILL.md is a variant. Both are
    # loadable skills (D-T7: parents stay indexable and loadable).
    parent = suite.read("authentication-jwt")
    variant = suite.read("jwt-claims-confusion")

    assert parent and variant and parent != variant
    # The parent's `## Variants` section links its child leaves (R9).
    assert "jwt-claims-confusion" in parent
    # R10: `graphql` does not decompose and stands as the level-1 skill alone.
    assert suite.read("graphql").startswith("# GraphQL")


def test_each_family_parent_links_exactly_its_child_leaves(suite) -> None:
    # R9: the decomposing parent contract binds the two technique families the
    # way it binds a class - `## Variants` follows `## Testing Methodology`,
    # lists one line per child leaf in the form `<leaf> - <trigger>`, and its
    # line set equals the child leaf set. `_completion/verify.sh` check 8 also
    # sweeps this; the pin here makes a family regression fail in pytest.
    for family in ("defence-bypass", "proxy-techniques"):
        body = suite.read(family)
        assert body.startswith("# "), family
        assert body.index("## Variants") > body.index("## Testing Methodology")
        section = body.split("## Variants", 1)[1].split("\n## ", 1)[0]
        listed = [
            line[2:].split(" - ")[0]
            for line in section.splitlines()
            if line.startswith("- ")
        ]
        leaves = sorted(
            path.parent.name for path in (SKILLS_ROOT / family).glob("*/SKILL.md")
        )
        assert leaves, family  # a family with no leaves proves nothing
        assert sorted(listed) == leaves, family
        assert len(listed) == len(set(listed))  # every child has exactly one line
        # A family leaf resolves by its flat leaf name, like any other skill (R3).
        assert suite.read(leaves[0])


# --- R3: the flat leaf is the loader-facing identity ---------------------------


def test_a_variant_resolves_by_its_flat_leaf_in_any_group(suite) -> None:
    # R3/D-T2: the leaf is the loader-facing identity, so a leaf resolves
    # whichever group holds it and no class segment enters the name. The three
    # leaves live under three different groups: `authentication-jwt`, `xss`, and
    # `subdomain-takeover`.
    for name, title in (
        ("jwt-claims-confusion", "# JWT Claims Confusion"),
        ("xss-dom", "# DOM XSS"),
        ("cdn-alternate-domain-binding", "# Cdn Alternate Domain Binding"),
    ):
        assert name in suite.list_skills()
        body = suite.read(name)
        assert not body.startswith("---")  # frontmatter stripped
        assert body.startswith(title)


def test_a_path_shaped_suite_name_never_resolves_against_the_mount(suite) -> None:
    # R3: no class segment and no path appears in a suite variant's loader name.
    path_shaped = "authentication-jwt/jwt-claims-confusion"

    assert suite.bundle_path(path_shaped) is None
    assert suite.read(path_shaped) == ""  # fail-open, like any unknown name
    assert path_shaped not in suite.list_skills()


def test_a_namespaced_family_keeps_its_path_shaped_name(suite) -> None:
    # The `meta/` directory carries no SKILL.md, so it is not a suite variant
    # group: the live catalogue keeps the path-shaped loader name, and the
    # path-based meta rule (`is_meta_skill`) therefore still holds.
    assert "meta/meta-usage-skill" in suite.list_skills()
    assert suite.read("meta/meta-usage-skill")
    assert suite.meta("meta/meta-usage-skill")["name"] == "meta-usage-skill"
    assert suite.bundle_path("meta/meta-usage-skill") == (
        SKILLS_ROOT / "meta" / "meta-usage-skill"
    )
    assert "meta-usage-skill" not in suite.list_skills()


def test_the_meta_namespace_carries_no_skill_md_of_its_own(suite) -> None:
    # The path-shaped rule depends on `meta/` being a plain namespace directory:
    # a `meta/SKILL.md` would make every meta child a level-2 suite variant and
    # collapse its loader name to the flat leaf. The absence is asserted here
    # and repeated by `verify.sh`, so the rule cannot be broken silently.
    assert not (SKILLS_ROOT / "meta" / "SKILL.md").exists()
    assert all(
        suite.bundle_path(name).parent == SKILLS_ROOT / "meta"
        for name in suite.list_skills()
        if name.startswith("meta/")
    )


def test_reported_names_are_loader_names_and_complete(suite) -> None:
    names = suite.list_skills()
    assert names == sorted(names)
    # R1/R3: never the logical root; a suite leaf is bare, a namespaced skill
    # keeps its path shape.
    assert all(suite.logical_root not in name for name in names)
    assert all(name.startswith("meta/") for name in names if "/" in name)
    # The live root's exact loader-name set: every SKILL.md-bearing directory at
    # level 1 or 2 is reported by its loader name, so the mount drops nothing
    # and invents nothing (R2). The set is hardcoded, never recomputed from the
    # index rule, so a new, renamed, or missing bundle fails this pin.
    assert set(names) == _EXPECTED_LIVE_NAMES
    assert len(names) == len(_EXPECTED_LIVE_NAMES)  # a duplicate name is never collapsed


def test_the_loader_functions_resolve_through_the_mount(suite) -> None:
    assert skills.list_skills(catalogue=suite) == suite.list_skills()
    assert skills.skill_for("jwt-claims-confusion", catalogue=suite) == suite.read(
        "jwt-claims-confusion"
    )
    meta = skills.skill_meta("jwt-claims-confusion", catalogue=suite)
    assert meta["name"] == "jwt-claims-confusion"


def test_every_reported_skill_carries_the_conformant_data_section(suite) -> None:
    # R3/R8: the frontmatter `name` equals the leaf the mount reports, and the
    # metadata version is uniform; `validate_skill` judges it through the same
    # mount, so a misplaced or non-conforming skill fails here.
    names = suite.list_skills()
    bad = {name: skills.validate_skill(name, catalogue=suite) for name in names}
    bad = {name: errors for name, errors in bad.items() if errors}

    assert not bad, f"non-conforming skills: {bad}"


# --- R4: global uniqueness, loud on the first duplicate ------------------------


def test_a_duplicate_name_is_a_hard_error_naming_both_collisions(tmp_path) -> None:
    # R4/D-T3: the mount indexes every name and fails on the first duplicate,
    # naming both colliding paths; it never resolves the collision silently.
    _write_bundle(tmp_path, "alpha")  # the group parents
    _write_bundle(tmp_path, "beta")
    first = _write_bundle(tmp_path, "alpha", "shared-leaf")
    second = _write_bundle(tmp_path, "beta", "shared-leaf")

    with pytest.raises(skills.DuplicateSkillNameError) as excinfo:
        skills.SkillCatalogue(tmp_path)

    error = excinfo.value
    assert isinstance(error, ValueError)
    assert error.name == "shared-leaf"
    assert (error.first, error.second) == (first, second)  # first in walk order
    assert str(first) in str(error)
    assert str(second) in str(error)


def test_a_duplicate_across_levels_is_refused_too(tmp_path) -> None:
    # R4: uniqueness spans parents, family entries, and variant leaves alike.
    _write_bundle(tmp_path, "shared")  # a level-1 skill
    _write_bundle(tmp_path, "group")  # a level-1 group parent
    _write_bundle(tmp_path, "group", "shared")  # its level-2 variant

    with pytest.raises(skills.DuplicateSkillNameError) as excinfo:
        skills.SkillCatalogue(tmp_path)

    assert excinfo.value.name == "shared"


def test_a_bundle_outside_the_two_catalogue_levels_is_refused(tmp_path) -> None:
    # R2: every SKILL.md sits at exactly level 1 or level 2 under the
    # catalogue; a deeper bundle would be invisible to the flat-leaf index, so
    # the mount refuses it loudly instead of dropping a skill silently.
    level_zero = tmp_path / "level-zero"
    _write_bundle(level_zero)
    with pytest.raises(skills.SkillLayoutError, match="level-zero"):
        skills.SkillCatalogue(level_zero)

    too_deep = tmp_path / "too-deep"
    _write_bundle(too_deep, "group", "variant", "too-deep")
    with pytest.raises(skills.SkillLayoutError, match="too-deep"):
        skills.SkillCatalogue(too_deep)


def test_a_bundle_named_the_logical_root_is_refused(tmp_path) -> None:
    # R1: no directory under the catalogue carries the logical root's name - a
    # skill named after the root would put the identity into a skill name.
    _write_bundle(tmp_path, skills.LOGICAL_SUITE_ROOT)

    with pytest.raises(skills.SkillLayoutError, match=skills.LOGICAL_SUITE_ROOT):
        skills.SkillCatalogue(tmp_path)


# --- R8: the skill-local bundle ------------------------------------------------


def test_bundles_resolve_inside_their_own_leaf_at_either_level(tmp_path) -> None:
    parent = _write_bundle(tmp_path, "group")
    variant = _write_bundle(tmp_path, "group", "variant")
    (parent / "references").mkdir()
    (parent / "references" / "rules.md").write_text("rules\n", encoding="utf-8")
    (variant / "scripts").mkdir()
    (variant / "scripts" / "probe.py").write_text("print('probe')\n", encoding="utf-8")
    catalogue = skills.SkillCatalogue(tmp_path)

    # R8: `references/` and `scripts/` stay skill-local, at either level.
    assert catalogue.bundle_path("group") == parent
    assert catalogue.bundle_path("group", "references/rules.md") == (
        parent / "references" / "rules.md"
    )
    assert catalogue.bundle_path("variant", "scripts/probe.py") == (
        variant / "scripts" / "probe.py"
    )
    assert catalogue.bundle_path("variant", "scripts/probe.py").is_file()
    # The variant resolves its own leaf, never its parent's directory.
    variant_rules = catalogue.bundle_path("variant", "references/rules.md")
    assert variant_rules == variant / "references" / "rules.md"
    assert variant_rules != parent / "references" / "rules.md"


def test_a_bundle_path_cannot_escape_the_leaf(tmp_path) -> None:
    _write_bundle(tmp_path, "group")
    _write_bundle(tmp_path, "group", "variant")
    catalogue = skills.SkillCatalogue(tmp_path)

    # The separator rule of `validate_path_component` applies here too: a
    # backslash target would traverse the bundle on Windows.
    for hostile in ("../SKILL.md", "../group/SKILL.md", "/etc/passwd", "..\\evil"):
        with pytest.raises(ValueError):
            catalogue.bundle_path("variant", hostile)
    # An unknown skill resolves nothing, whatever the artefact.
    assert catalogue.bundle_path("ghost", "references/rules.md") is None


# --- fail-open mounting and the untouched live root ---------------------------


def test_a_missing_root_mounts_empty_and_degrades(tmp_path) -> None:
    # The loader discipline holds at the mount too: a missing mount is an empty
    # catalogue, never a crash (no I/O at import; reads degrade to the fallback).
    catalogue = skills.SkillCatalogue(tmp_path / "no-such-mount")

    assert catalogue.list_skills() == []
    assert skills.list_skills(catalogue=catalogue) == []
    assert catalogue.read("anything") == ""
    assert catalogue.read("anything", fallback="FALLBACK") == "FALLBACK"
    assert catalogue.meta("anything") == {}
    assert catalogue.bundle_path("anything") is None


def test_a_malformed_live_tree_degrades_to_an_empty_catalogue(
    tmp_path, monkeypatch, caplog
) -> None:
    # The default live mount is fail-open: a tree that fails to index (here a
    # duplicate leaf name) degrades to an empty catalogue with ONE loud log, so
    # a broken deployment never raises into an agent turn.
    _write_bundle(tmp_path, "alpha")
    _write_bundle(tmp_path, "beta")
    _write_bundle(tmp_path, "alpha", "shared-leaf")
    _write_bundle(tmp_path, "beta", "shared-leaf")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)

    with caplog.at_level(logging.ERROR, logger="polymerhus.app.llm.skills"):
        assert skills.list_skills() == []
        assert skills.skill_for("shared-leaf") == ""
        assert skills.skill_meta("shared-leaf") == {}

    mount_logs = [
        record
        for record in caplog.records
        if "failed to mount" in record.getMessage()
    ]
    assert len(mount_logs) == 1  # one log per failed snapshot, never per read
    assert mount_logs[0].levelno == logging.ERROR

    # The fallback is the LIVE mount's contract only: an explicit mount of the
    # same malformed tree raises at construction.
    with pytest.raises(skills.DuplicateSkillNameError):
        skills.SkillCatalogue(tmp_path)


def test_clear_cache_picks_up_a_newly_added_skill(tmp_path, monkeypatch) -> None:
    # `clear_cache` drops the live-root index snapshot (the hot-reload seam):
    # a skill added after the first scan stays invisible until the cache clears,
    # then indexes without a new process.
    _write_bundle(tmp_path, "first")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path)
    assert skills.list_skills() == ["first"]

    _write_bundle(tmp_path, "second")
    assert skills.list_skills() == ["first"]  # the snapshot is still the old tree

    skills.clear_cache()
    assert skills.list_skills() == ["first", "second"]


def test_the_default_resolution_mounts_the_live_root(suite) -> None:
    # The mount replacement: no `catalogue=` is needed for a nested suite leaf,
    # and the flat product skills and the path-shaped meta family resolve too.
    assert skills.skill_for("jwt-claims-confusion") == suite.read(
        "jwt-claims-confusion"
    )
    assert skills.skill_for("idor-direct-object-swap") == suite.read(
        "idor-direct-object-swap"
    )
    assert skills.skill_for("webpage-analysis") == suite.read("webpage-analysis")
    assert skills.skill_for("meta/meta-usage-skill") == suite.read(
        "meta/meta-usage-skill"
    )
    assert skills.list_skills() == suite.list_skills()
    assert skills.skill_meta("jwt-claims-confusion") == suite.meta(
        "jwt-claims-confusion"
    )
    assert skills.validate_skill("sql-injection-second-order") == []


def test_load_skill_serves_a_suite_leaf_with_the_protocol(tmp_path) -> None:
    # The mount replacement reaches every read surface: `load_skill` resolves a
    # nested leaf through the live-root catalogue, appends the usage protocol,
    # and the meta exemption still keys on the path.
    store = skills.SkillStore(root_dir=tmp_path)
    tool = skills.build_load_skill_tool("proj-x", store=store)

    body = tool.invoke({"name": "jwt-claims-confusion"})
    assert body.startswith(skills.skill_for("jwt-claims-confusion"))
    assert body.endswith(
        skills.PROTOCOL_SEPARATOR + skills.skill_for("meta/meta-usage-skill")
    )
    assert tool.invoke({"name": "meta/meta-usage-skill"}) == skills.skill_for(
        "meta/meta-usage-skill"
    )


def test_the_default_catalogue_follows_a_repointed_root(tmp_path, monkeypatch) -> None:
    # The lazy live snapshot is keyed on the root it indexed, so a test (or a
    # hot reload) that repoints `_SKILLS_ROOT` never reads a stale index.
    first = tmp_path / "first"
    _write_bundle(first, "only-here")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", first)
    assert skills.list_skills() == ["only-here"]

    second = tmp_path / "second"
    _write_bundle(second, "elsewhere")
    monkeypatch.setattr(skills, "_SKILLS_ROOT", second)
    assert skills.list_skills() == ["elsewhere"]


def test_an_explicit_mount_still_wins(tmp_path) -> None:
    # `catalogue=` semantics are unchanged: an explicit mount indexes its own
    # root and never serves the live root's body (the cache is per root).
    bundle = tmp_path / "ssrf"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\nname: ssrf\ndescription: A mounted ssrf.\n"
        "metadata:\n  version: 1.0.0\n---\n\n# Mounted SSRF\n",
        encoding="utf-8",
    )
    mounted = skills.SkillCatalogue(tmp_path)

    assert skills.list_skills(catalogue=mounted) == ["ssrf"]
    assert skills.skill_for("ssrf", catalogue=mounted).startswith("# Mounted SSRF")
    assert "ssrf" in skills.list_skills()  # the live root carries its own bundle
    assert skills.skill_for("ssrf") != skills.skill_for("ssrf", catalogue=mounted)
    # The suite's logical root never appears in either catalogue's names.
    assert skills.LOGICAL_SUITE_ROOT not in skills.list_skills()
