# Rate-Limit Posture Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendere la postura di rate limit di ogni target di un progetto una vista YAML persistente e leggibile da tutte le fasi, scritta dal controllore e consumabile dagli agenti di hunting in sola lettura.

**Architecture:** un modulo nuovo `app/rate_limit/` (store + tool) sul precedente di `app/auth/`; il pipeline proietta lo stesso `RateProfile` già persistito in `recon_runs.stats` dentro `data/<project_id>/rate-limit/<target_key>.yaml`; il tool è read-only e viene legato solo agli agenti di hunting che eseguono comandi su Kali.

**Tech Stack:** Python 3.12, pydantic v2, PyYAML, pytest, LangChain tools, Postgres (invariato).

**Spec:** `docs/superpowers/specs/2026-09-25-rate-limit-posture-store-design.md`

## Global Constraints

- Il file è **advisory**: nessun enforcement, nessuna modifica a lease, proxy o governor (spec D4, D6).
- Un file **per `target_key`** sotto `data/<project_id>/rate-limit/` (spec D1).
- Postgres (`recon_runs.stats`) resta intatto e resta il registro per-run; il file è la postura corrente (spec D2).
- Il tool per gli agenti è in **sola lettura**; il controllore è l'unico scrittore (spec D3).
- Scrittura del file fallita ⇒ **run `failed`** prima di qualunque fase (spec D5).
- Nessun import di `kali.*` da `polymerhus.app.*`: la semantica di match degli host è rispecchiata, con un test che la pinna.
- Ogni file toccato rispetta `CODING_STANDARD.md`: nessun I/O all'import, contratti pydantic chiusi (`extra="forbid"`), scritture atomiche.
- Il workflow dell'orchestrator di recon resta a **due turni**: nessun nuovo prompt, nessun nuovo turn brief, nessun tool aggiunto all'actor (spec §15).

## Review Focus

- Un file di postura **corrotto** non deve mai leggersi come "nessun limite noto": il comportamento atteso è un errore esplicito.
- Un **host in scope ma non misurato** (sottodominio scoperto in wildcard) non deve ricevere la postura di un altro host: deve ottenere `no_posture_for_host`.
- Due run concorrenti sullo stesso target: una misura **più vecchia** non deve sovrascrivere una più nuova.
- Il file non deve contenere **segreti**: la postura non ne ha per costruzione, e il test del tool lo verifica.
- Una scrittura fallita non deve lasciare la run a metà: nessuna fase deve partire.

## Design units

| File | Responsabilità |
|---|---|
| `src/polymerhus/app/data_root.py` | possiede lo scaffold; guadagna `rate-limit` |
| `src/polymerhus/app/rate_limit/store.py` | envelope, scrittura atomica, lettura, resolve |
| `src/polymerhus/app/rate_limit/tool.py` | l'unico tool agent-facing, read-only |
| `src/polymerhus/recon/control/pipeline.py` | la proiezione dopo il turno di mapping |
| `src/polymerhus/attack/hunting/pod/agents.py` | binding al Pod Runner |
| `src/polymerhus/attack/hunting/hunter_tools.py` | binding al Hunter |

---

### Task 1: Scaffold e store — il percorso di scrittura

**Files:**
- Modify: `src/polymerhus/app/data_root.py` (`PROJECT_SCAFFOLD`)
- Create: `src/polymerhus/app/rate_limit/__init__.py`
- Create: `src/polymerhus/app/rate_limit/store.py`
- Modify: `src/polymerhus/app/CONTEXT.md` (una voce per il nuovo modulo)
- Test: `tests/app/test_rate_limit_posture_store.py`

**Interfaces:**
- Consumes: `app.data_root.project_dir`, `app.data_root.validate_path_component`, `recon.domain.rate_limit.RateProfile`
- Produces: `POSTURE_VERSION`, `PostureEnvelope`, `PostureRecord`, `PostureWriteError`, `PostureUnreadableError`, `RateLimitPostureStore(root=None).write(project_id, profile, source_run_id) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/app/test_rate_limit_posture_store.py
import yaml
import pytest

from polymerhus.app.rate_limit.store import (
    POSTURE_VERSION,
    PostureWriteError,
    RateLimitPostureStore,
)
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile


def _profile(target_key: str = "acme.com") -> RateProfile:
    return RateProfile.conservative(
        target_key, [target_key], rate_limit_safety_budget(), "test fixture",
    )


def test_write_creates_one_file_per_target(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)

    path = store.write("proj-1", _profile("api.acme.com"), "run-1")

    assert path == tmp_path / "proj-1" / "rate-limit" / "api.acme.com.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["version"] == POSTURE_VERSION
    assert payload["advisory"] is True
    assert payload["source_run_id"] == "run-1"
    assert payload["profile"]["target_key"] == "api.acme.com"


def test_write_rejects_an_unsafe_target_key(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)

    with pytest.raises(PostureWriteError):
        store.write("proj-1", _profile("../escape"), "run-1")


def test_write_keeps_the_newer_measurement(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    newer = _profile("acme.com")
    older = newer.model_copy(
        update={"measured_at": newer.measured_at.replace(year=newer.measured_at.year - 1)}
    )

    store.write("proj-1", newer, "run-new")
    store.write("proj-1", older, "run-old")

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert stored["source_run_id"] == "run-new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_rate_limit_posture_store.py -q`
Expected: FAIL with `ModuleNotFoundError: polymerhus.app.rate_limit`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/polymerhus/app/rate_limit/__init__.py
"""The per-project rate-limit posture bucket (#238 follow-up)."""
```

```python
# src/polymerhus/app/rate_limit/store.py
"""The per-project, per-target rate-limit posture bucket (#238 follow-up).

Layout: ``<data_root>/<project_id>/rate-limit/<target_key>.yaml``, one file per
measured target. The file is the project's CURRENT posture, readable by every
phase; ``recon_runs.stats["rate_limit"]`` stays the immutable per-run record.
The envelope is ``advisory: true``: the limit is KNOWN, never ENFORCED.

No import-time I/O (CODING_STANDARD section 6); the root is the app-owned
``DATA_ROOT`` resolved through the one layout owner, with an explicit root for
tests (the AuthStore precedent).
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from polymerhus.app.data_root import DATA_ROOT, project_dir, validate_path_component
from polymerhus.recon.domain.rate_limit import RateProfile

logger = logging.getLogger(__name__)

POSTURE_VERSION = "rate-limit-posture/v1"
_BUCKET_NAME = "rate-limit"


class PostureWriteError(ValueError):
    """A write that could not land. The caller fails the run loudly."""


class PostureUnreadableError(ValueError):
    """A stored file that exists but cannot be validated. NEVER 'absent'."""


class PostureEnvelope(BaseModel):
    """The on-disk contract, closed like every contract in the repo."""

    model_config = ConfigDict(extra="forbid")

    version: str = POSTURE_VERSION
    source_run_id: str
    advisory: bool = True
    profile: RateProfile


@dataclass(frozen=True)
class PostureRecord:
    """What a reader gets back: the validated profile plus its provenance."""

    target_key: str
    profile: RateProfile
    source_run_id: str
    fresh: bool


_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def _lock_for(project_id: str) -> threading.Lock:
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the same directory + os.replace (the AuthStore precedent)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class RateLimitPostureStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else DATA_ROOT

    def _dir(self, project_id: str) -> Path:
        return project_dir(project_id, _BUCKET_NAME, root=self._root)

    def _path(self, project_id: str, target_key: str) -> Path:
        name = validate_path_component(target_key, "target_key")
        return self._dir(project_id) / f"{name}.yaml"

    def write(
        self, project_id: str, profile: RateProfile, source_run_id: str
    ) -> Path:
        try:
            path = self._path(project_id, profile.target_key)
        except ValueError as exc:
            raise PostureWriteError(str(exc)) from exc
        envelope = PostureEnvelope(source_run_id=source_run_id, profile=profile)
        text = yaml.safe_dump(envelope.model_dump(mode="json"), sort_keys=False)
        with _lock_for(project_id):
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = self._read_envelope(path)
            if existing is not None and existing.profile.measured_at > profile.measured_at:
                logger.warning(
                    "rate posture for %s/%s on disk is newer (%s > %s); keeping it",
                    project_id, profile.target_key,
                    existing.profile.measured_at, profile.measured_at,
                )
                return path
            try:
                _atomic_write(path, text)
            except OSError as exc:
                raise PostureWriteError(
                    f"could not write the rate posture for "
                    f"{project_id}/{profile.target_key}: {exc}"
                ) from exc
        return path

    def _read_envelope(self, path: Path) -> PostureEnvelope | None:
        if not path.exists():
            return None
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - any parse failure is unreadable
            raise PostureUnreadableError(f"{path} is not readable YAML: {exc}") from exc
        try:
            return PostureEnvelope.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - any schema failure is unreadable
            raise PostureUnreadableError(f"{path} failed validation: {exc}") from exc
```

Modify `src/polymerhus/app/data_root.py` — aggiungi la voce allo scaffold fisso:

```python
PROJECT_SCAFFOLD: tuple[str, ...] = (
    "skills",
    "auth",
    "rate-limit",
    "hunting/orchestration",
    # ...le voci esistenti restano invariate...
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_rate_limit_posture_store.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/app/data_root.py src/polymerhus/app/rate_limit \
  src/polymerhus/app/CONTEXT.md tests/app/test_rate_limit_posture_store.py
git commit -m "feat(app): add the per-project rate-limit posture store (write path)"
```

---

### Task 2: Store — lettura, elenco, resolve per host, freschezza

**Files:**
- Modify: `src/polymerhus/app/rate_limit/store.py`
- Test: `tests/app/test_rate_limit_posture_store.py`

**Interfaces:**
- Consumes: `RateLimitPostureStore._read_envelope`, `RateProfile.is_fresh`
- Produces: `host_matches(host, patterns) -> bool`, `RateLimitPostureStore.read/list_targets/resolve`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/app/test_rate_limit_posture_store.py
from polymerhus.app.rate_limit.store import (
    PostureRecord,
    PostureUnreadableError,
    host_matches,
)


def test_read_is_none_only_when_the_file_is_absent(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    assert store.read("proj-1", "acme.com") is None


def test_read_reports_freshness(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")

    record = store.read("proj-1", "acme.com")

    assert isinstance(record, PostureRecord)
    assert record.fresh is True
    assert record.profile.target_key == "acme.com"
    assert record.source_run_id == "run-1"


def test_list_targets_is_empty_without_a_bucket(tmp_path):
    assert RateLimitPostureStore(root=tmp_path).list_targets("nope") == []


def test_list_targets_lists_every_written_target(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")
    store.write("proj-1", _profile("api.acme.com"), "run-1")

    assert store.list_targets("proj-1") == ["acme.com", "api.acme.com"]


def test_resolve_matches_exact_and_wildcard_hosts():
    assert host_matches("api.acme.com", ["api.acme.com"]) is True
    assert host_matches("API.ACME.COM", ["api.acme.com"]) is True
    assert host_matches("api.acme.com", ["*.acme.com"]) is True
    assert host_matches("other.example.com", ["acme.com"]) is False
    assert host_matches(None, ["acme.com"]) is False
    assert host_matches("anything", []) is True


def test_resolve_returns_none_for_an_uncovered_host(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")

    assert store.resolve("proj-1", "api.acme.com") is None
    assert store.resolve("proj-1", "acme.com").target_key == "acme.com"


def test_a_corrupt_file_is_unreadable_never_absent(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")
    (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").write_text(
        "::: not yaml :::", encoding="utf-8"
    )

    with pytest.raises(PostureUnreadableError):
        store.read("proj-1", "acme.com")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_rate_limit_posture_store.py -q`
Expected: FAIL with `ImportError: cannot import name 'host_matches'`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/polymerhus/app/rate_limit/store.py - aggiungi in testa: import fnmatch
# e, a fine modulo, il predicato e i tre metodi di lettura.
import fnmatch
from datetime import datetime, timezone


def host_matches(host: str | None, patterns) -> bool:
    """Whether a request host is this posture's business.

    MIRRORS `kali.http_history.governor.host_matches` BY VALUE - never imported,
    because `kali` is not on the agent image's import path. An empty pattern
    list means "whatever this project sends" (the posture is already
    per-target); a non-empty list is exact match plus shell-style wildcards,
    case-insensitive, mirroring the governor exactly (no trailing-dot
    normalisation beyond the strip the governor performs).
    """
    wanted = tuple(str(pattern).lower() for pattern in (patterns or ()))
    if not wanted:
        return True
    if not host:
        return False
    value = host.strip().lower()
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in wanted)


class RateLimitPostureStore:
    # ...il codice di Task 1 resta invariato; aggiungi questi metodi...

    def read(self, project_id: str, target_key: str) -> PostureRecord | None:
        envelope = self._read_envelope(self._path(project_id, target_key))
        if envelope is None:
            return None
        return PostureRecord(
            target_key=envelope.profile.target_key,
            profile=envelope.profile,
            source_run_id=envelope.source_run_id,
            fresh=envelope.profile.is_fresh(datetime.now(timezone.utc)),
        )

    def list_targets(self, project_id: str) -> list[str]:
        directory = self._dir(project_id)
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.yaml") if path.is_file())

    def resolve(self, project_id: str, host: str) -> PostureRecord | None:
        for target_key in self.list_targets(project_id):
            record = self.read(project_id, target_key)
            if record is not None and host_matches(host, record.profile.host_patterns):
                return record
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_rate_limit_posture_store.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/app/rate_limit/store.py tests/app/test_rate_limit_posture_store.py
git commit -m "feat(app): read, list and host-resolve the rate-limit posture"
```

---

### Task 3: Tool agent-facing in sola lettura

**Files:**
- Create: `src/polymerhus/app/rate_limit/tool.py`
- Test: `tests/app/test_rate_limit_posture_tool.py`

**Interfaces:**
- Consumes: `RateLimitPostureStore.read/list_targets/resolve`, `RateProfile.conservative`
- Produces: `RATE_LIMIT_POSTURE_CONTRACT`, `build_rate_limit_posture_tool(project_id, store=None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/app/test_rate_limit_posture_tool.py
from polymerhus.app.rate_limit.store import RateLimitPostureStore
from polymerhus.app.rate_limit.tool import build_rate_limit_posture_tool
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile


def _store(tmp_path) -> RateLimitPostureStore:
    store = RateLimitPostureStore(root=tmp_path)
    store.write(
        "proj-1",
        RateProfile.conservative(
            "acme.com", ["acme.com"], rate_limit_safety_budget(), "fixture",
        ),
        "run-1",
    )
    return store


def test_resolve_reports_a_known_target(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "resolve", "host": "acme.com"})

    assert result["ok"] is True
    assert result["status"] == "known_target"
    assert result["posture"]["target_key"] == "acme.com"
    assert result["posture"]["advisory"] is True
    assert result["posture"]["fresh"] is True


def test_resolve_reports_an_unmeasured_host_with_the_conservative_default(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "resolve", "host": "api.acme.com"})

    assert result["ok"] is True
    assert result["status"] == "no_posture_for_host"
    assert result["assumed"]["rate_per_s"] == 1.0
    assert result["assumed"]["burst"] == 1
    assert result["assumed"]["max_concurrency"] == 1


def test_list_reports_no_postures_for_an_empty_project(tmp_path):
    tool = build_rate_limit_posture_tool(
        "proj-1", store=RateLimitPostureStore(root=tmp_path)
    )

    assert tool.invoke({"command": "list"})["status"] == "no_postures"


def test_an_unreadable_file_is_reported_never_absent(tmp_path):
    store = _store(tmp_path)
    (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").write_text(
        "::: not yaml :::", encoding="utf-8"
    )
    tool = build_rate_limit_posture_tool("proj-1", store=store)

    result = tool.invoke({"command": "resolve", "host": "acme.com"})

    assert result["ok"] is False
    assert result["status"] == "unreadable"


def test_the_tool_exposes_no_write_operation(tmp_path):
    tool = build_rate_limit_posture_tool("proj-1", store=_store(tmp_path))

    result = tool.invoke({"command": "get", "target": "acme.com"})
    assert result["ok"] is True  # read path works

    # There is no write command in the closed args schema: the schema itself is
    # the guarantee. Assert it here so a future widening fails loudly.
    assert set(tool.args_schema.model_fields) == {"command", "target", "host"}
    assert "write" not in str(tool.args_schema.model_fields["command"].annotation)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/app/test_rate_limit_posture_tool.py -q`
Expected: FAIL with `ModuleNotFoundError: polymerhus.app.rate_limit.tool`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/polymerhus/app/rate_limit/tool.py
"""The one shared read-only agent tool over the rate-limit posture bucket
(#238 follow-up).

Read-only by construction: the controller is the only writer, so no model can
enlarge a budget by writing here. The contract rides the tool description
verbatim (the AUTH_STORE_CONTRACT / GRAPH_VIEW_CONTRACT precedent).
"""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from polymerhus.app.rate_limit.store import (
    PostureRecord,
    PostureUnreadableError,
    RateLimitPostureStore,
)
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile

RATE_LIMIT_POSTURE_CONTRACT = (
    "Read the project's measured rate-limit posture, one record per target.\n\n"
    "A posture is the traffic shape this project measured against ONE target: "
    "its host patterns, the safe rate per second, the burst, the concurrency "
    "ceiling, when it was measured and when it expires. It is ADVISORY: it is "
    "NOT enforced on your commands. Respect it anyway - it is the only measured "
    "fact about how hard this target may be hit.\n\n"
    "Operations: `list` (targets with a posture), `get` (one target), "
    "`resolve` (given a request host, which posture covers it). Before sending "
    "traffic to a host, `resolve` it. If the answer is `no_posture_for_host`, "
    "the target was never measured: assume the conservative default the tool "
    "returns (1 request per second, burst 1, concurrency 1) and say so in your "
    "reasoning. If the answer is `unreadable`, assume nothing and report it.\n\n"
    "This tool never writes. A posture can only be produced by the run's "
    "deterministic rate mapping."
)


class PostureArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["list", "get", "resolve"]
    target: str = ""
    host: str = ""


def _render(record: PostureRecord) -> dict:
    policy = record.profile.traffic_policy
    return {
        "target_key": record.target_key,
        "outcome": record.profile.outcome,
        "safe_rate_per_s": record.profile.safe_rate_per_s,
        "burst": policy.burst,
        "max_concurrency": policy.max_concurrency,
        "host_patterns": list(record.profile.host_patterns),
        "measured_at": record.profile.measured_at.isoformat(),
        "expires_at": record.profile.expires_at.isoformat(),
        "fresh": record.fresh,
        "source_run_id": record.source_run_id,
        "advisory": True,
    }


def _conservative_default(target_key: str) -> dict:
    """The value to assume for an unmeasured host. Single-sourced from the
    domain fallback so the tool and the admission can never disagree."""
    profile = RateProfile.conservative(
        target_key, [], rate_limit_safety_budget(),
        "unmeasured target: assume the conservative fallback",
    )
    policy = profile.traffic_policy
    return {
        "rate_per_s": policy.rate_per_s,
        "burst": policy.burst,
        "max_concurrency": policy.max_concurrency,
        "basis": "conservative-fallback",
    }


class RateLimitPostureTool(BaseTool):
    name: str = "rate_limit_posture"
    description: str = RATE_LIMIT_POSTURE_CONTRACT
    args_schema: type[BaseModel] = PostureArgs

    project_id: str = ""
    store: RateLimitPostureStore | None = None

    def _run(self, command: str, target: str = "", host: str = "") -> dict:
        seam = self.store if self.store is not None else RateLimitPostureStore()
        try:
            if command == "list":
                records = [
                    record
                    for record in (
                        seam.read(self.project_id, key)
                        for key in seam.list_targets(self.project_id)
                    )
                    if record is not None
                ]
                if not records:
                    return {"ok": True, "status": "no_postures", "targets": []}
                return {
                    "ok": True,
                    "status": "known_targets",
                    "targets": [_render(record) for record in records],
                }
            if command == "get":
                record = seam.read(self.project_id, target)
                if record is None:
                    return {
                        "ok": True,
                        "status": "no_postures",
                        "target": target,
                        "assumed": _conservative_default(target),
                    }
                return {"ok": True, "status": "known_target", "posture": _render(record)}
            if command == "resolve":
                record = seam.resolve(self.project_id, host)
                if record is None:
                    known = bool(seam.list_targets(self.project_id))
                    return {
                        "ok": True,
                        "status": "no_posture_for_host" if known else "no_postures",
                        "host": host,
                        "assumed": _conservative_default(host),
                    }
                return {"ok": True, "status": "known_target", "posture": _render(record)}
        except PostureUnreadableError as exc:
            return {"ok": False, "status": "unreadable", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return {"ok": False, "status": "store_unavailable", "detail": str(exc)}
        return {
            "ok": False,
            "status": "invalid_command",
            "detail": "command must be list, get or resolve",
        }


def build_rate_limit_posture_tool(
    project_id: str | None = None, store: RateLimitPostureStore | None = None
) -> RateLimitPostureTool:
    """Build the ONE `rate_limit_posture` tool bound to `project_id`.

    `project_id` defaults to the control-plane project (`config.PROJECT_ID`),
    resolved LAZILY here so import never touches env (CODING_STANDARD §6).
    """
    if project_id is None:
        from polymerhus.app.config import config  # noqa: PLC0415

        project_id = config.PROJECT_ID
    return RateLimitPostureTool(project_id=project_id, store=store)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/app/test_rate_limit_posture_tool.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/app/rate_limit/tool.py tests/app/test_rate_limit_posture_tool.py
git commit -m "feat(app): expose the read-only rate-limit posture tool"
```

---

### Task 4: Proiezione nel pipeline e test di non-divergenza

**Files:**
- Modify: `src/polymerhus/recon/control/pipeline.py` (dopo `_persist_rate_profile`)
- Create: `tests/recon/test_rate_limit_posture_write.py`

**Interfaces:**
- Consumes: `RateLimitPostureStore.write`, `RateProfile`
- Produces: parametro keyword-only `write_posture` su `run_pipeline` e helper di modulo `_default_write_posture(project_id, profile, run_id) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/recon/test_rate_limit_posture_write.py
"""The pipeline projects the SAME validated profile into the project bucket,
after Postgres and before any phase. Fully mocked (the FakeRegistry shape from
tests/recon/test_pipeline.py): no live Neo4j/Postgres/pod graph."""
import asyncio

import yaml

from polymerhus.app.rate_limit.store import RateLimitPostureStore
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.control import pipeline
from polymerhus.recon.domain.rate_limit import RateProfile
from polymerhus.recon.domain.types import PodExport


class FakeRegistry:
    def __init__(self):
        self.set_run_status_calls = []
        self.upsert_job_calls = []
        self.run_stats = {}

    def create_run(self, run_id, project_id):
        pass

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append((phase, job, status))

    def set_run_stats(self, run_id, stats):
        self.run_stats.update(stats)


def _profile(target_key: str = "acme.com") -> RateProfile:
    return RateProfile.conservative(
        target_key, [target_key], rate_limit_safety_budget(), "fixture",
    )


class _FakeOrchestrator:
    """A gateway that degrades (None) and a rate turn that returns the fixture
    profile - no LLM, no Kali, deterministic."""

    def __init__(self, profile: RateProfile):
        self._profile = profile

    async def run_gateway(self, *, project_id):
        return None

    async def run_rate_limit(self, **kwargs):
        return self._profile


async def _run(registry, profile, **kwargs):
    return await pipeline.run_pipeline(
        "proj-1",
        run_id="run-1",
        job_subset=["httpx"],
        registry=registry,
        load_settings=lambda project_id: {"target_seed": "acme.com"},
        read_assets=lambda *args, **kw: [],
        run_job=lambda *args, **kw: [PodExport(input_asset={}, verdict="success")],
        orchestrator_factory=lambda run_id: _FakeOrchestrator(profile),
        **kwargs,
    )


def test_the_posture_file_matches_the_run_stats(tmp_path):
    registry = FakeRegistry()
    profile = _profile()
    store = RateLimitPostureStore(root=tmp_path)

    asyncio.run(
        _run(
            registry, profile,
            write_posture=lambda pid, prof, rid: store.write(pid, prof, rid),
        )
    )

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert stored["profile"] == registry.run_stats["rate_limit"]


def test_a_failed_posture_write_fails_the_run_before_any_phase(tmp_path):
    registry = FakeRegistry()

    def _boom(project_id, profile, run_id):
        raise OSError("disk full")

    asyncio.run(_run(registry, _profile(), write_posture=_boom))

    assert registry.set_run_status_calls[-1] == ("run-1", "failed", None)
    assert registry.upsert_job_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/recon/test_rate_limit_posture_write.py -q`
Expected: FAIL with `TypeError: run_pipeline() got an unexpected keyword argument 'write_posture'`

- [ ] **Step 3: Write the minimal implementation**

Aggiungi l'helper di modulo accanto a `_default_orchestrator_factory`:

```python
def _default_write_posture(project_id: str, profile, run_id: str) -> None:
    """The pipeline's ONE posture write (#238 follow-up).

    A module-level seam so the unit tier can patch one name (the autouse
    fixture below) instead of every `run_pipeline` call site.
    """
    from polymerhus.app.rate_limit.store import RateLimitPostureStore  # noqa: PLC0415

    RateLimitPostureStore().write(project_id, profile, run_id)
```

Estendi la firma di `run_pipeline` con il parametro keyword-only:

```python
    prepare_inputs=None,
    fetch_capabilities=None,
    write_posture=None,
) -> None:
```

Subito dopo `await _persist_rate_profile(registry, run_id, rate_profile)`:

```python
        # #238 follow-up: project the SAME validated profile into the
        # cross-phase project bucket. Postgres first (just above), then the
        # file: a file naming a run whose stats never carried the profile
        # would be an unverifiable claim.
        try:
            await asyncio.to_thread(
                write_posture or _default_write_posture,
                project_id, rate_profile, run_id,
            )
        except Exception:
            logger.error(
                "run %s could not project the rate posture into the project "
                "bucket; failing the run before any phase runs", run_id,
                exc_info=True,
            )
            await asyncio.to_thread(registry.set_run_status, run_id, "failed")
            return
```

Aggiungi la fixture autouse in `tests/recon/conftest.py` (il file non esiste
ancora: crealo) così che nessun test esistente scriva nel vero `data/`:

```python
# tests/recon/conftest.py
import pytest

from polymerhus.recon.control import pipeline


@pytest.fixture(autouse=True)
def _no_real_posture_writes(monkeypatch):
    """The default posture seam is a no-op in the unit tier; the write path is
    exercised explicitly by tests/recon/test_rate_limit_posture_write.py."""
    monkeypatch.setattr(
        pipeline, "_default_write_posture",
        lambda project_id, profile, run_id: None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/recon/test_rate_limit_posture_write.py tests/recon/test_pipeline.py tests/recon/test_rate_limit_pipeline.py -q`
Expected: PASS (nessuna regressione)

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/recon/control/pipeline.py tests/recon/conftest.py \
  tests/recon/test_rate_limit_posture_write.py
git commit -m "feat(recon): project the rate posture into the project bucket"
```

---

### Task 5: Binding in hunting e allineamento della documentazione

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/agents.py` (`runner_react_tools`)
- Modify: `src/polymerhus/attack/hunting/hunter_tools.py` (`build_hunter_tools`)
- Modify: `docs/design/rate-limit-job-admission-operations.md`
- Modify: `src/polymerhus/app/CONTEXT.md`
- Test: `tests/attack/test_hunting_posture_tool_binding.py`

**Interfaces:**
- Consumes: `build_rate_limit_posture_tool`
- Produces: `rate_limit_posture` presente nei tool del Pod Runner e dell'Hunter, assente in quelli del Triager

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_hunting_posture_tool_binding.py
"""The posture tool is bound to the two agents that execute on Kali (Pod
Runner, Hunter) and NEVER to the Triager, which never touches the target."""
from langchain_core.tools import BaseTool
from types import SimpleNamespace

from polymerhus.attack.hunting import hunter_tools
from polymerhus.attack.hunting.pod import agents


def _stub_tool() -> BaseTool:
    class _Stub(BaseTool):
        name: str = "rate_limit_posture"
        description: str = "stub"

        def _run(self, *args, **kwargs):  # pragma: no cover - binding only
            return ""

    return _Stub()


def _names(tools) -> set[str]:
    return {getattr(tool, "name", "") for tool in tools}


def test_runner_binds_the_posture_tool(monkeypatch):
    monkeypatch.setattr(agents, "_posture_tool", lambda project_id: _stub_tool())

    tools = agents.runner_react_tools(
        exec_fn=None, memory_store=SimpleNamespace(), spec_id="s-1",
        log=None, variant_ref="", project_id="proj-1",
    )

    assert "rate_limit_posture" in _names(tools)


def test_triager_never_binds_the_posture_tool():
    tools = agents.triager_react_tools(
        memory_store=SimpleNamespace(), spec_id="s-1",
    )

    assert "rate_limit_posture" not in _names(tools)


def test_hunter_binds_the_posture_tool(monkeypatch):
    monkeypatch.setattr(hunter_tools, "_posture_tool", lambda project_id: _stub_tool())

    tools = hunter_tools.build_hunter_tools(project_id="proj-1")

    assert "rate_limit_posture" in _names(tools)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/attack/test_hunting_posture_tool_binding.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute '_posture_tool'` oppure `rate_limit_posture` assente dai nomi

- [ ] **Step 3: Write the minimal implementation**

In `src/polymerhus/attack/hunting/pod/agents.py`, accanto a `_graph_view_tools`:

```python
def _posture_tool(project_id: str):
    """The read-only rate-limit posture tool (#238 follow-up). ADVISORY: the
    hunter reads the known limit; nothing here throttles its traffic. Bound only
    to the roles that execute on Kali (Runner, Hunter) - never the Triager."""
    from polymerhus.app.rate_limit.tool import (  # noqa: PLC0415
        build_rate_limit_posture_tool,
    )

    return build_rate_limit_posture_tool(project_id or None)
```

In `runner_react_tools`, dopo `tools += _graph_view_tools(graph_view_fn)`:

```python
    tools.append(_posture_tool(project_id))
```

In `src/polymerhus/attack/hunting/hunter_tools.py`, accanto a `build_hunter_tools`:

```python
def _posture_tool(project_id: str):
    """The read-only rate-limit posture tool (#238 follow-up), advisory only."""
    from polymerhus.app.rate_limit.tool import (  # noqa: PLC0415
        build_rate_limit_posture_tool,
    )

    return build_rate_limit_posture_tool(project_id or None)
```

In `build_hunter_tools`, aggiungi in coda alla lista restituita:

```python
        _posture_tool(project_id),
```

Lo sviluppo non si ferma qui: aggiorna anche
`docs/design/rate-limit-job-admission-operations.md` con una sezione "Seconda
superficie di persistenza" che dichiari:

- `data/<project_id>/rate-limit/<target_key>.yaml` è la postura **corrente** per
  progetto e target, leggibile da tutte le fasi;
- l'envelope è `advisory: true`: il limite è **noto**, non **imposto** — il
  traffico di hunting resta non governato (decisione dell'operatore);
- la precedenza in caso di divergenza: il file non sostituisce
  `recon_runs.stats`, che resta il registro per-run; e una misura più vecchia
  non sovrascrive una più nuova.

Aggiorna infine `src/polymerhus/app/CONTEXT.md` con il nuovo modulo
`app/rate_limit` e la sua ownership del bucket.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/attack/test_hunting_posture_tool_binding.py -q`
Expected: PASS (3 passed)

Run (guardia di regressione sui consumatori esistenti):
`python -m pytest tests/attack tests/app tests/recon -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/attack/hunting \
  docs/design/rate-limit-job-admission-operations.md \
  src/polymerhus/app/CONTEXT.md \
  tests/attack/test_hunting_posture_tool_binding.py
git commit -m "feat(hunting): bind the advisory rate-limit posture tool"
```

---

## Self-Review

**Spec coverage:**

| Sezione della spec | Task |
|---|---|
| §5 layout su disco | Task 1 |
| §6 contratto del file | Task 1 |
| §7 store | Task 1, Task 2 |
| §8 tool | Task 3 |
| §9 percorso di scrittura | Task 4 |
| §10 invarianti di coesistenza | Task 4 (test di non-divergenza) |
| §11 integrazione hunting | Task 5 |
| §12 errori e semantiche | Task 1, 2, 3 |
| §13 testing | ogni task |
| §15 documentazione | Task 5 |

Nessuna sezione della spec è lasciata senza task.

**Placeholder scan:** nessun "TBD"/"TODO". I punti che dipendono da dettagli del
repo sono ancorati al precedente reale: Task 3 implementa il tool come
`BaseTool` (la forma che il test esercita con `invoke` e `args_schema`), Task 4
modella i fake su `tests/recon/test_pipeline.py` e ne cita la forma.

**Type consistency:** `RateLimitPostureStore.write/read/list_targets/resolve`,
`PostureRecord(target_key, profile, source_run_id, fresh)`,
`host_matches(host, patterns)`,
`build_rate_limit_posture_tool(project_id, store=None)` e
`run_pipeline(..., write_posture=None)` compaiono con la stessa firma in tutti i
task che li usano.
