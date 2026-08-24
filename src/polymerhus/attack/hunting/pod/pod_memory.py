"""The pod's persistent experiment-memory store (T1, D84-33 through D84-38).

The hunting test-executor's OWN memory, projected onto the operator-locked
per-project deterministic-key pattern. One store per project under the hunting
module's data seam, sibling to the #164 hunter's `data/<project_id>/hunting/`
tree. The store has TWO bodies:

    data/<project_id>/test-executor-pod/
      experiment-logs/<fault>_<strategy>/<order>.yaml   (one file per variant)
      notes.yaml                                         (per-project notes)

The spec identifier is the #164 hunter's `SpecItem.spec_id = "<fault>_<strategy>"`
(D84-34) - the `_` separator + keyword sanitisation (`:`/`-` are poisoned) - and
IS the experiment-log directory name; the order number is the variant ordinal
(0, 1, 2, ...), so the file name IS the order and following variants are the next
file. Notes are keyed `<spec_id>:<order>:<note_name>` (D84-36), stored in the
per-project `notes.yaml`, append + read-latest. There is NO `_seq`/`_ref` on any
record (D84-36): the deterministic key + the natural list order disambiguate
every artifact; reads are latest-first by list position.

The reading surface gains typed attribute filters (`order`, `kind`,
`classification`, `symptom_status`) as first-class filters alongside the retained
`parent_key` / `key_keyword` / `body_keyword` substring match. The per-variant
experiment-log file is OVERWRITTEN idempotently on a re-run (D84-37: the
deterministic path is the address); the notes file is append-only with
read-latest.

T1 scope: this module establishes the per-project layout, the identity, the
notes file with the new key pattern, the attribute-filter read surface, and the
idempotent-overwrite mechanism for per-variant files. The full D6 experiment-log
content and the summary sink land in T2/T5; the `experiment-logs/` body here is
a minimal stub the later tickets build on.

The session-thread identity stays hash-based (D84-34): `canonical_spec_hash`
(`context.py`) remains the session discriminator and is NOT the memory key. The
old content-addressed `canonical_spec_id(spec)` keying function is retired.

Fail-open durability (O3/O4): a write failure raises (the caller degrades to a
warning and keeps serving); a corrupt/unreadable file raises rather than
silently returning [] (the rewrite paths would otherwise destroy history).

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from pathlib import Path

import yaml

# The hunting module's data seam (D84-33): sibling to the #164 hunter's
# `data/<project_id>/hunting/` tree. No env var; the explicit-root constructor
# is kept for the tests' temp stores.
HUNTING_DATA = Path(__file__).resolve().parent.parent / "data"

# The closed enum of pod note kinds (D84-28): `experiment_summary` is the ONE
# consolidated P3 note per stretch (the Triager's primary artifact), `kb_insight`
# is a KB-derived testing primitive (the `implicit_test_primitive` analogue),
# `freeform` is any forward-useful note.
POD_NOTE_KINDS = ("experiment_summary", "kb_insight", "freeform")

# The filename-keyword sanitisation banned set (D84-34, mirroring the #164
# hunter's ruling): `_` is the spec-id separator, so a keyword may not contain
# it; `:` is poisoned (it appears inside unit ids); `/`/`\` are path separators.
# Each banned char (plus control/NUL chars) is replaced with `-`, a safe,
# non-separator keyword char (`-` itself is never banned).
_UNSAFE_KEYWORD_CHARS = frozenset("_:/\\")


def _sanitise_keyword(keyword: str) -> str:
    """Sanitise a `<fault>`/`<strategy>` spec-id keyword (D84-34, G3)."""
    out = "".join(
        "-" if ch in _UNSAFE_KEYWORD_CHARS or ord(ch) < 32 else ch
        for ch in keyword
    )
    if not out or out in (".", ".."):
        raise ValueError(
            f"pod memory: keyword {keyword!r} sanitises to the unsafe "
            f"spec-id component {out!r}"
        )
    return out


def spec_identifier(fault_keyword: str, strategy_keyword: str) -> str:
    """The #164 hunter's `SpecItem.spec_id = "<fault>_<strategy>"` (D84-34):
    both keywords sanitised and joined by `_`, the one safe separator. This IS
    the experiment-log directory name. The `_` separator + keyword sanitisation
    ruling applies (`:` and `-` are poisoned separators)."""
    return f"{_sanitise_keyword(fault_keyword)}_{_sanitise_keyword(strategy_keyword)}"


def note_key(spec_id: str, order: int, note_name: str) -> str:
    """The deterministic note key (D84-36): `<spec_id>:<order>:<note_name>`."""
    return f"{spec_id}:{order}:{note_name}"


# The persistent SYSTEM-side block (D84-27, D84-36): the tool contract + kinds +
# the two bodies + the typed read filters, re-presented in every lap opener and
# triager delta.
MEMORY_READ_GUIDANCE = """# Pod experiment memory (the note tool)
Write or read pod experiment notes through the `note` tool, one operation per call.
The store has two bodies, both addressable by a deterministic identifier:
- experiment-logs/<fault>_<strategy>/<order>.yaml - the per-variant experiment log
- notes.yaml - the per-project note store, keyed <fault>_<strategy>:<order>:<note_name>
Kinds (closed enum):
- experiment_summary - ONE consolidated summary of a whole stretch, written as
  the FINAL step of a stretch when the probe space is exhausted
- kb_insight - a knowledge-base-derived testing primitive worth carrying forward
- freeform - any forward-useful note
Read filters (combinable or singular):
- order - the variant ordinal (int)
- kind / classification / symptom_status - typed attribute filters
- parent_key - the exact spec or variant prefix to range over (e.g. "<spec_id>:0")
- key_keyword - a case-insensitive substring of the note key
- body_keyword - a case-insensitive substring of the note body
A read returns matching notes newest-first, with each note's full body verbatim."""


class PodMemoryStore:
    """The pod's per-project experiment-memory store, keyed by the #164 spec id.

    Layout: `<root>/experiment-logs/<spec_id>/<order>.yaml` + `<root>/notes.yaml`.
    The per-variant experiment-log file is overwritten idempotently on a re-run
    (D84-37); the notes file is append-only with read-latest, records addressed
    by the deterministic `<spec_id>:<order>:<note_name>` key + typed attribute
    filters (D84-36) - no `_seq`/`_ref`. All retrieval matching lives strictly
    inside this store.
    """

    def __init__(self, root_dir: str | Path | None = None, *,
                 project_id: str | None = None):
        """The store rooted under `root_dir` (tests' temp stores) OR, in
        production, the per-project root `data/<project_id>/test-executor-pod/`
        under the hunting module's data seam (D84-33). One of the two is
        required - there is no fixed default root."""
        if root_dir is not None:
            self._root = Path(root_dir)
        elif project_id is not None:
            self._root = HUNTING_DATA / str(project_id) / "test-executor-pod"
        else:
            raise ValueError(
                "PodMemoryStore needs a root_dir (tests) or a project_id (production)"
            )

    # -- paths ---------------------------------------------------------------

    def _spec_log_dir(self, spec_id: str) -> Path:
        return self._root / "experiment-logs" / str(spec_id)

    def _variant_log_file(self, spec_id: str, order: int) -> Path:
        return self._spec_log_dir(spec_id) / f"{int(order)}.yaml"

    def _notes_file(self) -> Path:
        return self._root / "notes.yaml"

    # -- experiment-log body (T1 stub; the D6 content + summary sink is T2/T5) --

    def write_variant_log(self, spec_id: str, order: int, records: list) -> None:
        """IDEMPOTENTLY overwrite the variant's experiment-log file (D84-37):
        one file per variant, the deterministic path is the address. A re-run of
        the same (spec, order) rewrites the file - the persisted log is the
        current truth, never an unbounded accumulation. A write failure raises
        for the caller to degrade (O3)."""
        path = self._variant_log_file(spec_id, order)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(records, fh, sort_keys=False)

    def read_variant_log(self, spec_id: str, order: int) -> list[dict]:
        """The variant's persisted experiment-log records (T1 stub), in list
        order. A corrupt file raises (O4) rather than returning []."""
        path = self._variant_log_file(spec_id, order)
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(
                f"pod memory: unreadable experiment-log file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        return []

    def list_variant_orders(self, spec_id: str) -> list[int]:
        """The variant ORDERS present on file for one spec (the prompt-embedded
        experiment-log identifiers, D84-27): following variants are enumerable
        from the directory listing."""
        log_dir = self._spec_log_dir(spec_id)
        if not log_dir.exists():
            return []
        orders = []
        for child in log_dir.iterdir():
            if child.suffix == ".yaml":
                try:
                    orders.append(int(child.stem))
                except ValueError:
                    continue
        return sorted(orders)

    # -- notes record mechanics ----------------------------------------------

    def _read_notes_records(self) -> list[dict]:
        path = self._notes_file()
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"pod memory: unreadable notes file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        return []

    def _write_notes_records(self, records: list[dict]) -> None:
        path = self._notes_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(records, fh, sort_keys=False)

    # -- write ---------------------------------------------------------------

    def append(
        self,
        spec_id: str,
        *,
        order: int,
        note_name: str,
        kind: str,
        body: str,
        classification: str = "",
        symptom_status: str = "",
        kb_primitives_used: tuple[str, ...] | list[str] = (),
        exhaustion_evidence: str = "",
        evidence: str = "",
        provenance: dict | None = None,
    ) -> str:
        """Append ONE note of a closed `kind` under the deterministic key
        `<spec_id>:<order>:<note_name>` (D84-36); return its key. The notes file
        is append-only with read-latest (a re-run appends a newer record under
        the same key). The VALUE fields are the D84-32 CANONICAL set minus
        `_seq`/`_ref`. A write failure raises - the caller degrades to a warning
        and keeps serving (O3)."""
        if kind not in POD_NOTE_KINDS:
            raise ValueError(f"unknown pod note kind {kind!r}; known: {POD_NOTE_KINDS}")
        records = self._read_notes_records()
        stored = {
            "key": note_key(spec_id, order, note_name),
            "spec_id": spec_id,
            "order": int(order),
            "note_name": note_name,
            "kind": kind,
            "body": body,
            "classification": classification,
            "symptom_status": symptom_status,
            "kb_primitives_used": list(kb_primitives_used),
            "exhaustion_evidence": exhaustion_evidence,
            "evidence": evidence,
            "provenance": provenance or {},
        }
        records.append(stored)
        self._write_notes_records(records)
        return stored["key"]

    # -- read ----------------------------------------------------------------

    @staticmethod
    def _norm(key: str) -> str:
        """Normalise a key's delimiter for comparison: `::` -> `:`."""
        return key.lower().replace("::", ":")

    def read_notes(
        self,
        spec_id: str,
        *,
        order: int | None = None,
        kind: str | None = None,
        classification: str | None = None,
        symptom_status: str | None = None,
        parent_key: str | None = None,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
    ) -> list[dict]:
        """Grep-match read over the project's notes (D84-36): the matching logic
        lives strictly here. The typed attribute filters (`order`, `kind`,
        `classification`, `symptom_status`) are first-class alongside the
        retained `parent_key` / `key_keyword` / `body_keyword` substrings.
        Returns matching notes LATEST-FIRST (read-latest); zero matches is a
        valid empty result, never a failure. A corrupt file RAISES (O4) instead
        of returning [] - the caller degrades to an empty set and keeps serving."""
        records = self._read_notes_records()
        parent = self._norm(parent_key) if parent_key else None
        key_kw = key_keyword.lower() if key_keyword else None
        body_kw = body_keyword.lower() if body_keyword else None
        out = []
        for rec in records:
            if str(rec.get("spec_id")) != str(spec_id):
                continue
            key = str(rec.get("key") or "")
            if order is not None and rec.get("order") != order:
                continue
            if kind is not None and rec.get("kind") != kind:
                continue
            if classification is not None and (rec.get("classification") or "") != classification:
                continue
            if symptom_status is not None and (rec.get("symptom_status") or "") != symptom_status:
                continue
            if parent is not None and parent not in self._norm(key):
                continue
            if key_kw is not None and key_kw not in key.lower():
                continue
            if body_kw is not None and body_kw not in str(rec.get("body") or "").lower():
                continue
            out.append(rec)
        return list(reversed(out))

    def note_keys(self, spec_id: str) -> list[str]:
        """The spec's note KEYS in newest-first order - the prompt-embedded
        indexable list (D84-27), so the Runner/Triager can index into prior
        notes and then call the `note` read tool for the relevant body."""
        return [str(r.get("key")) for r in self.read_notes(spec_id) if r.get("key")]


def read_variant_summary(store: PodMemoryStore | None, spec_id: str,
                         order: int) -> str:
    """The newest consolidated `experiment_summary` note body for one variant
    ORDER - the Triager's PRIMARY reasoning artifact (D84-23), verbatim.
    Fail-open: a None/raising store or no summary on file yields "" (the caller
    degrades to the raw triager context), never a raise."""
    if store is None:
        return ""
    try:
        notes = store.read_notes(spec_id, order=order, kind="experiment_summary")
    except Exception:  # noqa: BLE001 - fail-open read
        return ""
    for note in notes:  # newest-first
        return str(note.get("body") or "")
    return ""


def compose_memory_guidance(store: PodMemoryStore | None, spec_id: str) -> str:
    """The per-turn USER-side memory header (D84-27): the INDEXABLE key-list of
    the spec's notes on file PLUS the experiment-log identifiers (spec id + the
    orders present on file), plus the persistent reading guidance - embedded in
    the Runner's lap opener and the Triager's delta. NO deterministic retrieval
    stage: the agent indexes the keys, then calls the `note` tool. Fail-open: a
    missing/raising store yields the guidance with an empty index, never a
    raise."""
    keys: list[str] = []
    log_ids: list[str] = []
    if store is not None:
        try:
            keys = list(store.note_keys(spec_id))
            log_ids = [f"{spec_id}/{o}" for o in store.list_variant_orders(spec_id)]
        except Exception:  # noqa: BLE001 - fail-open: an unreadable store degrades
            keys, log_ids = [], []
    lines = ["# Pod experiment memory (indexable keys)"]
    if keys:
        lines.append("# Notes")
        lines.extend(f"- {k}" for k in keys)
    else:
        lines.append("# Notes")
        lines.append("- (no notes on file for this spec yet)")
    if log_ids:
        lines.append("# Experiment logs")
        lines.extend(f"- {i}" for i in log_ids)
    return f"\n".join(lines) + f"\n\n{MEMORY_READ_GUIDANCE}"
