"""The pod's persistent experiment-memory store (T7, D84-20/27/28).

The hunting test-executor's OWN memory: notes accumulate per `TestImplementationSpec`
identifier (the spec's canonical hash, D84-2) under the hunting module's store
seam, sibling to the hunt store (`data/hunts/`). Each spec owns one append-only
`notes.yaml`; a note rows under a `_seq`/`_ref`, rangeable by `variant_ref` via
the `notation_key` hierarchy and grep-match read (parent_key / key_keyword /
body_keyword), read-latest. The note VALUE fields are the D84-32 CANONICAL set.

This is NOT a `ProjectMemoryStore` (#137/#140) import - that is the
hunt-orchestrator's cross-project `(unit_id, fault_class)` namespace; the pod's
store is spec-keyed and lives inside the pod package (D84-20). The indexing /
retrieval patterns replicate it precisely (append-only, `_seq`/`_ref`,
grep-match, read-latest).

The prompt-memory pattern (D84-27, replicating the hunt-orchestrator's
`config_keys`/reading-guidance): `MEMORY_READ_GUIDANCE` is the persistent SYSTEM
block (tool contract + kinds + read filters), `compose_memory_guidance` renders
the per-turn USER-side INDEXABLE key-list header + the same guidance - both
embedded in the Runner's lap opener and the Triager's delta. NO deterministic
retrieval stage: the agent indexes the key list, then calls the `note` tool.

Fail-open durability (O3/O4): a write failure raises (the caller degrades to a
warning and keeps serving); a corrupt/unreadable file raises rather than
silently returning [] (the rewrite-on-append would otherwise destroy history).

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from pathlib import Path

import yaml

# The FIXED store root (D84-28): the hunting module's store seam, sibling to the
# hunt store (`data/hunts/`). No env var; the explicit-root constructor is kept
# for the tests' temp stores.
POD_MEMORY_ROOT = Path(__file__).resolve().parent.parent / "data" / "pod-memory"

# The closed enum of pod note kinds (D84-28): `experiment_summary` is the ONE
# consolidated P3 note per stretch (the Triager's primary artifact), `kb_insight`
# is a KB-derived testing primitive (the `implicit_test_primitive` analogue),
# `freeform` is any forward-useful note.
POD_NOTE_KINDS = ("experiment_summary", "kb_insight", "freeform")


def canonical_spec_id(spec: dict) -> str:
    """The spec's canonical id (D84-2): the sha256 of its sorted-key JSON,
    byte-identical to the shared `context.canonical_spec_hash` / the parent's
    `hunting_agent._canonical_hash`, so the pod's memory keys and the parent's
    experiment-log keys never drift."""
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash

    return canonical_spec_hash(spec)


def notation_key(spec_id: str, variant_ref: str, note_name: str) -> str:
    """The hierarchy key of a note: `<spec_id>:<variant_ref>:<note_name>` - the
    parent index is the spec id, ranged per variant/stretch (D84-19.3)."""
    return f"{spec_id}:{variant_ref}:{note_name}"


# The persistent SYSTEM-side block (D84-27): the tool contract + kinds + read
# filters, re-presented in every lap opener and triager delta.
MEMORY_READ_GUIDANCE = """# Pod experiment memory (the note tool)
Write or read pod experiment notes through the `note` tool, one operation per call.
Kinds (closed enum):
- experiment_summary - ONE consolidated summary of a whole stretch, written as
  the FINAL step of a stretch when the probe space is exhausted
- kb_insight - a knowledge-base-derived testing primitive worth carrying forward
- freeform - any forward-useful note
Read filters (combinable or singular):
- parent_key - the exact spec or variant prefix to range over (e.g. "<spec_id>:v3")
- key_keyword - a case-insensitive substring of the note key
- body_keyword - a case-insensitive substring of the note body
A read returns matching notes newest-first, with each note's full body verbatim."""


class PodMemoryStore:
    """The pod's append-only experiment-memory store, keyed by spec id.

    Layout: `<root>/specs/<spec_id>/notes.yaml` - create-on-first-write, one file
    per spec. Records accumulate monotonically (each with a per-spec `_seq` and a
    `_ref = note-<seq:04d>`); a read returns latest-first. All retrieval matching
    lives strictly inside this store (the #140 precedent).
    """

    def __init__(self, root_dir: str | Path | None = None):
        """The store rooted under `root_dir` (default: the FIXED seam root
        `data/pod-memory/`, sibling to the hunt store - D84-20/28)."""
        self._root = Path(root_dir) if root_dir is not None else POD_MEMORY_ROOT

    def _spec_dir(self, spec_id: str) -> Path:
        return self._root / "specs" / str(spec_id)

    def _notes_file(self, spec_id: str) -> Path:
        return self._spec_dir(spec_id) / "notes.yaml"

    def _read_records(self, spec_id: str) -> list[dict]:
        path = self._notes_file(spec_id)
        if not path.exists():
            return []
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise OSError(f"pod memory: unreadable notes file {path}: {exc}") from exc
        if isinstance(loaded, list):
            return [r for r in loaded if isinstance(r, dict)]
        return []

    @staticmethod
    def _next_seq(records: list[dict]) -> int:
        """One past the highest `_seq` (max+1, never count+1) so a partially
        degraded read can never collide a `_ref`/`_seq` (the #137 precedent)."""
        return max([int(r.get("_seq", 0)) for r in records] or [0]) + 1

    def _write_records(self, spec_id: str, records: list[dict]) -> None:
        path = self._notes_file(spec_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(records, fh, sort_keys=False)

    # -- write ---------------------------------------------------------------

    def append(
        self,
        spec_id: str,
        *,
        variant_ref: str,
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
        """Monotonically append ONE note of a closed `kind` for `(spec, variant)`;
        return its `_ref`. The VALUE fields are the D84-32 CANONICAL set. A write
        failure raises - the caller degrades to a warning and keeps serving (O3)."""
        if kind not in POD_NOTE_KINDS:
            raise ValueError(f"unknown pod note kind {kind!r}; known: {POD_NOTE_KINDS}")
        records = self._read_records(spec_id)
        seq = self._next_seq(records)
        stored = {
            "_seq": seq,
            "_ref": f"note-{seq:04d}",
            "key": notation_key(spec_id, variant_ref, note_name),
            "spec_id": spec_id,
            "variant_ref": variant_ref,
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
        self._write_records(spec_id, records)
        return stored["_ref"]

    # -- read ----------------------------------------------------------------

    @staticmethod
    def _norm(key: str) -> str:
        """Normalise a key's delimiter for comparison: `::` -> `:`."""
        return key.lower().replace("::", ":")

    def read_notes(
        self,
        spec_id: str,
        *,
        parent_key: str | None = None,
        key_keyword: str | None = None,
        body_keyword: str | None = None,
    ) -> list[dict]:
        """Grep-match read over the spec's notes (D84-19.1): the matching logic
        lives strictly here. `parent_key` ranges the `notation_key` prefix,
        `key_keyword`/`body_keyword` are case-insensitive substrings. Returns
        matching notes LATEST-FIRST (read-latest); zero matches is a valid empty
        result, never a failure. A corrupt file RAISES (O4) instead of returning
        [] - the caller degrades to an empty set and keeps serving."""
        records = self._read_records(spec_id)
        parent = self._norm(parent_key) if parent_key else None
        key_kw = key_keyword.lower() if key_keyword else None
        body_kw = body_keyword.lower() if body_keyword else None
        out = []
        for rec in records:
            key = str(rec.get("key") or "")
            if parent is not None and self._norm(parent) not in self._norm(key):
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
                         variant_ref: str) -> str:
    """The newest consolidated `experiment_summary` note body for one variant -
    the Triager's PRIMARY reasoning artifact (D84-23), verbatim. Fail-open: a
    None/raising store or no summary on file yields "" (the caller degrades to
    the raw triager context), never a raise."""
    if store is None:
        return ""
    try:
        notes = store.read_notes(
            spec_id, parent_key=notation_key(spec_id, variant_ref, ""))
    except Exception:  # noqa: BLE001 - fail-open read
        return ""
    for note in notes:  # newest-first
        if note.get("kind") == "experiment_summary":
            return str(note.get("body") or "")
    return ""


def compose_memory_guidance(store: PodMemoryStore | None, spec_id: str) -> str:
    """The per-turn USER-side memory header (D84-27): the INDEXABLE key-list of
    the spec's notes on file, plus the persistent reading guidance - embedded in
    the Runner's lap opener and the Triager's delta. NO deterministic retrieval
    stage: the agent indexes the keys, then calls the `note` tool. Fail-open: a
    missing/raising store yields the guidance with an empty index, never a raise."""
    keys: list[str] = []
    if store is not None:
        try:
            keys = list(store.note_keys(spec_id))
        except Exception:  # noqa: BLE001 - fail-open: an unreadable store degrades
            keys = []
    if keys:
        header = ("# Pod experiment memory (indexable keys)\n"
                  + "\n".join(f"- {k}" for k in keys))
    else:
        header = ("# Pod experiment memory (indexable keys)\n"
                  "No notes on file for this spec yet.")
    return f"{header}\n\n{MEMORY_READ_GUIDANCE}"