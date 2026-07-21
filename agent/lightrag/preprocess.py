from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_OUTPUT_DIR = Path("data/lightrag/inputs/__preprocessed__")
DEFAULT_WSTG_OUTPUT_DIR = Path("data/lightrag/inputs/wstg_preprocessed")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WSTG_ID_RE = re.compile(r"\bWSTG-[A-Z]{4}-\d{2}\b")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_URL_RE = re.compile(r"https?://[^\s)>]+")


@dataclass(frozen=True)
class FacetSpec:
    key: str
    title: str
    description: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class SourceFragment:
    fragment_id: str
    source_id: str
    source_path: str
    document_title: str
    heading_path: tuple[str, ...]
    locator: str
    text: str
    line_start: int
    line_end: int
    block_type: str


@dataclass
class PreprocessResult:
    fragments: list[SourceFragment]
    fragment_facets: dict[str, list[str]]
    generated_files: list[Path] = field(default_factory=list)


DEFAULT_FACETS: tuple[FacetSpec, ...] = (
    FacetSpec(
        key="attack-methods",
        title="Attack Methods",
        description=(
            "Reusable offensive techniques, probes, exploit approaches, bypass "
            "methods, and chained attacker actions."
        ),
        keywords=(
            "attack",
            "attacktechnique",
            "technique",
            "probe",
            "exploit",
            "exploits",
            "bypasses",
            "bypass method",
            "bypass technique",
            "tamper",
            "tampering",
            "harvesting",
            "fixation",
            "payload",
            "chaining",
        ),
    ),
    FacetSpec(
        key="defenses-and-detections",
        title="Defenses And Detections",
        description=(
            "Controls, filters, validation layers, mitigations, detection signals, "
            "and conditions under which they observe or block behavior."
        ),
        keywords=(
            "defense",
            "defensive",
            "defensivetechnology",
            "control",
            "firewall",
            "waf",
            "filter",
            "filters",
            "filtered",
            "block",
            "blocking",
            "detect",
            "detects",
            "detectedby",
            "mitigate",
            "mitigates",
            "middleware",
            "enforcement",
            "validation",
        ),
    ),
    FacetSpec(
        key="prerequisites-and-environment",
        title="Prerequisites And Environment",
        description=(
            "Target states, environmental conditions, required capabilities, "
            "preconditions, and setup facts that make a method applicable."
        ),
        keywords=(
            "prerequisite",
            "precondition",
            "condition",
            "conditions",
            "environment",
            "environmentalcondition",
            "requires",
            "require",
            "required",
            "enables",
            "enable",
            "enabled",
            "when",
            "if ",
            "present",
            "state",
            "capability",
            "user-controlled",
            "low privileged",
            "normalization mismatch",
            "session rotation",
        ),
    ),
    FacetSpec(
        key="vulnerability-classes",
        title="Vulnerability Classes",
        description=(
            "Reusable weakness classes, vulnerability families, taxonomy names, "
            "and impact-oriented descriptions."
        ),
        keywords=(
            "vulnerability",
            "vulnerabilityclass",
            "weakness",
            "cwe",
            "owasp",
            "capec",
            "sql injection",
            "insecure direct object reference",
            "idor",
            "authentication bypass",
        ),
    ),
    FacetSpec(
        key="code-and-payload-examples",
        title="Code And Payload Examples",
        description=(
            "Code snippets, HTTP examples, payload examples, command examples, "
            "and concrete request or response material."
        ),
        keywords=(
            "payload",
            "snippet",
            "example request",
            "http request",
            "curl ",
            "code",
            "```",
            "<script",
            "union select",
        ),
    ),
    FacetSpec(
        key="source-context",
        title="Source Context",
        description=(
            "Source material that does not fit a narrower facet but may preserve "
            "document framing, definitions, or assumptions."
        ),
        keywords=(),
    ),
)

RELATION_KEYWORDS: tuple[str, ...] = (
    "bypasses",
    "requires",
    "exploits",
    "mitigates",
    "detectedby",
    "detected by",
    "enables",
    "blocks",
)

WSTG_FACET_TITLES: dict[str, tuple[str, str]] = {
    "overview": (
        "Overview",
        "Scenario summary, vulnerability framing, impact, and core testing purpose.",
    ),
    "test-objectives": (
        "Test Objectives",
        "Explicit objectives a tester should satisfy for this WSTG scenario.",
    ),
    "attack-methods": (
        "Attack Methods",
        "Concrete testing procedures, probes, exploitation approaches, and technique variants.",
    ),
    "prerequisites-and-environment": (
        "Prerequisites And Environment",
        "Target conditions, entry points, privileges, side channels, and applicability constraints.",
    ),
    "defenses-and-detections": (
        "Defenses And Detections",
        "Controls, validation behavior, mitigations, detection signals, and defensive limits.",
    ),
    "code-and-payload-examples": (
        "Code And Payload Examples",
        "Payloads, URLs, SQL snippets, command examples, and concrete request material.",
    ),
    "references": (
        "References",
        "Tools, external references, standards, and source reading material.",
    ),
    "source-context": (
        "Source Context",
        "Useful scenario context that did not match a narrower WSTG methodology facet.",
    ),
}


def _slug(value: str, *, fallback: str = "item") -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or fallback


def _clean_heading(value: str) -> str:
    return value.strip().strip("#").strip()


def _source_id(path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        stable_path = resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        stable_path = resolved.as_posix()
    suffix = hashlib.sha1(stable_path.encode("utf-8")).hexdigest()[:8]
    return f"{_slug(path.stem)}-{suffix}"


def _iter_source_files(source_paths: Iterable[str | Path]) -> list[Path]:
    files: list[Path] = []
    for source in source_paths:
        path = Path(source)
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file()
                and not child.name.startswith(".")
                and child.suffix.lower() in {".md", ".markdown", ".txt"}
            )
        elif path.is_file():
            files.append(path)
    return sorted(files)


def parse_markdown_source(source_path: str | Path) -> list[SourceFragment]:
    path = Path(source_path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    source_id = _source_id(path)
    document_title = path.stem.replace("-", " ").replace("_", " ").title()
    heading_stack: list[tuple[int, str]] = []
    fragments: list[SourceFragment] = []
    pending: list[str] = []
    block_start = 1
    block_type = "text"
    in_code = False
    fence_marker = ""

    def current_heading_path() -> tuple[str, ...]:
        return tuple(title for _, title in heading_stack)

    def flush(end_line: int) -> None:
        nonlocal pending, block_start, block_type
        raw = "\n".join(pending).strip()
        pending = []
        if not raw:
            return
        ordinal = len(fragments) + 1
        locator = f"{source_id}#f{ordinal:03d}"
        fragment_id = locator
        fragments.append(
            SourceFragment(
                fragment_id=fragment_id,
                source_id=source_id,
                source_path=path.as_posix(),
                document_title=document_title,
                heading_path=current_heading_path(),
                locator=locator,
                text=raw,
                line_start=block_start,
                line_end=max(block_start, end_line),
                block_type=block_type,
            )
        )

    for lineno, line in enumerate(lines, start=1):
        heading_match = _HEADING_RE.match(line)
        if heading_match and not in_code:
            flush(lineno - 1)
            level = len(heading_match.group(1))
            title = _clean_heading(heading_match.group(2))
            if level == 1 and len(fragments) == 0:
                document_title = title
            heading_stack = [(lvl, value) for lvl, value in heading_stack if lvl < level]
            heading_stack.append((level, title))
            continue

        fence_match = _CODE_FENCE_RE.match(line)
        if fence_match:
            if not pending:
                block_start = lineno
                block_type = "code"
            pending.append(line)
            marker = fence_match.group(1)
            if in_code and marker == fence_marker:
                in_code = False
                fence_marker = ""
                flush(lineno)
            else:
                in_code = True
                fence_marker = marker
            continue

        if in_code:
            pending.append(line)
            continue

        if not line.strip():
            flush(lineno - 1)
            continue

        if not pending:
            block_start = lineno
            stripped = line.strip()
            if stripped.startswith("|"):
                block_type = "table"
            elif _LIST_RE.match(line):
                block_type = "list"
            else:
                block_type = "text"
        pending.append(line)

    flush(len(lines))
    return fragments


def classify_fragment(fragment: SourceFragment, facets: Sequence[FacetSpec] = DEFAULT_FACETS) -> list[str]:
    haystack = fragment.text.lower()
    matched: list[str] = []
    for facet in facets:
        if facet.key == "source-context":
            continue
        if fragment.block_type == "code" and facet.key == "code-and-payload-examples":
            matched.append(facet.key)
            continue
        if any(_keyword_matches(haystack, keyword) for keyword in facet.keywords):
            matched.append(facet.key)
    if not matched:
        matched.append("source-context")
    return matched


def _keyword_matches(haystack: str, keyword: str) -> bool:
    normalized = keyword.strip().lower()
    if not normalized:
        return False
    if re.fullmatch(r"[a-z0-9]+", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", haystack) is not None
    return normalized in haystack


def is_relation_fragment(fragment: SourceFragment) -> bool:
    normalized = f" {re.sub(r'\\s+', ' ', fragment.text.lower())} "
    return any(f" {keyword} " in normalized for keyword in RELATION_KEYWORDS)


def build_preprocessed_documents(source_paths: Iterable[str | Path]) -> PreprocessResult:
    fragments: list[SourceFragment] = []
    fragment_facets: dict[str, list[str]] = {}
    for path in _iter_source_files(source_paths):
        for fragment in parse_markdown_source(path):
            fragments.append(fragment)
            fragment_facets[fragment.fragment_id] = classify_fragment(fragment)
    return PreprocessResult(fragments=fragments, fragment_facets=fragment_facets)


def _render_fragment(fragment: SourceFragment, facets: Sequence[str] | None = None) -> list[str]:
    lines = [
        f"## {fragment.locator}",
        "",
        f"- Source ID: {fragment.source_id}",
        f"- Source path: {fragment.source_path}",
        f"- Document title: {fragment.document_title}",
        f"- Heading path: {_format_heading_path(fragment.heading_path)}",
        f"- Source lines: {fragment.line_start}-{fragment.line_end}",
        f"- Block type: {fragment.block_type}",
    ]
    if facets:
        lines.append(f"- Matched facets: {', '.join(facets)}")
    lines.extend(["", fragment.text, ""])
    return lines


def _format_heading_path(heading_path: Sequence[str]) -> str:
    if not heading_path:
        return "(document root)"
    return " > ".join(heading_path)


def _detect_wstg_id(path: Path, fragments: Sequence[SourceFragment]) -> str:
    for value in (path.as_posix(), path.stem):
        match = _WSTG_ID_RE.search(value.upper())
        if match:
            return match.group(0)
    for fragment in fragments:
        match = _WSTG_ID_RE.search(fragment.text.upper())
        if match:
            return match.group(0)
    return f"WSTG-UNKN-{hashlib.sha1(path.as_posix().encode('utf-8')).hexdigest()[:2].upper()}"


def _detect_wstg_title(path: Path, fragments: Sequence[SourceFragment]) -> str:
    ignored_titles = {"wstg - latest", "id"}
    for fragment in fragments:
        for heading in fragment.heading_path:
            heading_text = heading.strip()
            if heading_text and heading_text.lower() not in ignored_titles:
                return heading_text
    return path.stem.replace("-", " ").replace("_", " ").title()


def _wstg_slug(wstg_id: str) -> str:
    return _slug(wstg_id.lower(), fallback="wstg-scenario")


def _unique_wstg_slug(wstg_id: str, source_file: Path, used_slugs: set[str]) -> str:
    base_slug = _wstg_slug(wstg_id)
    if base_slug not in used_slugs:
        used_slugs.add(base_slug)
        return base_slug

    source_slug = _slug(source_file.stem, fallback="source")
    candidate = f"{base_slug}-{source_slug}"
    if candidate in used_slugs:
        suffix = hashlib.sha1(source_file.as_posix().encode("utf-8")).hexdigest()[:8]
        candidate = f"{candidate}-{suffix}"
    used_slugs.add(candidate)
    return candidate


def _wstg_heading_text(fragment: SourceFragment) -> str:
    return " > ".join(fragment.heading_path).lower()


def _wstg_leaf_heading_text(fragment: SourceFragment) -> str:
    if not fragment.heading_path:
        return ""
    return fragment.heading_path[-1].lower()


def _looks_like_payload_or_code(fragment: SourceFragment) -> bool:
    text = fragment.text
    lowered = text.lower()
    return (
        fragment.block_type == "code"
        or bool(_INLINE_CODE_RE.search(text))
        or bool(_URL_RE.search(text))
        or "union select" in lowered
        or "select " in lowered and " from " in lowered
        or "sleep(" in lowered
        or "benchmark(" in lowered
        or "--" in text
        or " or " in lowered and "=" in text
    )


def classify_wstg_fragment(fragment: SourceFragment) -> list[str]:
    """Classify one WSTG source fragment into stable methodology facets."""
    heading = _wstg_leaf_heading_text(fragment)
    text = fragment.text.lower()
    facets: list[str] = []

    if _WSTG_ID_RE.search(fragment.text.upper()):
        facets.append("overview")
    if "summary" in heading:
        facets.append("overview")
    if "test objectives" in heading:
        facets.append("test-objectives")
    if (
        "how to test" in heading
        or "black-box" in heading
        or "white-box" in heading
        or "detection techniques" in heading
        or "testing for" in heading
        or "attack" in heading
    ):
        facets.append("attack-methods")
    if (
        "remediation" in heading
        or "mitigation" in heading
        or "countermeasure" in heading
        or "validation" in text
        or "sanitize" in text
        or "parameterized" in text
        or "prepared statement" in text
        or "detect" in text
    ):
        facets.append("defenses-and-detections")
    if (
        "reference" in heading
        or "tools" in heading
        or "suggested reading" in heading
        or "external references" in heading
    ):
        facets.append("references")
    if _looks_like_payload_or_code(fragment):
        facets.append("code-and-payload-examples")
    if (
        "requires" in text
        or "condition" in text
        or "privilege" in text
        or "input field" in text
        or "parameter" in text
        or "entry point" in text
        or "side channel" in text
        or "when " in text
        or "if " in text
    ):
        facets.append("prerequisites-and-environment")

    for generic_facet in classify_fragment(fragment):
        if generic_facet != "source-context":
            facets.append(generic_facet)

    deduped = list(dict.fromkeys(facets))
    return deduped or ["source-context"]


def primary_wstg_facet(fragment: SourceFragment, facets: Sequence[str]) -> str:
    heading = _wstg_leaf_heading_text(fragment)
    if "references" in facets or "reference" in heading or "tools" in heading:
        return "references"
    if "test-objectives" in facets:
        return "test-objectives"
    if "overview" in facets:
        return "overview"
    if "remediation" in heading or "mitigation" in heading or "defenses-and-detections" in facets:
        if "summary" not in heading:
            return "defenses-and-detections"
    if "code-and-payload-examples" in facets:
        return "code-and-payload-examples"
    if "attack-methods" in facets:
        return "attack-methods"
    if "prerequisites-and-environment" in facets:
        return "prerequisites-and-environment"
    if "vulnerability-classes" in facets or "overview" in facets:
        return "overview"
    return "source-context"


def _is_wstg_relation_candidate(fragment: SourceFragment, facets: Sequence[str]) -> bool:
    heading = _wstg_leaf_heading_text(fragment)
    text = fragment.text.lower()
    if fragment.block_type == "code":
        return False
    return (
        is_relation_fragment(fragment)
        or heading in {"summary", "test objectives", "how to test", "remediation"}
        or any(
            marker in text
            for marker in (
                "allows",
                "can read",
                "can modify",
                "can execute",
                "without proper",
                "without adequate",
                "interact with",
                "input validation",
            )
        )
    )


def _render_wstg_fragment(
    fragment: SourceFragment,
    *,
    wstg_id: str,
    title: str,
    facets: Sequence[str] | None = None,
) -> list[str]:
    lines = [
        f"### {fragment.locator}",
        "",
        (
            f"Source: {wstg_id} | {title} | "
            f"{_format_heading_path(fragment.heading_path)} | "
            f"lines {fragment.line_start}-{fragment.line_end} | "
            f"{fragment.block_type}"
        ),
    ]
    if facets:
        lines.append(f"Facets: {', '.join(facets)}")
    lines.extend(["", fragment.text, ""])
    return lines


def _render_wstg_document(
    *,
    wstg_id: str,
    title: str,
    facet_key: str,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    facet_title, description = WSTG_FACET_TITLES[facet_key]
    lines = [
        f"# {wstg_id} - {title}: {facet_title}",
        "",
        f"Purpose: {description}",
        "",
        (
            "Source boundary: this document is generated from OWASP WSTG source "
            "fragments. It is ontology-agnostic; LightRAG extracts the active "
            "ontology during indexing."
        ),
        "",
    ]
    if not fragments:
        lines.extend(["No source fragments matched this WSTG facet.", ""])
    for fragment in fragments:
        lines.extend(
            _render_wstg_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
                facets=fragment_facets.get(fragment.fragment_id, []),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_wstg_relation_briefs(
    *,
    wstg_id: str,
    title: str,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    lines = [
        f"# {wstg_id} - {title}: Relation Briefs",
        "",
        (
            "Purpose: preserve source-grounded operational claims connecting "
            "testing methods, target conditions, defensive behavior, vulnerability "
            "classes, and payload examples."
        ),
        "",
        (
            "Ontology boundary: these briefs do not encode a fixed entity schema. "
            "They are the preferred LightRAG input when the ontology changes."
        ),
        "",
    ]
    relation_fragments = [
        fragment
        for fragment in fragments
        if _is_wstg_relation_candidate(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
    ]
    if not relation_fragments:
        lines.extend(["No WSTG relation candidates were found.", ""])
    for fragment in relation_fragments:
        lines.extend(
            _render_wstg_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
                facets=fragment_facets.get(fragment.fragment_id, []),
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _wstg_relation_fragments(
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> list[SourceFragment]:
    return [
        fragment
        for fragment in fragments
        if _is_wstg_relation_candidate(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
    ]


def _render_wstg_composite_document(
    *,
    wstg_id: str,
    title: str,
    source_file: Path,
    fragments: Sequence[SourceFragment],
    fragment_facets: dict[str, list[str]],
) -> str:
    lines = [
        f"# {wstg_id} - {title}",
        "",
        "## Scenario Metadata",
        "",
        f"- WSTG ID: {wstg_id}",
        f"- Scenario title: {title}",
        f"- Source path: {source_file.as_posix()}",
        "- Document kind: OWASP WSTG methodology scenario",
        (
            "- Ontology boundary: this composite document is source-grounded and "
            "ontology-agnostic; LightRAG extracts the active ontology during indexing."
        ),
        "",
    ]

    for facet_key, (facet_title, description) in WSTG_FACET_TITLES.items():
        if facet_key == "source-context":
            continue
        facet_fragments = [
            fragment
            for fragment in fragments
            if primary_wstg_facet(
                fragment,
                fragment_facets.get(fragment.fragment_id, []),
            )
            == facet_key
        ]
        if not facet_fragments:
            continue
        lines.extend([f"## {facet_title}", "", f"Purpose: {description}", ""])
        for fragment in facet_fragments:
            lines.extend(
                _render_wstg_fragment(
                    fragment,
                    wstg_id=wstg_id,
                    title=title,
                    facets=fragment_facets.get(fragment.fragment_id, []),
                )
            )

    source_context = [
        fragment
        for fragment in fragments
        if primary_wstg_facet(
            fragment,
            fragment_facets.get(fragment.fragment_id, []),
        )
        == "source-context"
    ]
    if source_context:
        facet_title, description = WSTG_FACET_TITLES["source-context"]
        lines.extend([f"## {facet_title}", "", f"Purpose: {description}", ""])
        for fragment in source_context:
            lines.extend(
                _render_wstg_fragment(
                    fragment,
                    wstg_id=wstg_id,
                    title=title,
                    facets=fragment_facets.get(fragment.fragment_id, []),
                )
            )

    relation_fragments = _wstg_relation_fragments(fragments, fragment_facets)
    lines.extend(
        [
            "## Relation Briefs",
            "",
            (
                "Purpose: preserve source-grounded operational claims connecting "
                "testing methods, target conditions, defensive behavior, vulnerability "
                "classes, and payload examples."
            ),
            "",
        ]
    )
    if not relation_fragments:
        lines.extend(["No WSTG relation candidates were found.", ""])
    for fragment in relation_fragments:
        lines.extend(
            _render_wstg_fragment(
                fragment,
                wstg_id=wstg_id,
                title=title,
                facets=fragment_facets.get(fragment.fragment_id, []),
            )
        )

    return "\n".join(lines).rstrip() + "\n"


def _render_facet_document(facet: FacetSpec, fragments: Sequence[SourceFragment]) -> str:
    lines = [
        f"# {facet.title}",
        "",
        f"Purpose: {facet.description}",
        "",
        (
            "Ontology boundary: this document groups source material by a stable "
            "methodology facet. It does not encode the active LightRAG ontology."
        ),
        "",
    ]
    if not fragments:
        lines.extend(["No source fragments matched this facet.", ""])
    for fragment in fragments:
        lines.extend(_render_fragment(fragment))
    return "\n".join(lines).rstrip() + "\n"


def _render_relation_briefs(result: PreprocessResult) -> str:
    relation_fragments = [
        fragment for fragment in result.fragments if is_relation_fragment(fragment)
    ]
    lines = [
        "# Relation Briefs",
        "",
        (
            "Purpose: preserve operational claims that connect methods, defenses, "
            "conditions, vulnerabilities, code, and observed limitations."
        ),
        "",
        (
            "Ontology boundary: relation briefs are source-grounded and ontology-"
            "agnostic. The current LightRAG ontology may extract typed edges from "
            "them, but the briefs remain valid when that ontology changes."
        ),
        "",
    ]
    if not relation_fragments:
        lines.extend(["No relation-like source fragments were found.", ""])
    for fragment in relation_fragments:
        facets = result.fragment_facets.get(fragment.fragment_id, [])
        lines.extend(_render_fragment(fragment, facets=facets))
    return "\n".join(lines).rstrip() + "\n"


def _manifest_payload(result: PreprocessResult) -> dict:
    return {
        "schema_version": 1,
        "primary_document": "relation-briefs.md",
        "ontology_boundary": (
            "Generated documents are ontology-agnostic methodology views. "
            "LightRAG ontology extraction happens after this preprocessing step."
        ),
        "fragments": [
            {
                **asdict(fragment),
                "facets": result.fragment_facets.get(fragment.fragment_id, []),
                "is_relation_brief": is_relation_fragment(fragment),
            }
            for fragment in result.fragments
        ],
        "generated_files": [path.as_posix() for path in result.generated_files],
    }


def write_preprocessed_documents(
    result: PreprocessResult,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    facets: Sequence[FacetSpec] = DEFAULT_FACETS,
) -> PreprocessResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    generated_files: list[Path] = []

    relation_path = output_path / "relation-briefs.md"
    relation_path.write_text(_render_relation_briefs(result), encoding="utf-8")
    generated_files.append(relation_path)

    for facet in facets:
        facet_fragments = [
            fragment
            for fragment in result.fragments
            if facet.key in result.fragment_facets.get(fragment.fragment_id, [])
        ]
        doc_path = output_path / f"{facet.key}.md"
        doc_path.write_text(_render_facet_document(facet, facet_fragments), encoding="utf-8")
        generated_files.append(doc_path)

    result.generated_files = generated_files
    manifest_path = output_path / ".manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_payload(result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    generated_files.append(manifest_path)
    return result


def _wstg_manifest_payload(
    result: PreprocessResult,
    scenarios: Sequence[dict],
    *,
    debug_facets: bool,
) -> dict:
    return {
        "schema_version": 3,
        "profile": "wstg",
        "primary_document_pattern": "<wstg-id>-methodology.md",
        "debug_facets": debug_facets,
        "ontology_boundary": (
            "Generated WSTG composite documents are ontology-agnostic methodology "
            "views. LightRAG v1.5 applies the active entity prompt profile during "
            "indexing."
        ),
        "scenarios": list(scenarios),
        "fragments": [
            {
                **asdict(fragment),
                "facets": result.fragment_facets.get(fragment.fragment_id, []),
            }
            for fragment in result.fragments
        ],
        "generated_files": [path.as_posix() for path in result.generated_files],
    }


def preprocess_wstg_for_lightrag(
    source_paths: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_WSTG_OUTPUT_DIR,
    *,
    debug_facets: bool = False,
) -> PreprocessResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    all_fragments: list[SourceFragment] = []
    all_fragment_facets: dict[str, list[str]] = {}
    generated_files: list[Path] = []
    scenarios: list[dict] = []
    used_slugs: set[str] = set()

    for source_file in _iter_source_files(source_paths):
        fragments = parse_markdown_source(source_file)
        if not fragments:
            continue
        wstg_id = _detect_wstg_id(source_file, fragments)
        title = _detect_wstg_title(source_file, fragments)
        slug = _unique_wstg_slug(wstg_id, source_file, used_slugs)
        fragment_facets = {
            fragment.fragment_id: classify_wstg_fragment(fragment)
            for fragment in fragments
        }

        all_fragments.extend(fragments)
        all_fragment_facets.update(fragment_facets)

        composite_path = output_path / f"{slug}-methodology.md"
        composite_path.write_text(
            _render_wstg_composite_document(
                wstg_id=wstg_id,
                title=title,
                source_file=source_file,
                fragments=fragments,
                fragment_facets=fragment_facets,
            ),
            encoding="utf-8",
        )
        generated_files.append(composite_path)

        debug_files: list[str] = []
        if debug_facets:
            debug_dir = output_path / "_debug_facets"
            debug_dir.mkdir(parents=True, exist_ok=True)
            relation_path = debug_dir / f"{slug}-relation-briefs.md"
            relation_path.write_text(
                _render_wstg_relation_briefs(
                    wstg_id=wstg_id,
                    title=title,
                    fragments=fragments,
                    fragment_facets=fragment_facets,
                ),
                encoding="utf-8",
            )
            generated_files.append(relation_path)
            debug_files.append(relation_path.as_posix())

            for facet_key in WSTG_FACET_TITLES:
                facet_fragments = [
                    fragment
                    for fragment in fragments
                    if facet_key in fragment_facets.get(fragment.fragment_id, [])
                ]
                if not facet_fragments and facet_key != "source-context":
                    continue
                doc_path = debug_dir / f"{slug}-{facet_key}.md"
                doc_path.write_text(
                    _render_wstg_document(
                        wstg_id=wstg_id,
                        title=title,
                        facet_key=facet_key,
                        fragments=facet_fragments,
                        fragment_facets=fragment_facets,
                    ),
                    encoding="utf-8",
                )
                generated_files.append(doc_path)
                debug_files.append(doc_path.as_posix())

        scenarios.append(
            {
                "wstg_id": wstg_id,
                "title": title,
                "source_path": source_file.as_posix(),
                "fragments": len(fragments),
                "primary_document": composite_path.name,
                "debug_files": debug_files,
            }
        )

    result = PreprocessResult(
        fragments=all_fragments,
        fragment_facets=all_fragment_facets,
        generated_files=generated_files,
    )
    manifest_path = output_path / ".manifest.json"
    manifest_path.write_text(
        json.dumps(
            _wstg_manifest_payload(result, scenarios, debug_facets=debug_facets),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    generated_files.append(manifest_path)
    return result


def preprocess_sources_for_lightrag(
    source_paths: Iterable[str | Path],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> PreprocessResult:
    result = build_preprocessed_documents(source_paths)
    return write_preprocessed_documents(result, output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preprocess methodology documents into LightRAG-ready facet documents."
    )
    parser.add_argument("sources", nargs="+", help="Source Markdown/text files or directories.")
    parser.add_argument(
        "--profile",
        choices=("generic", "wstg"),
        default="generic",
        help="Preprocessing profile to apply.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where generated LightRAG input documents are written.",
    )
    parser.add_argument(
        "--debug-facets",
        action="store_true",
        help="For the WSTG profile, also write per-facet debug documents under _debug_facets/.",
    )
    args = parser.parse_args(argv)

    if args.profile == "wstg":
        output_dir = args.output_dir or DEFAULT_WSTG_OUTPUT_DIR
        result = preprocess_wstg_for_lightrag(
            args.sources,
            output_dir,
            debug_facets=args.debug_facets,
        )
    else:
        output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
        result = preprocess_sources_for_lightrag(args.sources, output_dir)
    if args.profile == "wstg":
        relation_count = sum(
            1
            for fragment in result.fragments
            if _is_wstg_relation_candidate(
                fragment,
                result.fragment_facets.get(fragment.fragment_id, []),
            )
        )
    else:
        relation_count = sum(1 for fragment in result.fragments if is_relation_fragment(fragment))
    summary = {
        "profile": args.profile,
        "fragments": len(result.fragments),
        "relation_briefs": relation_count,
        "generated_files": [path.as_posix() for path in result.generated_files],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
