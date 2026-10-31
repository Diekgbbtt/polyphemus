"""The per-project unit threat model store (S2 4, 5, and 10; T1 #374).

One model document per discretely testable L1 unit, plus one threat file per
dispatchable threat, under the project's threat-modeller bucket:

    data/<project_id>/hunting/threat_modeller/
      notes.yaml                       (bounded episodic notes)
      produced/<unit_name>/
        <unit_name>.yaml               (the model document; the commit marker)
        threat-<rank>.yaml               (one per non-`none` threat, at COMPLETED)
      consumed/<unit_name>/            (the mover's target; at-least-once)
      abandoned/<unit_name>/           (a degraded or invalid model)

`<unit_name>` sanitises `:` and `/` to `-`. The store OWNS every derived
symbol (S2 10.2): the unit directory, the model file name, the threat file name,
the threat id, the dispatch id `<unit_name>__<threat_id>`, and the note key prefix.
The model id is the unit id and stays authoritative.

Write contract:

- A write payload carries only values: `{state, sections}` (plus the
  harness-bound `run_id`). The store derives and binds the identity.
- The state is monotonic (S2 5.3): a lower-gate write merges its section but
  never regresses the persisted state.
- Every write parses the merged document as `PartialThreatModel`; an unknown
  field or a malformed section is rejected loudly. No semantic gate runs at an
  intermediate gate.
- The COMPLETED write (S2 4.3, 5.6) normalises the threats, computes the
  `risk_profile`, runs the non-blocking completion checker, writes the threat
  files first, then commits the model document. A gate write below COMPLETED
  deletes stale produced threat files (crash repair); the next COMPLETED write
  rewrites the whole set.
- The assessment write (schema-5 spec 2/4): `write_impact_assessment` is the
  sole writer of one `impact_assessment` row. It loads the produced v5
  document, accepts the row at `PRIOR_ART`/`IMPACT_ASSESSED`, validates the row
  and its references, DERIVES `risk`/`risk_vector` from the authored factors
  inside the commit, merges by row id, advances the state to
  `IMPACT_ASSESSED`, and commits atomically. A v4 document is refused.
- A move-aware write (S2 4.5): a write whose identity already lives in
  `consumed/` is a no-op success returning the consumed path. The store never
  recreates a consumed file.
- A name collision (S2 4.2): two distinct unit ids that sanitise to the same
  `<unit_name>` are disambiguated with `-<first 8 hex of sha256(unit_id)>` on
  the later name. The store checks the existing directory's model `unit_id`
  before it writes; a readable DIFFERENT id triggers the suffix. An empty
  directory (a crash between the atomic write's parent mkdir and its replace)
  is reused, and an UNREADABLE model document refuses with a coded error -
  never a suffix (which would fork one unit into two directories) and never a
  clobber (the identity is unknown).
- The notes file uses the shared bounded whole-file primitive (`#341`); the
  model and threat files are single-model files and are not bounded records.
- Every whole-file write routes through the shared atomic primitive (`#340`),
  so a killed write leaves the previous complete file.

Read contract:

- `_load_document` returns the TYPED record: the v5 `PartialThreatModel` for the
  current schema, and the raw `RawThreatModel` wrapper for a v4 (and, on a
  legacy read, a v2/v3) document. A raw document is never normalised and never
  re-scored; it renders back to its persisted mapping, so the prior art and the
  measurement read the v4 fields as they were written.
- `query_prior_art` is the prior-art query (S2 7): one record kind, a
  non-empty AND list of regex field filters, project-scoped, over the produced
  and consumed models. It excludes the bound unit unless a filter path is
  `unit_id` and returns summaries, never a full model.

Fail-open canon: a read failure degrades (a warning, then None/[]), never a
raise into the caller. A write failure raises to the caller (O3). An unknown
`schema_version` refuses to load (a warning records the version) and refuses a
merge; a v4 (or older) document reads raw but is REFUSED as a write target,
because a stale model must never be mixed into a v5 run. There is no silent
migration.

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import AbstractSet, Any

import yaml

from polymerhus.app.data_root import DATA_ROOT, project_dir
from polymerhus.app.memory.bounds import notes_body_len
from polymerhus.app.memory.store import BoundedRecordStore

from .threat_model import (
    GATE_SECTIONS,
    LEGACY_SCHEMA_VERSIONS,
    PREVIOUS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    STATE_ORDER,
    FieldFilter,
    ImpactAssessment,
    ImpactDisposition,
    ModelState,
    PartialThreatModel,
    PriorArtKind,
    RawThreatModel,
    RiskMetrics,
    ThreatQueryMatch,
    ThreatQueryResult,
    UnitThreatModel,
    check_completion,
    compute_risk,
    compute_risk_profile,
    document_of,
    normalise_threats,
    prior_art_paths,
    unit_kind_from_unit_id,
    validate_metrics,
)

# The oldest read-only legacy schema: the intake and the measurement read a v2
# model raw when they ask for a legacy read; the mover and the prior-art query
# do not. A v3 document reads raw on the same opt-in. A v4 document reads raw
# ALWAYS (schema-5 spec 11, prior art and measurement); none of them is ever
# normalised or re-scored.
LEGACY_SCHEMA_VERSION = 2

# The typed result of one document read: the v5 model parsed as the persisted
# `PartialThreatModel`, or the raw legacy wrapper. Both render back to the
# document mapping through `document_of`.
LoadedDocument = PartialThreatModel | RawThreatModel


logger = logging.getLogger(__name__)

# The model directories (S2 4.2). A threat file lives only in produced/ or
# consumed/; abandoned/ holds the whole unit directory the harness archives.
_FAMILIES = ("produced", "consumed", "abandoned")
_READ_FAMILIES = ("produced", "consumed")

# The notes bound (#341): the same shared primitive and a size ceiling that
# matches the other whole-file hunting notes stores.
NOTES_MAX_RECORDS = 2000
NOTES_MAX_BYTES = 4 * 1024 * 1024

# The existing note kinds (the pattern's #137 Q3). `phase_summary` is the
# hunter's kind and is NOT available to the modeller (S1 5.2).
NOTE_KINDS = (
    "hypothesis_refusal",
    "implicit_test_primitive",
    "wellformedness",
    "freeform",
)

_NOTE_ACTIONS = ("append", "update", "delete")

# The prior-art query contract bounds (S2 section 7).
QUERY_DEFAULT_LIMIT = 20
QUERY_MAX_LIMIT = 50
QUERY_PATH_MAX_CHARS = 120
QUERY_REGEX_MAX_CHARS = 200
QUERY_MATCH_VALUE_MAX_CHARS = 500


class ThreatQueryError(ValueError):
    """A prior-art query the store refuses (a coded teaching rejection).

    `fields` names the request field(s) the model must correct, so the tool can
    return its field-naming rejection instead of a bare raise. The store owns
    the validation because the path catalog and the compiled regex belong to
    the query engine, never to the tool's argument shape.
    """

    def __init__(self, fields: list[str], message: str):
        super().__init__(message)
        self.fields = list(fields)


def sanitise_unit_name(unit_id: str) -> str:
    """The unit directory name (S2 4.2): `:` and `/` become `-`.

    The unit id stays authoritative; the name is the derived on-disk symbol.
    An id that cannot form one safe path component is a coded rejection, never
    a silently composed degenerate name.
    """
    name = unit_id.replace(":", "-").replace("/", "-")
    if not name or name in (".", ".."):
        raise ThreatModelIdentityError(
            ["unit_id"],
            f"threat model store: unit id {unit_id!r} derives an unsafe unit "
            f"directory name {name!r}",
        )
    if any(ord(char) < 32 for char in name) or "\\" in name:
        raise ThreatModelIdentityError(
            ["unit_id"],
            f"threat model store: unit id {unit_id!r} contains a control or "
            f"path character the derived name {name!r} cannot carry",
        )
    return name


def collision_suffix(unit_id: str) -> str:
    """The collision disambiguator: the first 8 hex of sha256(unit_id)."""
    return hashlib.sha256(unit_id.encode("utf-8")).hexdigest()[:8]


def dispatch_id(unit_name: str, threat_id: str) -> str:
    """The threat file's dispatch identity: `<unit_name>__<threat_id>` (S2 8.1)."""
    return f"{unit_name}__{threat_id}"


def threat_file_name(threat_id: str) -> str:
    """The threat file name: `threat-<rank>.yaml` (S2 4.2), derived from the id."""
    return f"{threat_id}.yaml"


# The store-owned threat id form; a caller-supplied key that is not one is a
# coded rejection (the derived-symbol discipline).
_THREAT_ID_RE = re.compile(r"threat-\d+")


# The assessment-row id and capability-id forms (schema-5 spec 2): the model
# authors both, so the assessment write validates them before the row joins the
# document. Case-insensitive, because the contract's prefixes are `IA-`/`P-` and
# the fixtures write them lowercase.
_IMPACT_ID_RE = re.compile(r"IA-[A-Za-z0-9][A-Za-z0-9._-]*", re.IGNORECASE)
_CAPABILITY_ID_RE = re.compile(r"P-[A-Za-z0-9][A-Za-z0-9._-]*", re.IGNORECASE)

# The gates at which one assessment row may be written (schema-5 spec 4). The
# `assess_impact` tool is the row's sole writer; the gate below `PRIOR_ART` has
# no vulnerabilities to reference yet, and a `COMPLETED` model is decided and is
# never extended.
_ASSESSMENT_WRITE_STATES: tuple[ModelState, ...] = (
    ModelState.PRIOR_ART,
    ModelState.IMPACT_ASSESSED,
)


def is_threat_id(value: Any) -> bool:
    """True for a store-owned threat id (`threat-<rank>`, S2 10.2). The ONE form
    check: the store's write keys and the mover's dispatch validity predicate
    both read it, so a threat id cannot mean two things."""
    return isinstance(value, str) and _THREAT_ID_RE.fullmatch(value) is not None


def _threat_rank(stem: str) -> int:
    """The numeric rank of a `threat-<rank>` file stem; a non-numeric stem sorts
    first (it can never be a store-written threat file)."""
    suffix = stem.removeprefix("threat-")
    return int(suffix) if suffix.isdigit() else 0


@dataclass(frozen=True)
class _FamilyState:
    """One family directory's read of a derived unit name (S2 4.2)."""

    directory: bool
    model: bool
    unit_id: str | None


class ThreatModelIdentityError(ValueError):
    """A write whose derivation input is missing or malformed (the coded
    teaching rejection of the store-write decisions). `fields` names the
    attribute(s) so the tool can return a field-naming rejection."""

    def __init__(self, fields: list[str], message: str):
        super().__init__(message)
        self.fields = list(fields)


class ImpactAssessmentError(ValueError):
    """An assessment row the store refuses (a coded teaching rejection).

    `fields` names the row field(s) the caller must correct, so the
    `assess_impact` tool can return its field-naming rejection instead of a
    bare raise. The store owns the row validation because the referential
    checks and the factor rules belong to the document, not to the tool's
    argument shape.
    """

    def __init__(self, fields: list[str], message: str):
        super().__init__(message)
        self.fields = list(fields)


class ThreatModelSchemaVersionError(ValueError):
    """An existing document cannot be read under the reader's schema.

    Either its `schema_version` is not the reader's - there is no silent
    migration (S2 5.8), so the merge refuses and records the version - or the
    body is unreadable/no longer a mapping, in which case merging into it would
    destroy state it still holds."""

    def __init__(self, path: Path, version: Any):
        super().__init__(
            f"threat model store: cannot merge into {path} - unknown "
            f"schema_version {version!r} (this reader knows {SCHEMA_VERSION} "
            f"only) or an unreadable body"
        )
        self.path = path
        self.version = version


class UnitDirectoryCollisionError(ValueError):
    """Both the plain and the collision-suffixed unit names are held by a
    different unit id: writing would clobber another unit's model."""


class ThreatModelDirectoryError(ValueError):
    """A unit directory exists at the derived name and cannot be reused.

    Its model document is unreadable (a truncated or hand-edited file), or the
    produced/consumed/abandoned copies disagree on the unit id. The store
    refuses the write: the collision suffix is reserved for a readable,
    genuinely different unit id, and guessing a second directory would
    silently fork one unit's model."""

    def __init__(self, name: str):
        super().__init__(
            f"threat model store: unit directory {name!r} carries an unreadable "
            f"model document or disagreeing unit ids; refusing to write rather "
            f"than create a second directory for the same unit"
        )
        self.name = name


class ThreatModelDocumentError(ValueError):
    """An existing model document cannot be merged.

    Its persisted `state` is not one of the seven workflow gates (a corrupt or
    foreign document). The store refuses with a coded error instead of a raw
    pydantic/enum `ValueError`."""

    def __init__(self, path: Path, state: Any):
        super().__init__(
            f"threat model store: {path} carries unknown state {state!r}; "
            f"known: {tuple(member.value for member in ModelState)}"
        )
        self.path = path
        self.state = state


# --- the prior-art query engine helpers (S2 section 7) -----------------------

# The model section each non-threat query kind reads. The `threat` view is the
# threat file merged with these sections, so it is built separately.
_QUERY_SECTION_BY_KIND: dict[PriorArtKind, str] = {
    PriorArtKind.IMPACT: "impact_assessment",
    PriorArtKind.PRECURSOR: "impact_assessment",
    PriorArtKind.VULNERABILITY: "vulnerabilities",
    PriorArtKind.ASSUMPTION: "assumptions",
}


def _records_by_id(value: Any) -> dict[str, dict]:
    """The section records keyed by their `id`, skipping malformed entries."""
    records: dict[str, dict] = {}
    for item in value or []:
        if not isinstance(item, Mapping):
            continue
        record_id = item.get("id")
        if isinstance(record_id, str) and record_id:
            records[record_id] = dict(item)
    return records


def _query_leaf_values(value: Any) -> list[Any]:
    """The values one resolved path contributes to matching.

    A dict is matched on its JSON string (S2 section 7); a list is iterated
    element-wise (the `evidence_refs` example names a leaf list without a `*`);
    `None` is absent and never matches.
    """
    if isinstance(value, Mapping):
        return [json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)]
    if isinstance(value, list):
        values: list[Any] = []
        for item in value:
            values.extend(_query_leaf_values(item))
        return values
    if value is None:
        return []
    return [value]


def _resolve_query_path(value: Any, segments: Sequence[str]) -> list[Any]:
    """Every leaf value at one dotted path, `*` iterating a list."""
    if not segments:
        return _query_leaf_values(value)
    head, rest = segments[0], segments[1:]
    if head == "*":
        if not isinstance(value, list):
            return []
        values: list[Any] = []
        for item in value:
            values.extend(_resolve_query_path(item, rest))
        return values
    if not isinstance(value, Mapping) or head not in value:
        return []
    return _resolve_query_path(value[head], rest)


def _query_searchable(value: Any) -> str:
    """The string one leaf value is matched on."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json_safe(value: Any) -> Any:
    """A matched value in the result payload's JSON-safe form.

    A structured value is stringified and truncated: the result is a summary,
    never a full record body smuggled through a dict path."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if len(text) <= QUERY_MATCH_VALUE_MAX_CHARS:
        return text
    return text[:QUERY_MATCH_VALUE_MAX_CHARS] + "..."


def _parse_query_filters(
    kind: PriorArtKind, filters: Sequence[Any],
) -> list[tuple[str, re.Pattern[str]]]:
    """Validate and compile one query's filters.

    An empty list, an unknown path, an over-long path or regex, an unsupported
    flag, and an invalid regex are coded teaching rejections (S2 section 7).
    """
    if not filters:
        raise ThreatQueryError(
            ["filters"],
            "a prior-art query needs at least one filter of "
            "{path, regex, flags}; an empty list would dump the store",
        )
    accepted = prior_art_paths(kind)
    parsed: list[tuple[str, re.Pattern[str]]] = []
    for index, raw in enumerate(filters):
        prefix = f"filters[{index}]"
        if isinstance(raw, FieldFilter):
            path, regex, flags = raw.path, raw.regex, raw.flags
        elif isinstance(raw, Mapping):
            path = raw.get("path")
            regex = raw.get("regex")
            flags = raw.get("flags", "i")
        else:
            raise ThreatQueryError(
                [prefix], "a filter must be an object of {path, regex, flags}")
        if not isinstance(path, str) or not path.strip():
            raise ThreatQueryError(
                [f"{prefix}.path"], "a filter needs a non-empty dotted `path`")
        path = path.strip()
        if len(path) > QUERY_PATH_MAX_CHARS:
            raise ThreatQueryError(
                [f"{prefix}.path"],
                f"path {path!r} is longer than {QUERY_PATH_MAX_CHARS} characters",
            )
        if path not in accepted:
            raise ThreatQueryError(
                [f"{prefix}.path"],
                f"unknown path {path!r} for kind {kind.value}; accepted paths: "
                f"{', '.join(accepted)}",
            )
        if not isinstance(regex, str):
            raise ThreatQueryError(
                [f"{prefix}.regex"], "a filter needs a `regex` string")
        if len(regex) > QUERY_REGEX_MAX_CHARS:
            raise ThreatQueryError(
                [f"{prefix}.regex"],
                f"regex is longer than {QUERY_REGEX_MAX_CHARS} characters",
            )
        if flags not in ("", "i"):
            raise ThreatQueryError(
                [f"{prefix}.flags"],
                "`flags` is 'i' for case-insensitive or '' for case-sensitive",
            )
        try:
            pattern = re.compile(regex, re.IGNORECASE if flags == "i" else 0)
        except re.error as exc:
            raise ThreatQueryError(
                [f"{prefix}.regex"],
                f"invalid regex {regex!r}: {exc}; correct the expression and "
                f"retry",
            ) from exc
        parsed.append((path, pattern))
    return parsed


def _match_query_filters(
    view: Mapping[str, Any], parsed: Sequence[tuple[str, re.Pattern[str]]],
) -> list[dict] | None:
    """The `matched` path/value pairs when EVERY filter matches, else None.

    The filters are AND: each must match at least one value at its path, and
    every value that matches contributes one pair in filter order.
    """
    matched: list[dict] = []
    for path, pattern in parsed:
        values = _resolve_query_path(view, path.split("."))
        hits = [value for value in values if pattern.search(_query_searchable(value))]
        if not hits:
            return None
        for value in hits:
            matched.append({"path": path, "value": _json_safe(value)})
    return matched


def _evidence_refs(entries: Any) -> list[str]:
    """The deduplicated evidence refs of a record's `evidences`/`evidence_refs`."""
    refs: list[str] = []
    for entry in entries or []:
        if isinstance(entry, Mapping):
            ref = entry.get("ref")
        elif isinstance(entry, str):
            ref = entry
        else:
            continue
        if isinstance(ref, str) and ref and ref not in refs:
            refs.append(ref)
    return refs


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _threat_view(
    record: Mapping[str, Any],
    rows: Mapping[str, dict],
    precursors: Mapping[str, dict],
    document: Mapping[str, Any],
) -> dict:
    """One threat file merged with its impact row and precursor entities.

    The threat file is the published denormalisation; the model's impact row is
    authoritative for the assessment context and supplies `precursor_refs`,
    which the threat file does not carry (S2 section 7). The overlay carries
    BOTH generations: a v4 row's `damage`, and a v5 row's two prose blocks, its
    factors, its score, and its vector, so a raw v4 model and a v5 model are
    queryable through one catalog. The v5 fields are ALSO flattened onto the
    view itself, because the threat catalog names `risk_vector`, `factors.*`,
    and the two prose blocks at this level (schema-5 spec 10).
    """
    threat_value = record.get("threat")
    threat = dict(threat_value) if isinstance(threat_value, Mapping) else {}
    impact_value = record.get("impact")
    impact = dict(impact_value) if isinstance(impact_value, Mapping) else {}
    impact_ref = str(impact.get("impact_ref") or threat.get("impact_ref") or "")
    row = rows.get(impact_ref, {})
    if row:
        # The model row is authoritative for the assessment context; the threat
        # file is the published denormalisation. Key presence (not truthiness)
        # is the overlay rule, so an explicit empty value survives.
        for key in (
            "damage",
            "impact_description",
            "exploitability_description",
            "factors",
            "risk",
            "risk_vector",
            "disposition",
            "capability_path",
            "precursor_refs",
            "evidence_refs",
        ):
            if key not in row:
                continue
            value = row[key]
            impact[key] = list(value) if isinstance(value, list) else value
    if not impact.get("precursors"):
        impact["precursors"] = [
            dict(precursors[ref])
            for ref in impact.get("capability_path") or []
            if ref in precursors
        ]
    return {
        "threat_id": str(record.get("threat_id") or threat.get("id") or ""),
        "dispatch_id": str(record.get("dispatch_id") or ""),
        "unit_id": str(document.get("unit_id") or record.get("unit_id") or ""),
        "run_id": str(record.get("run_id") or document.get("run_id") or ""),
        "risk": record.get("risk", threat.get("risk")),
        # The v5 assessment paths, flattened beside the threat file's own keys:
        # `PRIOR_ART_PATHS[THREAT]` names `risk_vector`, `factors.*`, and the
        # two prose blocks at this level, so a v5 threat is queryable through
        # one catalog; a raw v4 row still fills the prose from `damage`.
        "risk_vector": row.get("risk_vector", ""),
        "impact_description": (
            row.get("impact_description") or row.get("damage") or ""),
        "exploitability_description": row.get("exploitability_description", ""),
        "factors": dict(row.get("factors") or {}),
        "threat": threat,
        "impact": impact,
    }


def _section_query_views(
    kind: PriorArtKind, document: Mapping[str, Any],
) -> Iterator[tuple[str, dict]]:
    """The model's records of one non-threat kind, each with the owner identity."""
    for item in document.get(_QUERY_SECTION_BY_KIND[kind]) or []:
        if not isinstance(item, Mapping):
            continue
        if kind is PriorArtKind.PRECURSOR and item.get("disposition") != "precursor":
            continue
        view = dict(item)
        view["unit_id"] = str(document.get("unit_id") or "")
        if kind is PriorArtKind.ASSUMPTION and "description" not in view:
            # The spec's catalog names the assumption prose `description`; the
            # schema field is `statement`, so both paths resolve one value.
            view["description"] = view.get("statement", "")
        yield str(item.get("id") or ""), view


def _query_match(
    kind: PriorArtKind,
    record_id: str,
    unit_id: str,
    view: Mapping[str, Any],
    state: str,
    matched: list[dict],
) -> ThreatQueryMatch:
    """The summary one query result carries, per kind, never the full model."""
    threat: Mapping[str, Any] = {}
    impact: Mapping[str, Any] = {}
    if kind is PriorArtKind.THREAT:
        threat = view.get("threat") or {}
        impact = view.get("impact") or {}
        label = str(threat.get("canonical_class") or "")
        web_vulnerability_class = str(threat.get("web_vulnerability_class") or "")
        disposition = _optional_text(impact.get("disposition"))
        summary = str(
            impact.get("impact_description") or impact.get("damage") or "")
        evidence_refs = _evidence_refs(impact.get("evidence_refs"))
        for ref in _evidence_refs(threat.get("evidences")):
            if ref not in evidence_refs:
                evidence_refs.append(ref)
    elif kind is PriorArtKind.VULNERABILITY:
        label = str(view.get("canonical_class") or "")
        web_vulnerability_class = str(view.get("web_vulnerability_class") or "")
        disposition = None
        summary = str(view.get("characterisation") or "")
        evidence_refs = _evidence_refs(view.get("evidences"))
    elif kind is PriorArtKind.PRECURSOR:
        label = str(view.get("capability") or "")
        web_vulnerability_class = ""
        disposition = _optional_text(view.get("disposition"))
        summary = str(view.get("impact_description") or view.get("damage") or "")
        evidence_refs = _evidence_refs(view.get("evidence_refs"))
    elif kind is PriorArtKind.ASSUMPTION:
        fault = view.get("fault")
        fault = fault if isinstance(fault, Mapping) else {}
        label = str(fault.get("label") or "")
        web_vulnerability_class = ""
        disposition = None
        summary = str(view.get("statement") or view.get("description") or "")
        evidence_refs = _evidence_refs(view.get("evidences"))
    else:  # impact
        disposition = _optional_text(view.get("disposition"))
        label = disposition or ""
        web_vulnerability_class = ""
        summary = str(view.get("impact_description") or view.get("damage") or "")
        evidence_refs = _evidence_refs(view.get("evidence_refs"))
    return ThreatQueryMatch(
        unit_id=unit_id,
        record_id=record_id,
        kind=kind.value,
        label=label,
        web_vulnerability_class=web_vulnerability_class,
        disposition=disposition,
        summary=summary,
        state=state,
        evidence_refs=evidence_refs,
        matched=matched,
    )


class ThreatModelStore(BoundedRecordStore):
    """The per-project unit threat model store (S2 10.1)."""

    def __init__(
        self,
        root_dir: str | Path | None = None,
        *,
        class_names: AbstractSet[str] | None = None,
    ):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`); the
        per-project bucket is `<root>/<project_id>/hunting/threat_modeller/`,
        resolved through the ONE `data_root.project_dir` layout owner. The
        explicit-root constructor is kept for the tests' temp stores (the
        retired bounded-store precedent).

        `class_names` is the optional web-vulnerability suite index used by the
        class-binding completion findings. Its findings never reject a write."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT
        self._class_names = frozenset(class_names) if class_names is not None else None

    def set_class_names(self, class_names: AbstractSet[str] | None) -> None:
        """Bind the suite class index after construction.

        The runtime builds the store before the per-unit suite seam exists, so
        the tool surface calls this once the suite classes are known. The
        findings stay non-blocking."""
        self._class_names = frozenset(class_names) if class_names else None

    # --- path helpers ----------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/threat_modeller", root=self._root)

    def _family_dir(self, project_id: str, family: str) -> Path:
        return self._project_dir(project_id) / family

    def _unit_dir(self, project_id: str, unit_name: str, family: str) -> Path:
        return self._family_dir(project_id, family) / unit_name

    def _model_path(self, project_id: str, unit_name: str, family: str) -> Path:
        return self._unit_dir(project_id, unit_name, family) / f"{unit_name}.yaml"

    def _notes_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "notes.yaml"

    # --- document reads ---------------------------------------------------------

    def _load_raw(self, path: Path) -> dict | None:
        """One YAML mapping, fail-open: a missing file, an unreadable YAML, or
        a non-mapping body warns and degrades to None (O4)."""
        if not path.exists():
            return None
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("threat model store: unreadable document %s (%s)", path, exc)
            return None
        return loaded if isinstance(loaded, dict) else None

    def _load_document(
        self, path: Path, *, allow_legacy: bool = False,
    ) -> LoadedDocument | None:
        """A document under the reader's schema version, typed.

        The current version parses as the persisted `PartialThreatModel`. A v4
        document is read RAW as `RawThreatModel` for the prior art and the
        measurement: it is never normalised and never re-scored (schema-5 spec
        11). A v2/v3 document is read raw only when the caller asks
        (`allow_legacy`): the intake and the measurement need it, the mover and
        the query do not. Any other version is refused and logged, never
        migrated (S2 5.8). A v5 document that does not parse is refused the same
        way: an unreadable body is not merged and not queried.
        """
        raw = self._load_raw(path)
        if raw is None:
            return None
        version = raw.get("schema_version")
        if version == SCHEMA_VERSION:
            try:
                return PartialThreatModel.model_validate(raw)
            except ValueError as exc:
                logger.error(
                    "threat model store: refusing %s - schema_version %s does "
                    "not parse as the v5 model (%s)", path, version, exc,
                )
                return None
        if version == PREVIOUS_SCHEMA_VERSION:
            return RawThreatModel.from_document(raw)
        if allow_legacy and version in LEGACY_SCHEMA_VERSIONS:
            return RawThreatModel.from_document(raw)
        logger.error(
            "threat model store: refusing %s - unsupported schema_version %r "
            "(this reader knows %s, reads %s raw, and the legacy read accepts %s)",
            path, version, SCHEMA_VERSION, PREVIOUS_SCHEMA_VERSION,
            LEGACY_SCHEMA_VERSION,
        )
        return None

    def _load_mapping(self, path: Path, *, allow_legacy: bool = False) -> dict | None:
        """One document as a mapping, through the ONE typed load.

        The store's mechanics (identity, merge, consumability, queries) read and
        write mappings; a raw legacy record round-trips verbatim, a v5 record
        renders through the schema's field set (`document_of`)."""
        loaded = self._load_document(path, allow_legacy=allow_legacy)
        return document_of(loaded) if loaded is not None else None

    # --- derived unit names (S2 4.2) -------------------------------------------

    def _family_holder(self, project_id: str, name: str, family: str) -> _FamilyState:
        """The ONE family-level read of a derived unit name (S2 4.2): whether
        the directory exists, whether its model document exists, and the unit
        id the document carries (`None` when unreadable or absent). Every name
        scan and the archive both build on this primitive."""
        directory = self._unit_dir(project_id, name, family)
        if not directory.exists():
            return _FamilyState(directory=False, model=False, unit_id=None)
        path = directory / f"{name}.yaml"
        if not path.exists():
            return _FamilyState(directory=True, model=False, unit_id=None)
        raw = self._load_raw(path)
        unit_id = raw.get("unit_id") if raw is not None else None
        if not isinstance(unit_id, str) or not unit_id:
            return _FamilyState(directory=True, model=True, unit_id=None)
        return _FamilyState(directory=True, model=True, unit_id=unit_id)

    def _classify_name(self, project_id: str, name: str) -> tuple[str, str | None]:
        """Classify one candidate name across all three families.

        - `("free", None)`: no directory anywhere.
        - `("empty", None)`: a directory exists but NO model document does (the
          crash window between the atomic write's parent mkdir and its
          `os.replace`): the name is reusable.
        - `("held", unit_id)`: every existing model document carries the SAME
          unit id - that unit owns the name.
        - `("unreadable", None)`: a model document exists but is unreadable, or
          the families disagree on the unit id: the identity is unknown, and
          the caller must refuse rather than guess.
        """
        present = False
        model_present = False
        found: set[str] = set()
        for family in _FAMILIES:
            state = self._family_holder(project_id, name, family)
            present = present or state.directory
            model_present = model_present or state.model
            if state.unit_id is not None:
                found.add(state.unit_id)
        if not present:
            return "free", None
        if not model_present:
            return "empty", None
        if len(found) != 1:
            return "unreadable", None
        return "held", next(iter(found))

    def _candidate_names(self, unit_id: str) -> tuple[str, str]:
        base = sanitise_unit_name(unit_id)
        return base, f"{base}-{collision_suffix(unit_id)}"

    def _unit_name_for_write(self, project_id: str, unit_id: str) -> str:
        """The unit directory name for a write.

        A name already held by THIS unit is reused (a retried write, a unit
        whose earlier copy lives in abandoned/ or consumed/); otherwise the
        first free or empty candidate is taken; a name held by another unit
        triggers the hash suffix. An unreadable holder refuses with a coded
        error - never a suffix (that would fork the unit's directory) and never
        a clobber (the identity is unknown).
        """
        plain, suffixed = self._candidate_names(unit_id)
        classified = {
            name: self._classify_name(project_id, name) for name in (plain, suffixed)
        }
        for name, (kind, _) in classified.items():
            if kind == "unreadable":
                raise ThreatModelDirectoryError(name)
        for name, (kind, holder) in classified.items():
            if kind == "held" and holder == unit_id:
                return name
        for name, (kind, _) in classified.items():
            if kind in ("free", "empty"):
                return name
        raise UnitDirectoryCollisionError(
            f"threat model store: both candidate directories {plain!r} and "
            f"{suffixed!r} are held by another unit; refusing to clobber"
        )

    def _find_model_path(
        self, project_id: str, unit_id: str, family: str,
        *, allow_legacy: bool = False,
    ) -> Path | None:
        """The model path for `unit_id` in one family, name- and identity-checked.

        Both the plain and the collision-suffixed candidate are tried; the
        identity check on the model's `unit_id` keeps a colliding sibling's
        document from being returned.
        """
        for name in self._candidate_names(unit_id):
            path = self._model_path(project_id, name, family)
            loaded = self._load_document(path, allow_legacy=allow_legacy)
            if loaded is None:
                continue
            if document_of(loaded).get("unit_id") == unit_id:
                return path
        return None

    def read_model(self, project_id: str, unit_id: str) -> dict | None:
        """The unit's model document as a mapping (produced/ first, then
        consumed/), or None. A v5 document renders through the schema's field
        set; a v4 (and every allowed legacy) document renders raw, exactly as
        it was persisted. An unknown `schema_version` refuses to load (a version
        error is logged). A read failure degrades to None, never a raise (O4)."""
        with self._lock_for(project_id):
            for family in _READ_FAMILIES:
                path = self._find_model_path(
                    project_id, unit_id, family, allow_legacy=True)
                if path is not None:
                    loaded = self._load_document(path, allow_legacy=True)
                    return document_of(loaded) if loaded is not None else None
            return None

    def read_section(self, project_id: str, unit_id: str, section: str) -> Any:
        """One section of the unit's model, or None when the model or the
        section is absent. Read-only."""
        model = self.read_model(project_id, unit_id)
        return model.get(section) if model is not None else None

    # --- the prior-art query (S2 section 7) ------------------------------------

    def _query_documents(
        self, project_id: str, family: str, *, produced_fallback: bool,
    ) -> Iterator[tuple[Path, dict]]:
        """One family's readable unit documents, by directory name.

        A consumed threat can outlive its model document (the model moves with
        the unit's LAST threat file), so the threat scan falls back to the
        produced document. An unreadable or unknown-version document is skipped
        fail-open (O4).
        """
        root = self._family_dir(project_id, family)
        if not root.exists():
            return
        for directory in sorted(root.iterdir()):
            if not directory.is_dir():
                continue
            loaded = self._load_document(directory / f"{directory.name}.yaml")
            if loaded is None and produced_fallback and family == "consumed":
                loaded = self._load_document(
                    self._model_path(project_id, directory.name, "produced"))
            if loaded is None:
                continue
            yield directory, document_of(loaded)

    def _threat_query_views(
        self, directory: Path, document: dict,
    ) -> Iterator[tuple[str, dict]]:
        """The directory's threat files merged with the model's impact rows and
        precursor entities. A malformed threat file is skipped (a read failure
        degrades, never raises)."""
        rows = _records_by_id(document.get("impact_assessment"))
        precursors = _records_by_id(document.get("precursors"))
        for path in sorted(
            directory.glob("threat-*.yaml"),
            key=lambda item: _threat_rank(item.stem),
        ):
            state, record = self._read_threat_file(path)
            if state != "record" or record is None:
                continue
            view = _threat_view(record, rows, precursors, document)
            yield str(record.get("threat_id") or view["threat_id"] or path.stem), view

    def query_prior_art(
        self,
        project_id: str,
        *,
        kind: PriorArtKind | str,
        filters: Sequence[FieldFilter | Mapping[str, Any]],
        limit: int = QUERY_DEFAULT_LIMIT,
        bound_unit_id: str = "",
    ) -> dict:
        """The project-scoped prior-art query over the produced and consumed
        models (S2 section 7).

        `kind` selects one record view; `filters` is a non-empty AND list, each
        a case-(in)sensitive `re.search` over the values at a dotted path. The
        query EXCLUDES the bound unit unless a filter path is `unit_id`. Each
        match carries its model's `state`, a summary, the evidence refs, and the
        `matched` path/value pairs; a full model is never returned.

        The empty filter list, an invalid regex, an unknown path, and an
        out-of-range limit are `ThreatQueryError`s (the tool's coded teaching
        rejection). A single unreadable document or threat file is skipped
        fail-open (O4).
        """
        try:
            query_kind = (
                kind if isinstance(kind, PriorArtKind) else PriorArtKind(str(kind))
            )
        except ValueError as exc:
            raise ThreatQueryError(
                ["kind"],
                f"unknown kind {kind!r}; known: "
                f"{', '.join(member.value for member in PriorArtKind)}",
            ) from exc
        parsed = _parse_query_filters(query_kind, filters)
        if isinstance(limit, bool) or not isinstance(limit, int) or not (
            1 <= limit <= QUERY_MAX_LIMIT
        ):
            raise ThreatQueryError(
                ["limit"],
                f"`limit` is an integer 1..{QUERY_MAX_LIMIT}",
            )
        exclude_bound = bool(bound_unit_id) and not any(
            path == "unit_id" for path, _ in parsed)
        matches: list[ThreatQueryMatch] = []
        seen: set[tuple[str, str]] = set()
        with self._lock_for(project_id):
            for family in _READ_FAMILIES:
                for directory, document in self._query_documents(
                    project_id, family,
                    produced_fallback=query_kind is PriorArtKind.THREAT,
                ):
                    unit_id = str(document.get("unit_id") or "")
                    if not unit_id or (exclude_bound and unit_id == bound_unit_id):
                        continue
                    state = str(document.get("state") or "")
                    views = (
                        self._threat_query_views(directory, document)
                        if query_kind is PriorArtKind.THREAT
                        else _section_query_views(query_kind, document)
                    )
                    for record_id, view in views:
                        dedupe = (unit_id, record_id)
                        if record_id and dedupe in seen:
                            continue
                        matched = _match_query_filters(view, parsed)
                        if matched is None:
                            continue
                        if record_id:
                            seen.add(dedupe)
                        matches.append(_query_match(
                            query_kind, record_id, unit_id, view, state, matched))
            result = ThreatQueryResult(
                matches=matches[:limit],
                count=min(len(matches), limit),
                truncated=len(matches) > limit,
            )
        return result.model_dump(mode="json")

    def read_threat_files(self, project_id: str, unit_id: str) -> list[dict]:
        """The unit's threat files in rank order: produced/ first, then
        consumed/. Returns [] unless the model is `COMPLETED` AND
        `validation.valid` - S2 4.3: a threat file is never read for a model
        whose state is not COMPLETED, so the crash window (threat files written,
        the model document not yet committed) never surfaces as work. The
        invalidity gate repeats the one consumability predicate (S2 10.5), so
        an invalid COMPLETED model's files are never dispatched. A missing unit
        or a zero-threat model yields [] - a valid empty result, never a failure.
        A malformed threat record is skipped fail-open (T4 owns the dispatch
        refuse-and-log rule)."""
        with self._lock_for(project_id):
            for family in _READ_FAMILIES:
                path = self._find_model_path(project_id, unit_id, family)
                if path is None:
                    continue
                raw = self._load_mapping(path)
                if raw is None or not self._consumable(raw):
                    return []
                directory = path.parent
                records: list[dict] = []
                for threat_path in sorted(
                    directory.glob("threat-*.yaml"), key=lambda item: _threat_rank(item.stem)
                ):
                    record = self._load_raw(threat_path)
                    if record is not None:
                        records.append(record)
                return records
            return []

    # --- consumption (the mover primitives, S2 8.4) -----------------------------

    @staticmethod
    def _consumable(raw: dict) -> bool:
        """The ONE consumability predicate (S2 5.7, 10.5): the model is
        COMPLETED and its completion validation is valid."""
        validation = raw.get("validation")
        return (
            raw.get("state") == ModelState.COMPLETED.value
            and isinstance(validation, dict)
            and validation.get("valid") is True
        )

    def consume_threat(self, project_id: str, unit_id: str, threat_id: str) -> bool:
        """Move one produced threat file to consumed/ - the single-owner
        produced-to-consumed transition of the mover (S2 8.4). True when the
        threat file now lives in consumed/ (moved now, or already moved by an
        earlier tick - at-least-once). False when no such threat file exists in
        either side. The model document moves with its LAST threat file: when no
        produced threat file remains, a consumable model document is moved too.
        The move refuses to clobber an existing consumed file (fail-open)."""
        if not is_threat_id(threat_id):
            raise ThreatModelIdentityError(
                ["threat_id"],
                f"threat model store: {threat_id!r} is not a threat id of the "
                f"`threat-<rank>` form",
            )
        with self._lock_for(project_id):
            model_path = self._find_model_path(project_id, unit_id, "produced")
            if model_path is None:
                consumed = self._find_model_path(project_id, unit_id, "consumed")
                if consumed is None:
                    return False
                return (consumed.parent / threat_file_name(threat_id)).exists()
            name = model_path.parent.name
            produced_threat = model_path.parent / threat_file_name(threat_id)
            consumed_threat = (
                self._unit_dir(project_id, name, "consumed")
                / threat_file_name(threat_id)
            )
            if not produced_threat.exists():
                return consumed_threat.exists()
            if consumed_threat.exists():
                logger.warning(
                    "threat model store: both produced/ and consumed/ hold %s "
                    "for %s; refusing to clobber the consumed record (fail-open)",
                    produced_threat.name, name,
                )
                return False
            consumed_threat.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced_threat, consumed_threat)
            if not any(model_path.parent.glob("threat-*.yaml")):
                self._move_model_if_ready(project_id, name)
            return True

    def consume_model_if_done(
        self,
        project_id: str,
        unit_id: str,
        *,
        refused_threats: Sequence[str] = (),
        non_pending_threats: Sequence[str] = (),
    ) -> bool:
        """Move the unit's model document to consumed/ when it is complete,
        valid, and has no PENDING threat file left (S2 8.4). A zero-threat model is
        consumed here without a dispatch; a model with produced threats stays until
        its last threat file is consumed (by `consume_threat`). True when the model
        now lives in consumed/ (moved now, or already moved).

        `refused_threats` names the produced threat files the mover REFUSED (a
        malformed body it can neither dispatch nor consume as a threat record,
        S2 10.5). `non_pending_threats` names the produced threat files the
        frozen promotion floor DEMOTED: evidence that stays in produced/ and is
        never work. Both sets are non-pending: counting them would leave the
        model in produced/ forever, so the run could never quiesce (T4a review
        F1). The files are left in place - they are debugging evidence, never
        silently deleted - and the model document moves as the ONE consumption
        marker."""
        non_pending = frozenset(str(threat_id) for threat_id in refused_threats) \
            | frozenset(str(threat_id) for threat_id in non_pending_threats)
        with self._lock_for(project_id):
            model_path = self._find_model_path(project_id, unit_id, "produced")
            if model_path is None:
                consumed = self._find_model_path(project_id, unit_id, "consumed")
                if consumed is None:
                    return False
                raw = self._load_mapping(consumed)
                return bool(raw is not None and self._consumable(raw))
            raw = self._load_mapping(model_path)
            if raw is None or not self._consumable(raw):
                return False
            if self._pending_threat_files(model_path.parent, non_pending):
                return False
            return self._move_model_if_ready(project_id, model_path.parent.name)

    @staticmethod
    def _pending_threat_files(
        directory: Path, non_pending: frozenset[str],
    ) -> list[Path]:
        """The produced `threat-*.yaml` files that are still PENDING work: every
        one except the mover-refused and promotion-demoted stems (S2 8.4/10.5)."""
        return [
            path for path in directory.glob("threat-*.yaml")
            if path.stem not in non_pending
        ]

    def _move_model_if_ready(self, project_id: str, unit_name: str) -> bool:
        """Move one produced model document to consumed/ when it is consumable;
        the now-empty produced unit directory is removed best-effort. The
        caller has already established that no produced threat file remains."""
        model_path = self._model_path(project_id, unit_name, "produced")
        raw = self._load_mapping(model_path)
        if raw is None or not self._consumable(raw):
            return False
        consumed_model = self._model_path(project_id, unit_name, "consumed")
        if consumed_model.exists():
            logger.warning(
                "threat model store: both produced/ and consumed/ hold the "
                "model document for %s; refusing to clobber (fail-open)", unit_name,
            )
            return False
        consumed_model.parent.mkdir(parents=True, exist_ok=True)
        os.replace(model_path, consumed_model)
        try:
            model_path.parent.rmdir()
        except OSError:
            pass
        return True

    def read_completed_units(self, project_id: str) -> list[str]:
        """The unit ids whose COMPLETED, valid model lives in consumed/ - the
        intake exclusion surface (S2 9.3). Sorted and deduplicated; an
        unreadable, unknown-version, or invalid document contributes nothing."""
        with self._lock_for(project_id):
            consumed = self._family_dir(project_id, "consumed")
            if not consumed.exists():
                return []
            found: set[str] = set()
            for directory in sorted(consumed.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_mapping(
                    directory / f"{directory.name}.yaml", allow_legacy=True)
                if raw is None or not self._consumable(raw):
                    continue
                unit_id = raw.get("unit_id")
                if isinstance(unit_id, str) and unit_id:
                    found.add(unit_id)
            return sorted(found)

    def _read_threat_file(self, path: Path) -> tuple[str, dict | None]:
        """One threat file's state (T4a review F1): `("record", body)` when the
        file parses to a mapping, else `("unreadable" | "not-a-mapping", None)`.

        The read is QUIET (unlike `_load_raw`): the produced read reports the
        malformed file to its caller, which refuses it once - a per-read warning
        here would re-log one line per tick for as long as the file lives
        (S2 10.5's log-once discipline)."""
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return "unreadable", None
        if not isinstance(loaded, dict):
            return "not-a-mapping", None
        return "record", loaded

    def _read_family_threats(self, project_id: str, family: str) -> list[dict]:
        """One family's consumable units and their threat files.

        The mover reads BOTH families (F-022): produced/ is the dispatch
        inbox, and consumed/ is the recovery inbox. A consumed threat whose
        hunter wrote no terminal spec set is work again after a provider pause
        - the produced->consumed move is the admission marker, never the
        completion marker. The model document rides the entry so the recovery
        dispatch needs no second read and never re-models the unit.

        A malformed file is REPORTED, never dropped (T4a review F1): dropping
        it would read as "the unit holds no threat file", the mover would consume
        the model, and the store would refuse while the `threat-*.yaml` remains -
        the run would never quiesce (S2 10.5). The mover refuses it once and
        never counts it as a pending threat.
        """
        with self._lock_for(project_id):
            root = self._family_dir(project_id, family)
            if not root.exists():
                return []
            entries: list[dict] = []
            for directory in sorted(root.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_mapping(directory / f"{directory.name}.yaml")
                if raw is None and family == "consumed":
                    # The model moves with its LAST threat file (S2 8.4), so a
                    # consumed threat from a multi-threat unit still has its model
                    # in produced/. Read that same original document: the
                    # recovery never re-models the unit.
                    raw = self._load_mapping(
                        self._model_path(project_id, directory.name, "produced"))
                if raw is None or not self._consumable(raw):
                    continue
                unit_id = raw.get("unit_id")
                if not isinstance(unit_id, str) or not unit_id:
                    continue
                threats: list[dict] = []
                malformed: list[dict] = []
                for threat_path in sorted(
                    directory.glob("threat-*.yaml"),
                    key=lambda item: _threat_rank(item.stem),
                ):
                    state, record = self._read_threat_file(threat_path)
                    if state != "record":
                        malformed.append({
                            "threat_id": threat_path.stem,
                            "reason": state,
                        })
                        continue
                    threats.append({"threat_id": threat_path.stem, "record": record})
                entries.append({
                    "unit_id": unit_id,
                    "unit_name": directory.name,
                    "run_id": raw.get("run_id") if isinstance(raw.get("run_id"), str) else "",
                    "threats": threats,
                    "malformed_threats": malformed,
                    # the document this read already parsed: the mover's payload
                    # materialisation reads it (S2 8.2) without a second read
                    "model": raw,
                })
            return entries

    def read_produced_threats(self, project_id: str) -> list[dict]:
        """The mover's dispatch inbox read (S2 8.1/8.4, T4 #377): one entry per
        PRODUCED, consumable unit - `{unit_id, unit_name, run_id, threats,
        malformed_threats, model}` - with `threats` the unit's produced threat file
        records in rank order, each as `{threat_id, record}` (the file stem plus the
        record verbatim, so the mover's validity predicate can check the two
        agree), `malformed_threats` the file stems whose body is unreadable or not a
        mapping, each as `{threat_id, reason}`, and `model` the document this read
        already parsed (the mover's payload context, S2 8.2: the threat file does
        not duplicate the model).

        A zero-threat consumable model IS an entry with no threats and no malformed
        files - the mover consumes it without a dispatch. A model below
        COMPLETED or invalid is never dispatch input (S2 4.3, 5.7)."""
        return self._read_family_threats(project_id, "produced")

    def read_consumed_threats(self, project_id: str) -> list[dict]:
        """The mover's recovery inbox read (F-022): one entry per CONSUMED,
        consumable unit, in the same shape as `read_produced_threats`.

        The consumed family is not "decided and never re-dispatched": the
        produced->consumed move is admission, and the hunter's terminal spec
        set is completion. After a provider pause a consumed threat can have no
        terminal set, so the mover recovers it from here.

        The model dependency is the ORIGINAL model document, never a re-model.
        The model moves to consumed/ with the unit's LAST threat file, so for a
        multi-threat unit the consumed threat still finds its model in produced/;
        the read falls back to it. A zero-threat consumed unit is not work and
        carries no recovery entry (its threats list is empty)."""
        return self._read_family_threats(project_id, "consumed")

    def read_produced_units(self, project_id: str) -> list[dict]:
        """Every produced model's `{unit_id, run_id, state}` (S2 9.3).

        The intake freeze reads the produced family to tell an in-flight model
        (its producing run is live or resumable) from a stale one. Ordered by
        unit directory name; a document without a readable unit id or run id
        contributes nothing (the freeze never guesses an identity it cannot
        attribute).
        """
        with self._lock_for(project_id):
            produced = self._family_dir(project_id, "produced")
            if not produced.exists():
                return []
            found: list[dict] = []
            for directory in sorted(produced.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_mapping(directory / f"{directory.name}.yaml")
                if raw is None:
                    continue
                unit_id = raw.get("unit_id")
                run_id = raw.get("run_id")
                if not isinstance(unit_id, str) or not unit_id:
                    continue
                found.append({
                    "unit_id": unit_id,
                    "run_id": run_id if isinstance(run_id, str) else "",
                    "state": raw.get("state"),
                })
            return found

    def archive_unit(self, project_id: str, unit_id: str, reason: str) -> Path | None:
        """Move the unit's produced directory to abandoned/ (S2 7.7).

        The harness calls this for a degraded unit or a COMPLETED model whose
        validation failed; the intake and the mover ignore abandoned/. A unit
        whose earlier attempt is already abandoned is REPLACED by the newest
        degraded copy - abandoned/ is a graveyard for debugging, not a history
        log, and it never carries two models for one unit. A consumed model is
        never touched (it is decided).

        Returns the abandoned unit directory when one exists after the call
        (moved now, or already archived); None when there is nothing to archive
        or the unit's model is already decided in consumed/.

        `reason` is the harness-recorded degradation reason; it is logged here
        (the run record is the durable home of the degraded-unit findings).
        """
        with self._lock_for(project_id):
            produced_path = self._find_model_path(project_id, unit_id, "produced")
            if produced_path is None:
                for name in self._candidate_names(unit_id):
                    state = self._family_holder(project_id, name, "abandoned")
                    if state.directory and state.unit_id == unit_id:
                        return self._unit_dir(project_id, name, "abandoned")
                if self._find_model_path(project_id, unit_id, "consumed") is not None:
                    logger.warning(
                        "threat model store: archive of %s skipped - its model "
                        "already lives in consumed/ (decided)", unit_id,
                    )
                    return None
                logger.warning(
                    "threat model store: archive of %s skipped - no produced "
                    "model to archive (%s)", unit_id, reason,
                )
                return None
            produced_name = produced_path.parent.name
            destination_name = None
            for name in (produced_name, *self._candidate_names(unit_id)):
                state = self._family_holder(project_id, name, "abandoned")
                if not state.directory or state.unit_id == unit_id:
                    destination_name = name
                    break
            if destination_name is None:
                raise UnitDirectoryCollisionError(
                    f"threat model store: no abandoned name is free for "
                    f"{unit_id!r}; refusing to clobber another unit's archive"
                )
            destination = self._unit_dir(project_id, destination_name, "abandoned")
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(produced_path.parent, destination)
            logger.warning(
                "threat model store: archived %s to abandoned/ (%s)",
                produced_name, reason,
            )
            return destination

    def read_abandoned_units(self, project_id: str) -> list[str]:
        """The unit ids with an abandoned model - the retry surface (S2 9.3:
        abandoned units are ignored and retried, never excluded). Sorted and
        deduplicated; an unreadable or unknown-version document contributes
        nothing."""
        with self._lock_for(project_id):
            abandoned = self._family_dir(project_id, "abandoned")
            if not abandoned.exists():
                return []
            found: set[str] = set()
            for directory in sorted(abandoned.iterdir()):
                if not directory.is_dir():
                    continue
                raw = self._load_mapping(directory / f"{directory.name}.yaml")
                if raw is None:
                    continue
                unit_id = raw.get("unit_id")
                if isinstance(unit_id, str) and unit_id:
                    found.add(unit_id)
            return sorted(found)

    # --- the gate write (S2 5.4) -----------------------------------------------

    @staticmethod
    def _section_value(value: Any) -> Any:
        """The JSON-safe section content.

        A typed section object (or a list of them) renders through
        `model_dump(mode="json")`; a plain mapping or list payload passes
        through for pydantic to validate, so T2 may send either form.
        """
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, (list, tuple)):
            return [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in value
            ]
        return value

    def write_sections(
        self,
        project_id: str,
        unit_id: str,
        state: str | ModelState,
        sections: Mapping[str, Any],
        *,
        run_id: str,
    ) -> Path:
        """Merge one gate write into the unit's model and persist it.

        `state` selects the allowed `sections` keys (S2 5.4); a key outside the
        gate's set is a coded rejection. The state is monotonic: a lower-gate
        write updates content but leaves the persisted state unchanged. The
        COMPLETED write normalises the threats, computes the risk profile, runs
        the checker, emits the threat files, and commits the document last
        (S2 4.3). A gate write below COMPLETED deletes stale produced threat
        files. A write whose identity already lives in consumed/ is a no-op
        success returning the consumed path (S2 4.5).

        `run_id` is the harness-held run identity, bound on the first write;
        a later write preserves the document's recorded run id.
        """
        try:
            gate = ModelState(state)
        except ValueError as exc:
            raise ThreatModelIdentityError(
                ["state"],
                f"threat model store: unknown state {state!r}; known: "
                f"{tuple(gate.value for gate in ModelState)}",
            ) from exc
        allowed = GATE_SECTIONS[gate]
        unexpected = [key for key in sections if key not in allowed]
        if unexpected:
            raise ThreatModelIdentityError(
                unexpected,
                f"threat model store: state {gate.value} accepts only "
                f"{allowed}; got {tuple(unexpected)}",
            )
        unit_id = unit_id if isinstance(unit_id, str) else str(unit_id or "")
        if not unit_id:
            raise ThreatModelIdentityError(
                ["unit_id"],
                "threat model store: write needs a non-empty harness-bound unit id",
            )
        if not run_id:
            raise ThreatModelIdentityError(
                ["run_id"],
                "threat model store: write needs a non-empty harness-bound run id",
            )
        with self._lock_for(project_id):
            unit_name = self._unit_name_for_write(project_id, unit_id)
            consumed_path = self._model_path(project_id, unit_name, "consumed")
            if consumed_path.exists():
                logger.warning(
                    "threat model store: write for %s skipped - the identity "
                    "already lives in consumed/ (post-move write); no produced/ "
                    "copy re-created", unit_name,
                )
                return consumed_path
            model_path = self._model_path(project_id, unit_name, "produced")
            existing = self._load_document(model_path)
            if existing is not None and not isinstance(existing, PartialThreatModel):
                # A legacy (v4 and older) document reads raw but is never
                # written: a stale model would otherwise be mixed into a v5 run
                # (schema-5 spec 11). No silent migration.
                raise ThreatModelSchemaVersionError(
                    model_path, existing.schema_version)
            if existing is None and model_path.exists():
                # Present but refused (an unknown schema_version or an
                # unreadable body): never merge into a document we cannot read.
                raise ThreatModelSchemaVersionError(model_path, self._raw_version(model_path))
            now = datetime.now(timezone.utc)
            doc = self._merged_document(
                document_of(existing) if existing is not None else None,
                unit_id, run_id, gate, sections, now, model_path,
                project_id=project_id,
            )
            self._commit(project_id, unit_name, doc, gate, now)
            return model_path

    @staticmethod
    def _raw_version(path: Path) -> Any:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return None
        return loaded.get("schema_version") if isinstance(loaded, dict) else None

    def _merged_document(
        self,
        existing: dict | None,
        unit_id: str,
        run_id: str,
        gate: ModelState,
        sections: Mapping[str, Any],
        now: datetime,
        path: Path,
        *,
        project_id: str,
    ) -> PartialThreatModel:
        """The merged, parsed document: identity bound, sections applied, the
        state kept monotonic, and - at COMPLETED - the threats normalised and
        the risk profile computed."""
        if existing is None:
            doc: dict = {
                "schema_version": SCHEMA_VERSION,
                "unit_id": unit_id,
                "unit_kind": unit_kind_from_unit_id(unit_id).value,
                "run_id": run_id,
                "created_at": now,
                "updated_at": now,
                "state": gate.value,
            }
        else:
            doc = {key: value for key, value in existing.items()}
            doc["updated_at"] = now
            try:
                persisted = ModelState(doc["state"])
            except (KeyError, ValueError) as exc:
                raise ThreatModelDocumentError(path, doc.get("state")) from exc
            doc["state"] = max(persisted, gate, key=STATE_ORDER.__getitem__).value
        for key, value in sections.items():
            doc[key] = self._section_value(value)
        model = PartialThreatModel.model_validate(doc)
        if gate is ModelState.COMPLETED:
            # The assessment row is the scored claim: the store fills the
            # threat's risk mirror from it, then ranks and profiles from the
            # mirror. The model never authored either value.
            model.threats = normalise_threats(
                model.threats, model.impact_assessment)
            model.risk_profile = compute_risk_profile(model.threats)
            model.validation = check_completion(
                UnitThreatModel.model_validate(model.model_dump()),
                class_names=self._class_names,
                capability_index=self._capability_index(project_id),
            )
        return model

    def _commit(
        self,
        project_id: str,
        unit_name: str,
        model: PartialThreatModel,
        gate: ModelState,
        now: datetime,
    ) -> None:
        """Persist the document under the commit protocol (S2 4.3).

        A COMPLETED gate write lands the threat files first (atomically,
        replacing the whole set), then the model document as the commit
        marker. A gate write below COMPLETED whose EFFECTIVE state is also
        below COMPLETED deletes the stale produced threat files (crash repair).
        A late lower-gate write on an already COMPLETED model leaves the
        committed threat set untouched: the state never regresses, so deleting
        its dispatch files would corrupt a published model.
        """
        produced_dir = self._unit_dir(project_id, unit_name, "produced")
        model_path = self._model_path(project_id, unit_name, "produced")
        if gate is ModelState.COMPLETED:
            self._write_threat_files(project_id, unit_name, model, now)
        elif ModelState(model.state) is not ModelState.COMPLETED:
            self._delete_threat_files(produced_dir)
        self._dump_yaml_atomic(model_path, model.model_dump(mode="json"))

    # --- the assessment write (schema-5 spec 2 and 4) ---------------------------

    def write_impact_assessment(
        self,
        project_id: str,
        unit_id: str,
        run_id: str,
        *,
        id: str,
        vulnerability_ref: str,
        disposition: ImpactDisposition | str,
        impact_description: str,
        exploitability_description: str,
        capability: str,
        capability_id: str,
        capability_path: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        factors: RiskMetrics | Mapping[str, Any],
    ) -> ImpactAssessment:
        """Write ONE assessment row: the sole writer of a schema-5 row.

        The row is the scored claim (schema-5 spec 2), so the STORE derives
        `risk` and `risk_vector`: `compute_risk` runs inside this commit, from
        the authored factors, and the caller never supplies either value. The
        first successful call advances the state to `IMPACT_ASSESSED`; the
        state is monotonic, so a later row keeps it. A row whose `id` already
        exists REPLACES it (a correction is one call); every other row is
        appended.

        Refused with a coded rejection, never a silent write:

        - a document that is not v5 (a raw v4/legacy read, an unreadable body,
          or no document at all) - a stale model is never mixed into a v5 run;
        - a state outside `PRIOR_ART`/`IMPACT_ASSESSED` (the gate contract);
        - a malformed `id` (`IA-*`) or `capability_id` (`P-*`);
        - an unknown `vulnerability_ref`;
        - a `capability_id` already held by another row of the SAME
          vulnerability (a second manner needs a distinct capability);
        - a `capability_path` element that resolves to no capability (local,
          self-qualified, or another unit's);
        - a factor set its disposition forbids (`risk_score.validate_metrics`).

        The document is committed atomically (`_commit`), so a killed write
        leaves the previous complete model.
        """
        row = self._assessment_row(
            id=id,
            vulnerability_ref=vulnerability_ref,
            disposition=disposition,
            impact_description=impact_description,
            exploitability_description=exploitability_description,
            capability=capability,
            capability_id=capability_id,
            capability_path=capability_path,
            evidence_refs=evidence_refs,
            factors=factors,
        )
        if not isinstance(unit_id, str) or not unit_id:
            raise ImpactAssessmentError(
                ["unit_id"],
                "threat model store: assessment write needs a non-empty "
                "harness-bound unit id",
            )
        if not run_id:
            raise ImpactAssessmentError(
                ["run_id"],
                "threat model store: assessment write needs a non-empty "
                "harness-bound run id",
            )
        with self._lock_for(project_id):
            unit_name = self._unit_name_for_write(project_id, unit_id)
            if self._model_path(project_id, unit_name, "consumed").exists():
                raise ImpactAssessmentError(
                    ["state"],
                    f"threat model store: the model of {unit_id!r} already "
                    f"lives in consumed/ (decided); an assessment is never "
                    f"written after the move",
                )
            model_path = self._model_path(project_id, unit_name, "produced")
            existing = self._load_document(model_path)
            if existing is None:
                if model_path.exists():
                    raise ThreatModelSchemaVersionError(
                        model_path, self._raw_version(model_path))
                raise ImpactAssessmentError(
                    ["state"],
                    f"threat model store: no produced model for {unit_id!r} to "
                    f"assess; write its gate sections first",
                )
            if not isinstance(existing, PartialThreatModel):
                # A v4 (and older) document reads raw but is never written: a
                # stale model is never mixed into a v5 run (schema-5 spec 11).
                raise ThreatModelSchemaVersionError(
                    model_path, existing.schema_version)
            if existing.state not in _ASSESSMENT_WRITE_STATES:
                accepted = " or ".join(
                    state.value for state in _ASSESSMENT_WRITE_STATES)
                raise ImpactAssessmentError(
                    ["state"],
                    "threat model store: an assessment row is written at "
                    f"{accepted}; the model is at {existing.state.value}",
                )
            self._validate_assessment_row(existing, row, project_id)
            # The score is computed in the commit, synchronously, from the
            # authored factors (schema-5 spec 3): no pending state, no second
            # state machine.
            result = compute_risk(row.factors)
            row = row.model_copy(update={
                "risk": result.score,
                "risk_vector": result.vector,
            })
            rows = [
                row if prior.id == row.id else prior
                for prior in existing.impact_assessment
            ]
            if not any(
                prior.id == row.id for prior in existing.impact_assessment
            ):
                rows.append(row)
            now = datetime.now(timezone.utc)
            merged = self._merged_document(
                document_of(existing), unit_id, run_id,
                ModelState.IMPACT_ASSESSED,
                {"impact_assessment": rows},
                now, model_path,
                project_id=project_id,
            )
            self._commit(
                project_id, unit_name, merged, ModelState.IMPACT_ASSESSED, now)
            return next(
                persisted for persisted in merged.impact_assessment
                if persisted.id == row.id
            )

    @staticmethod
    def _assessment_row(
        *,
        id: str,
        vulnerability_ref: str,
        disposition: ImpactDisposition | str,
        impact_description: str,
        exploitability_description: str,
        capability: str,
        capability_id: str,
        capability_path: Sequence[str],
        evidence_refs: Sequence[str],
        factors: RiskMetrics | Mapping[str, Any],
    ) -> ImpactAssessment:
        """One typed assessment row from its authored fields.

        The id and the capability id are the model-authored symbols, so their
        forms are validated here before the row joins the document. The derived
        `risk` and `risk_vector` stay at their schema defaults: only the commit
        computes them.
        """
        row_id = id.strip() if isinstance(id, str) else ""
        if _IMPACT_ID_RE.fullmatch(row_id) is None:
            raise ImpactAssessmentError(
                ["id"],
                f"threat model store: assessment id {id!r} is not of the "
                f"`IA-*` form (for example `IA-1`)",
            )
        capability_key = (
            capability_id.strip() if isinstance(capability_id, str) else "")
        if _CAPABILITY_ID_RE.fullmatch(capability_key) is None:
            raise ImpactAssessmentError(
                ["capability_id"],
                f"threat model store: capability_id {capability_id!r} is not "
                f"of the `P-*` form (for example `P-1`)",
            )
        path = list(capability_path or ())
        if any(not isinstance(ref, str) or not ref for ref in path):
            raise ImpactAssessmentError(
                ["capability_path"],
                "threat model store: capability_path is an ordered list of "
                "non-empty capability ids; a malformed element was supplied",
            )
        try:
            row_disposition = ImpactDisposition(disposition)
        except ValueError as exc:
            raise ImpactAssessmentError(
                ["disposition"],
                f"threat model store: unknown disposition {disposition!r}; "
                f"known: {', '.join(member.value for member in ImpactDisposition)}",
            ) from exc
        try:
            metrics = RiskMetrics.model_validate(factors)
        except ValueError as exc:
            raise ImpactAssessmentError(
                ["factors"],
                f"threat model store: the eight factors are invalid: {exc}",
            ) from exc
        return ImpactAssessment(
            id=row_id,
            vulnerability_ref=vulnerability_ref,
            disposition=row_disposition,
            impact_description=impact_description,
            exploitability_description=exploitability_description,
            capability=capability,
            capability_id=capability_key,
            capability_path=path,
            evidence_refs=list(evidence_refs or ()),
            factors=metrics,
        )

    def _validate_assessment_row(
        self,
        model: PartialThreatModel,
        row: ImpactAssessment,
        project_id: str,
    ) -> None:
        """The referential and factor invariants of one assessment row.

        The row joins the document only when it names a real vulnerability, its
        capability id is free for that vulnerability, every path element
        resolves, and its factor set matches its disposition. `validate_metrics`
        owns the impact-value rule; the referential rules mirror the completion
        checker's, so the write and the checker cannot disagree.
        """
        vulnerability_ids = {
            vulnerability.id for vulnerability in model.vulnerabilities}
        if row.vulnerability_ref not in vulnerability_ids:
            raise ImpactAssessmentError(
                ["vulnerability_ref"],
                f"threat model store: vulnerability_ref "
                f"{row.vulnerability_ref!r} names no vulnerability of "
                f"{model.unit_id!r}; known: "
                f"{', '.join(sorted(vulnerability_ids)) or 'none'}",
            )
        for prior in model.impact_assessment:
            if prior.id == row.id:
                continue
            if (
                prior.vulnerability_ref == row.vulnerability_ref
                and prior.capability_id == row.capability_id
            ):
                raise ImpactAssessmentError(
                    ["capability_id"],
                    f"threat model store: capability_id {row.capability_id!r} "
                    f"already keys row {prior.id!r} of vulnerability "
                    f"{row.vulnerability_ref!r}; a second manner needs a "
                    f"distinct capability id",
                )
        local = {
            prior.capability_id: prior
            for prior in model.impact_assessment
            if prior.capability_id and prior.id != row.id
        }
        # The project index is read only for a genuinely foreign ref: a local or
        # empty path costs no scan of every other unit's document.
        foreign: Mapping[str, Any] | None = None
        for ref in row.capability_path:
            if "::" in ref and not ref.startswith(f"{model.unit_id}::"):
                if foreign is None:
                    foreign = self._capability_index(project_id)
            if self._resolve_capability_ref(
                ref, model.unit_id, local, foreign or {}
            ) is None:
                raise ImpactAssessmentError(
                    ["capability_path"],
                    f"threat model store: capability_path ref {ref!r} resolves "
                    f"to no capability; name an existing local `P-*`, the "
                    f"unit-qualified `<unit_id>::P-*`, or another unit's "
                    f"`<unit_id>::P-*`",
                )
        findings = validate_metrics(
            row.factors, disposition=row.disposition.value)
        if findings:
            raise ImpactAssessmentError(["factors"], "; ".join(findings))

    @staticmethod
    def _resolve_capability_ref(
        ref: str,
        unit_id: str,
        local: Mapping[str, Any],
        foreign: Mapping[str, Any],
    ) -> Any | None:
        """One path element resolved locally, self-qualified, or across units.

        The same resolution the completion checker uses: an unqualified ref is
        local, `<unit_id>::P-*` is local, and any other `<unit>::P-*` is the
        project index. The row being written is never its own provider.
        """
        if ref.startswith(f"{unit_id}::"):
            return local.get(ref.split("::", 1)[1])
        if "::" in ref:
            return foreign.get(ref)
        return local.get(ref)

    def _capability_index(self, project_id: str) -> dict[str, dict]:
        """Every capability id in the project, keyed `Unit::P-*`.

        The index is the cross-unit resolution seam for a threat's chain. A
        malformed or unreadable document is skipped fail-open.
        """
        index: dict[str, dict] = {}
        for family in _READ_FAMILIES:
            for _directory, document in self._query_documents(
                project_id, family, produced_fallback=False
            ):
                unit_id = str(document.get("unit_id") or "")
                if not unit_id:
                    continue
                for row in document.get("impact_assessment") or []:
                    if not isinstance(row, Mapping):
                        continue
                    capability_id = str(row.get("capability_id") or "")
                    if capability_id:
                        index[f"{unit_id}::{capability_id}"] = {
                            "unit_id": unit_id,
                            "row": dict(row),
                        }
        return index

    def _write_threat_files(
        self,
        project_id: str,
        unit_name: str,
        model: PartialThreatModel,
        now: datetime,
    ) -> None:
        """Emit one threat file per DISPATCHABLE threat (S2 4.3, 8.1).

        A threat is dispatchable when its mirrored risk is above zero and its
        `impact_ref` resolves to a `threat` assessment: the file carries the
        top-level float `risk` (the derived score the mover reads) and the
        denormalised `impact` block (the row's prose, factors, score, vector,
        the precursors on its capability path, and the path).

        The shape is the LEAN self-contained one: the threat row and its one
        assessment row, repeated here as the `impact` block, so the mover and
        the payload need no model document for the assessment context (the
        model document moves with the unit's LAST threat file, so a consumed
        threat could not read it anyway). The threat row carries no retired
        likelihood / risk-factor / confidence / CIA vocabulary, and the block
        carries the prose, factors, score, and vector instead of a second
        scoring record. A threat with no resolving `impact` row (or one whose
        row belongs to another vulnerability) emits no file: the completion
        check reports it and the model is never consumable.
        """
        produced_dir = self._unit_dir(project_id, unit_name, "produced")
        assessments = {
            assessment.id: assessment for assessment in model.impact_assessment
        }
        index = self._capability_index(project_id)
        for assessment in model.impact_assessment:
            if assessment.capability_id:
                index[f"{model.unit_id}::{assessment.capability_id}"] = {
                    "unit_id": model.unit_id,
                    "row": assessment.model_dump(mode="json"),
                }

        def qualify(ref: str, unit: str) -> str:
            return ref if "::" in ref else f"{unit}::{ref}"

        written: set[str] = set()
        for threat in model.threats:
            # A threat with a zero score is stored in the model but never
            # dispatched: only a score above zero is work.
            if threat.risk <= 0:
                continue
            assessment = assessments.get(threat.impact_ref)
            if assessment is None or assessment.disposition != ImpactDisposition.THREAT:
                continue
            record = {
                "threat_id": threat.id,
                "unit_id": model.unit_id,
                "unit_kind": model.unit_kind.value,
                "run_id": model.run_id,
                "dispatch_id": dispatch_id(unit_name, threat.id),
                # The derived score, at the top level: the mover's ONE read.
                "risk": threat.risk,
                "threat": threat.model_dump(mode="json"),
                "impact": {
                    "impact_ref": assessment.id,
                    "impact_description": assessment.impact_description,
                    "exploitability_description": (
                        assessment.exploitability_description),
                    "disposition": assessment.disposition.value,
                    "capability": assessment.capability,
                    "capability_id": qualify(
                        assessment.capability_id, model.unit_id
                    ),
                    "capability_path": [
                        qualify(ref, model.unit_id)
                        for ref in assessment.capability_path
                    ],
                    "factors": assessment.factors.model_dump(mode="json"),
                    "risk": assessment.risk,
                    "risk_vector": assessment.risk_vector,
                    "chain": [
                        {
                            "capability": qualify(capability, model.unit_id),
                            "precursor": (
                                qualify(provider, model.unit_id)
                                if provider is not None else None
                            ),
                            "resolved": index.get(
                                qualify(capability, model.unit_id)
                            ),
                        }
                        for capability, provider in threat.enabling_precursors
                    ],
                },
                "created_at": now,
            }
            name = threat_file_name(threat.id)
            written.add(name)
            self._dump_yaml_atomic(produced_dir / name, record)
        for path in produced_dir.glob("threat-*.yaml"):
            if path.name not in written:
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning(
                        "threat model store: could not delete stale threat file %s (%s)",
                        path, exc,
                    )

    def _delete_threat_files(self, produced_dir: Path) -> None:
        if not produced_dir.exists():
            return
        for path in produced_dir.glob("threat-*.yaml"):
            try:
                path.unlink()
            except OSError as exc:
                logger.warning(
                    "threat model store: could not delete stale threat file %s (%s)",
                    path, exc,
                )

    # --- the notes store (#341, S1 5.2) -----------------------------------------

    def _load_notes(self, project_id: str) -> list[dict]:
        """The notes list in natural append order; a missing file or an
        unreadable `notes.yaml` degrades to [] (warned, never a raise)."""
        loaded = self._load_raw(self._notes_file(project_id))
        notes = loaded.get("notes") if loaded is not None else None
        if not isinstance(notes, list):
            return []
        return [note for note in notes if isinstance(note, dict)]

    def _save_notes(self, project_id: str, notes: list[dict]) -> None:
        """Rewrite `notes.yaml` under the shared bound (#341); a failure raises
        to the caller (O3). Atomic through the shared primitive."""
        kept = self._bounded(
            notes,
            max_records=NOTES_MAX_RECORDS,
            max_bytes=NOTES_MAX_BYTES,
            render=notes_body_len,
        )
        self._dump_yaml_atomic(self._notes_file(project_id), {"notes": kept})

    def write_note(
        self,
        project_id: str,
        unit_id: str,
        *,
        action: str = "append",
        note_name: str,
        kind: str,
        body: str,
        evidence: str | None = None,
        provenance: dict | None = None,
    ) -> str | None:
        """The `notes` body write over the per-project `notes.yaml`.

        The key is the store-owned `<unit_name>:<note_name>` (S2 10.2);
        `append` adds a note, `update` amends it, `delete` removes it. Returns
        the key; an update/delete on a missing key returns None (a denoted
        miss, never a failure). `phase_summary` is the hunter's kind and is
        NOT available here. Notes keep their natural append order and are
        bounded by the shared whole-file primitive."""
        if action not in _NOTE_ACTIONS:
            raise ValueError(f"threat model store: unknown note action {action!r}; known: {_NOTE_ACTIONS}")
        if kind not in NOTE_KINDS:
            raise ValueError(f"threat model store: unknown note kind {kind!r}; known: {NOTE_KINDS}")
        if not isinstance(note_name, str) or not note_name:
            raise ThreatModelIdentityError(
                ["note_name"], "threat model store: note_name must be a non-empty string"
            )
        if not isinstance(unit_id, str) or not unit_id:
            raise ThreatModelIdentityError(
                ["unit_id"], "threat model store: note needs a non-empty unit id"
            )
        with self._lock_for(project_id):
            key = f"{self._unit_name_for_write(project_id, unit_id)}:{note_name}"
            notes = self._load_notes(project_id)
            if action == "append":
                notes.append({
                    "key": key,
                    "unit_id": unit_id,
                    "note_name": note_name,
                    "kind": kind,
                    "body": body,
                    "evidence": evidence,
                    "provenance": provenance or {},
                })
                self._save_notes(project_id, notes)
                return key
            for record in notes:
                if record.get("key") != key:
                    continue
                if action == "update":
                    record.update({
                        "kind": kind,
                        "body": body,
                        "evidence": evidence,
                        "provenance": provenance or {},
                    })
                else:  # delete
                    notes.remove(record)
                self._save_notes(project_id, notes)
                return key
            return None

    def read_notes(self, project_id: str, key: str | None = None) -> list[dict]:
        """The notes for a `<unit_name>:<note_name>` key (a `<unit_name>`
        prefix reads the unit's notes), latest-first; `key=None` returns every
        note. Fail-open: an unreadable file degrades to [] (O4)."""
        with self._lock_for(project_id):
            notes = self._load_notes(project_id)
            if key is not None:
                notes = [
                    note for note in notes
                    if str(note.get("key") or "") == key
                    or str(note.get("key") or "").startswith(f"{key}:")
                ]
            return list(reversed(notes))
