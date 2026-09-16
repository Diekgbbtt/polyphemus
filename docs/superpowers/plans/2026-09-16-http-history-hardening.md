# HTTP-History Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere la filiera HTTP-history (#196) raggiungibile in una caccia reale, correggere l'unico replay silenziosamente sbagliato, togliere i falsi positivi generati dalle difese WAF, e chiudere i buchi di espressivita e di confine emersi dall'analisi.

**Architecture:** Nessuna modifica al modello `http-artifact/v1` e nessuna migrazione distruttiva. Si interviene su (a) i seam applicativi che oggi non collegano i tool dell'agente ne il replay del pod, (b) due guardie fail-closed nel servizio Kali, (c) due indici SQLite e un `ANALYZE`, (d) la classificazione degli esiti nel pod, (e) la proiezione sanificata, (f) tre descrizioni di tool.

**Tech Stack:** Python 3.12, pytest (`.venv`), SQLite 3.45 (WAL, FTS5, JSON1), pydantic v2, LangGraph + `langchain-mcp-adapters`, FastMCP.

**Spec:** `docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md` e `docs/design/http-proxy-history-operations.md`. La lista dei difetti risolti e nella sezione *Contesto* qui sotto: nessun altro documento li contiene.

## Global Constraints

- `tests/kali` (92 test) deve restare verde dopo ogni task.
- Nessuna nuova dipendenza: solo stdlib, pydantic, pytest e cio che e gia nel venv.
- `schema_version` resta `http-artifact/v1`. Nessuna modifica al formato di `record_json`.
- Nessuna migrazione distruttiva: gli indici nuovi si creano con `CREATE INDEX IF NOT EXISTS` dentro `_SCHEMA`, quindi si applicano lazy a ogni file di progetto alla prima apertura.
- `payload_vector_space` resta un dict aperto (#191): nessuna validazione nuova in INIT.
- La cattura resta fail-open; lookup e replay restano fail-closed.
- Nessun raw secret (authorization, cookie, body) attraversa le viste model-facing, i log o Langfuse.
- Convenzione di lavoro: branch `feat/http-history-hardening`, creato con la skill `superpowers:using-git-worktrees`.

## Contesto: i difetti che il piano risolve

P0 - filiera non raggiungibile: `build_hunter_tools(...)` e chiamato senza `http_search_fn`/`http_get_fn` (`attack/hunting/hunting_agent.py`), e il pod di produzione `arun_pod` non ha alcun percorso di replay: `request_ref` e risolto solo da `HuntingHttpPod` (pod deterministico, usato dai test e dal gate E2E). In produzione uno spec con `request_ref` non puo essere eseguito.

P0 - replay silenziosamente sbagliato: se la richiesta registrata dichiara un body non salvato (`capture_state="omitted"`), `service.replay` produce `plan.body = b""` con l'header `content-length` originale ancora presente, e si dichiara `baseline`.

P0 - falsi positivi da difese: `hunting_pod._allowed` mappa `4xx -> denied` e `2xx -> allowed`, quindi un `429`, un `403` di WAF o una challenge-page (`200`) possono far scattare la regola "baseline negata, mutazione ammessa" -> `symptom-confirmed` su una vulnerabilita inesistente.

P1 - query 1.800-3.900x piu lente: gli indici `attributes_text`/`attributes_numeric` non hanno `artifact_id` in coda, quindi la sottoquery correlata non risolve il legame dentro l'indice. `ANALYZE` non viene mai eseguito.

P2 - espressivita: nessuna negazione nei filtri ne negli override, quindi il gruppo di controllo ("la stessa richiesta senza quell'header") non e producibile.

P3 - confine: `sanitize_artifact` restituisce `capture_context.model_dump()` in blocco (quindi `source_ip` esce) e la redazione dei valori dipende da una regex sui nomi. Un replay manuale via `exec` perde la lineage.

P5 - contratto: la forma del ritorno non e nello schema inviato al modello, `get_http_artifact` non dice quando usarlo, e `request_ref` vince su `method`/`path` in silenzio.

Fuori scope (piano separato): pool di IP per lease (SNAT al posto del MASQUERADE), rate limiter nel capture plane, policy per-host di splice TLS, separazione dell'egress fra scanning e hunting, `stream_large_bodies`. La decisione di packaging (mantenere JSON+EAV com'e, con eventuale proiezione pigra) e una ADR, non un piano.

## File Structure

| file | responsabilita | azione |
|---|---|---|
| `kali/http_history/service.py` | guard sul body, lineage in `execute`, LRU della cache store | Modify |
| `kali/http_history/store.py` | indici covering, `optimize()`, operatore `absent`, `busy_timeout` | Modify |
| `kali/http_history/replay.py` | override `remove_header`/`remove_headers` | Modify |
| `kali/http_history/sanitize.py` | proiezione esplicita del capture context | Modify |
| `kali/mcp_server.py` | mappatura errori nuovi; parametri lineage | Modify |
| `src/polymerhus/app/clients/kali_http_history.py` | client app-side search/get/replay (sync) | Create |
| `src/polymerhus/attack/hunting/hunter_tools.py` | descrizioni dei tre verbi | Modify |
| `src/polymerhus/attack/hunting/hunting_pod.py` | difese/rate limit; nota di precedenza | Modify |
| `src/polymerhus/attack/hunting/pod/agents.py` | tool `replay` nel runner di produzione | Modify |
| `src/polymerhus/attack/hunting/pod/prompts.py` | una riga sul percorso `request_ref` | Modify |
| `src/polymerhus/attack/hunting/runtime.py` | binding dei seam nei due builder | Modify |
| `src/polymerhus/attack/hunting/hunting_agent.py` | pass-through dei due callable | Modify |

---

### Task 1: Guard fail-closed sul body mancante

**Files:**
- Modify: `kali/http_history/service.py`
- Modify: `kali/mcp_server.py`
- Test: `tests/kali/test_http_history_service.py`

**Interfaces:**
- Produces: `BodyUnavailableError(ValueError)` in `kali.http_history.service`, sollevata da `HttpHistoryService.replay(project_id, artifact_id, overrides, capture_context=None, *, sender=None)` quando la richiesta del baseline dichiara un body che non e nello store.
- Produces: al confine MCP, un errore con codice `"body_unavailable"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_service.py (append)
from kali.http_history.service import BodyUnavailableError


def test_replay_refuses_a_baseline_whose_body_is_missing(tmp_path):
    flow = FakeFlow(
        request=FakeMessage(
            method="POST", url="https://target.example/upload", content=b"0123456789"
        ),
        response=FakeMessage(status=200, reason="OK"),
    )
    artifact, bodies = normalize_flow(
        flow,
        project_id="proj-1",
        capture_context=CaptureContext(exec_id="e1"),
        artifact_id="http_01J0000000000000000000000A",
        max_body_bytes=1,
    )
    assert artifact.request.capture_state == "omitted"
    assert bodies == {}
    HttpHistoryStore(tmp_path, "proj-1").record(artifact, bodies)

    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    with pytest.raises(BodyUnavailableError) as excinfo:
        service.replay("proj-1", artifact.artifact_id, {}, sender=_fake_sender(store))
    assert "omitted" in str(excinfo.value)


def test_replay_still_accepts_a_bodyless_baseline(tmp_path):
    _seed(tmp_path)
    service = _service(tmp_path)
    store = HttpHistoryStore(tmp_path, "proj-1")
    result = service.replay(
        "proj-1", "http_01J0000000000000000000000A", {}, sender=_fake_sender(store)
    )
    assert result["replay_kind"] == "baseline"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_service.py -q -p no:cacheprovider`
Expected: FAIL con `ImportError: cannot import name 'BodyUnavailableError'`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/service.py, accanto a NotFoundError
class BodyUnavailableError(ValueError):
    """The recorded request declares a body whose bytes are not in the store."""
```

```python
# kali/http_history/service.py, dentro HttpHistoryService.replay, subito dopo
# il controllo `if baseline is None: raise NotFoundError(...)`
        raw_body = store.get_body(baseline.request.body_ref)
        if baseline.request.body_size and raw_body is None:
            raise BodyUnavailableError(
                f"replay refused for {artifact_id!r}: the recorded request declares "
                f"a {baseline.request.body_size}-byte body but the bytes are "
                f"unavailable (capture_state="
                f"{baseline.request.capture_state!r}); replaying it would send a "
                "request with no body. Declare an explicit `body` override to send "
                "a bodyless variant on purpose."
            )
```

La riga gia presente `raw_body = store.get_body(baseline.request.body_ref)` piu sotto va rimossa, perche il valore e gia calcolato sopra.

```python
# kali/mcp_server.py, in _error_payload
    from kali.http_history.service import BodyUnavailableError, NotFoundError

    if isinstance(exc, NotFoundError):
        return {"error": "not_found", "detail": str(exc)}
    if isinstance(exc, BodyUnavailableError):
        return {"error": "body_unavailable", "detail": str(exc)}
    return {"error": "invalid_request", "detail": str(exc)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS, 94 passed

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/service.py kali/mcp_server.py tests/kali/test_http_history_service.py
git commit -m "fix(http-history): fail closed when a replay baseline has no stored body"
```

---

### Task 2: Indici covering e ANALYZE

**Files:**
- Modify: `kali/http_history/store.py`
- Test: `tests/kali/test_http_history_store.py`

**Interfaces:**
- Produces: `HttpHistoryStore.optimize() -> None` che esegue `ANALYZE`.
- Produces: `attributes_text_cov` e `attributes_numeric_cov` con `artifact_id` in coda; i due indici non covering vengono rimossi in `_migrate`.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_store.py (append)
from tests.kali.test_http_history_search import _seed


def test_attribute_indexes_are_covering(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    sql = {
        row["name"]: (row["sql"] or "")
        for row in store._conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index'"
        )
    }
    assert "artifact_id" in sql["attributes_text_cov"]
    assert "artifact_id" in sql["attributes_numeric_cov"]
    assert "attributes_text" not in sql, "the non-covering index must be dropped"
    assert "attributes_numeric" not in sql


def test_optimize_runs_analyze(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    store.optimize()
    assert store._conn.execute("SELECT count(*) FROM sqlite_stat1").fetchone()[0] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_store.py -q -p no:cacheprovider`
Expected: FAIL con `KeyError: 'attributes_text_cov'`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/store.py, in _SCHEMA: sostituire le due CREATE INDEX
# degli attributi con queste tre
CREATE INDEX IF NOT EXISTS attributes_artifact ON attributes (artifact_id);
CREATE INDEX IF NOT EXISTS attributes_text_cov
    ON attributes (side, namespace, key, text_value, artifact_id);
CREATE INDEX IF NOT EXISTS attributes_numeric_cov
    ON attributes (side, namespace, key, numeric_value, artifact_id);
```

```python
# kali/http_history/store.py, dentro _migrate(), dopo executescript(_SCHEMA)
            # hardening #196: i due indici non covering restano su file
            # esistenti finche non li si rimuove; il rimpiazzo covering e gia
            # creato da _SCHEMA. DROP IF EXISTS e un no-op sui file nuovi.
            self._conn.execute("DROP INDEX IF EXISTS attributes_text")
            self._conn.execute("DROP INDEX IF EXISTS attributes_numeric")
```

```python
# kali/http_history/store.py, accanto a close()
    def optimize(self) -> None:
        """Refresh the query planner statistics (SQLite ANALYZE)."""
        with self._lock:
            self._conn.execute("ANALYZE")
```

```python
# kali/http_history/store.py, subito dopo sqlite3.connect(...) nel costruttore
        # Due processi scrivono lo stesso file di progetto (l'addon registra,
        # il MCP purga/fa retention): senza busy_timeout il secondo incassa un
        # "database is locked" immediato invece di attendere il writer.
        self._conn.execute("PRAGMA busy_timeout=5000")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS, 96 passed

- [ ] **Step 5: Verify the plan uses the covering index**

```bash
.venv/bin/python - <<'PY'
import tempfile
from pathlib import Path
from kali.http_history.store import HttpHistoryStore
store = HttpHistoryStore(Path(tempfile.mkdtemp()), "p")
sql = ("SELECT f.artifact_id FROM flows f WHERE f.project_id='p' "
       "AND EXISTS (SELECT 1 FROM attributes a WHERE a.artifact_id=f.artifact_id "
       "AND a.side='response' AND a.namespace='core' AND a.key='status' "
       "AND a.numeric_value=200) ORDER BY f.created_at, f.artifact_id LIMIT 51")
print("\n".join(r[3] for r in store._conn.execute("EXPLAIN QUERY PLAN " + sql)))
PY
```

Expected: la riga contiene `SEARCH a USING COVERING INDEX attributes_numeric_cov`.

- [ ] **Step 6: Commit**

```bash
git add kali/http_history/store.py tests/kali/test_http_history_store.py
git commit -m "perf(http-history): covering attribute indexes, ANALYZE and busy_timeout"
```

---

### Task 3: Operatore absent nei filtri

**Files:**
- Modify: `kali/http_history/store.py`
- Test: `tests/kali/test_http_history_search.py`

**Interfaces:**
- Produces: `op="absent"` accettato da `_filter_sql`. Semantica: la transazione non ha alcuna riga con quella `(side, namespace, key)`. Nessun `value` richiesto.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_search.py (append)
def test_absent_operator_matches_transactions_without_the_attribute(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with_x = _artifact("http_01J0000000000000000000000A", created_at=1000.0,
                       req_headers=[["x-forwarded-for", "127.0.0.1"]])
    without_x = _artifact("http_01J0000000000000000000001A", created_at=1001.0,
                          req_headers=[["content-type", "application/json"]])
    for artifact, bodies in (with_x, without_x):
        store.record(artifact, bodies=bodies)

    page = store.search([
        {"side": "request", "namespace": "header", "key": "x-forwarded-for",
         "op": "absent"},
    ])
    assert [a.artifact_id for a in page.artifacts] == [
        "http_01J0000000000000000000001A"
    ]


def test_absent_does_not_require_a_value(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search([
        {"side": "request", "namespace": "header", "key": "x-not-sent",
         "op": "absent"},
    ])
    assert len(page.artifacts) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_search.py -q -p no:cacheprovider`
Expected: FAIL con `ValueError: unknown op 'absent'`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/store.py
ALLOWED_OPS = frozenset({"eq", "contains", "prefix", "gte", "lte", "absent"})
```

```python
# kali/http_history/store.py, dentro _filter_sql: il ramo `absent` precede la
# costruzione della clausola EXISTS e non richiede `value`
            if op == "absent":
                clauses.append(
                    "NOT EXISTS (SELECT 1 FROM attributes a "
                    "WHERE a.artifact_id = f.artifact_id "
                    "AND a.side = ? AND a.namespace = ? AND a.key = ?)"
                )
                params.extend([side, namespace, key])
                continue
            clause, clause_params = _op_sql(op, value)
            clauses.append(
                "EXISTS (SELECT 1 FROM attributes a WHERE a.artifact_id = f.artifact_id "
                "AND a.side = ? AND a.namespace = ? AND a.key = ? AND " + clause + ")"
            )
            params.extend([side, namespace, key, *clause_params])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS, 98 passed

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/store.py tests/kali/test_http_history_search.py
git commit -m "feat(http-history): add the absent filter operator for control-group queries"
```

---

### Task 4: remove_header negli override di replay

**Files:**
- Modify: `kali/http_history/replay.py`
- Test: `tests/kali/test_http_history_replay.py`

**Interfaces:**
- Produces: chiavi `remove_header` / `remove_headers` in `ALLOWED_OVERRIDES`, valore lista di nomi; rimozione case-insensitive, applicata dopo gli override di header e cookie.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_replay.py (append)
def test_remove_header_drops_the_named_headers():
    plan = apply_overrides(_request(), b"", {"remove_headers": ["authorization", "X-Keep"]})
    names = [name.lower() for name, _ in plan.headers]
    assert "authorization" not in names
    assert "x-keep" not in names
    assert "content-type" in names
    assert plan.replay_kind == "mutated"


def test_remove_header_runs_after_setting_headers():
    plan = apply_overrides(
        _request(), b"", {"headers": {"x-new": "1"}, "remove_header": ["x-new"]}
    )
    assert [name.lower() for name, _ in plan.headers].count("x-new") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_replay.py -q -p no:cacheprovider`
Expected: FAIL con `ReplayOverrideError: unsupported replay override(s): ['remove_headers']`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/replay.py
ALLOWED_OVERRIDES = frozenset(
    {
        "method", "url", "path", "query", "header", "headers",
        "remove_header", "remove_headers",
        "cookie", "cookies", "body", "form", "json",
    }
)
```

```python
# kali/http_history/replay.py, dentro apply_overrides: dopo il blocco dei cookie
# override e prima di `new_body = body or b""`
    removals = [
        *(overrides.get("remove_header") or []),
        *(overrides.get("remove_headers") or []),
    ]
    if removals:
        lowered = {str(name).lower() for name in removals}
        headers = [(k, v) for k, v in headers if k.lower() not in lowered]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS, 100 passed

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/replay.py tests/kali/test_http_history_replay.py
git commit -m "feat(http-history): allow header removal in replay overrides"
```

---

### Task 5: Difese e rate limit non sono un esito applicativo

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunting_pod.py`
- Test: `tests/attack/test_hunting_pod.py`

**Interfaces:**
- Produces: `DEFENCE_STATUSES = frozenset({429, 503})`, `_defence_signal(status) -> str | None` (`"rate-limited"`, `"server-error"`, `None`), e `_allowed(status)` che torna `None` per qualunque status classificato come difesa.
- Produces: la voce `interpretations` di ogni replay porta anche `"defence": <signal|None>`; una risposta classificata come difesa non puo produrre `symptom-confirmed`.

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_hunting_pod.py (append)
from polymerhus.attack.hunting.hunting_pod import _allowed, _defence_signal


def test_waf_and_rate_limit_are_not_application_verdicts():
    assert _allowed(429) is None
    assert _allowed(503) is None
    assert _allowed(500) is None
    assert _allowed(403) is False
    assert _allowed(200) is True
    assert _defence_signal(429) == "rate-limited"
    assert _defence_signal(500) == "server-error"
    assert _defence_signal(403) is None


def test_rate_limited_mutation_is_not_a_confirmed_symptom():
    def replay(project_id, artifact_id, overrides):
        return {"status": 429 if overrides else 403}

    spec = {"d4_typed_base": {
        "target_identity": {"url": "http://target.example/"},
        "payload_vector_space": {
            "request_ref": "http_01J0000000000000000000000A",
            "mutations": [{"location": "query", "name": "q", "values": ["x"]}],
        }}}
    pod = HuntingHttpPod(project_id="proj-1", replay_fn=replay,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    out = pod(spec)
    assert out["verdict"] == "unsuccessful"
    assert out["evidence"]["terminal_reason"] != "symptom-confirmed"
    assert any(item.get("defence") == "rate-limited"
               for item in out["evidence"]["interpretations"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/attack/test_hunting_pod.py -q -p no:cacheprovider`
Expected: FAIL: `_allowed(429)` e `False` e il verdetto e `successful`

- [ ] **Step 3: Write minimal implementation**

```python
# src/polymerhus/attack/hunting/hunting_pod.py, accanto a _allowed
DEFENCE_STATUSES = frozenset({429, 503})


def _defence_signal(status) -> str | None:
    """A defence that is not an application verdict: rate limiting or a
    server-side block. Never `denied`, never `allowed` - inconclusive."""
    if not isinstance(status, int):
        return None
    if status in DEFENCE_STATUSES:
        return "rate-limited"
    if 500 <= status < 600:
        return "server-error"
    return None


def _allowed(status) -> bool | None:
    """True = request allowed (2xx/3xx), False = denied (4xx), None = unknown."""
    if not isinstance(status, int):
        return None
    if _defence_signal(status) is not None:
        return None
    if 200 <= status < 400:
        return True
    if 400 <= status < 500:
        return False
    return None
```

```python
# src/polymerhus/attack/hunting/hunting_pod.py, dentro _run_request_ref, nel
# ciclo `for override in mutations:` sostituendo l'append esistente
            defence = _defence_signal(status)
            interpretations.append(
                {"vector": f"request_ref {ref}", "override": override,
                 "status": status, "defence": defence}
            )
            if defence is not None:
                definitive = False
                continue
```

La condizione del sintomo resta `baseline_allowed is False and _allowed(status) is True`: ora non puo scattare su una difesa, perche il ciclo la salta prima.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/attack -q -p no:cacheprovider`
Expected: PASS (i test preesistenti del pod non usano 429/503/5xx come "allowed")

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/attack/hunting/hunting_pod.py tests/attack/test_hunting_pod.py
git commit -m "fix(hunting-pod): rate limits and WAF blocks are not application verdicts"
```

---

### Task 6: Il contratto dei tool dove il modello lo legge

**Files:**
- Modify: `src/polymerhus/attack/hunting/hunter_tools.py`
- Modify: `src/polymerhus/attack/hunting/hunting_pod.py`
- Test: `tests/attack/test_http_history_tools.py`

**Interfaces:**
- Produces: descrizioni aggiornate per `search_http_history`, `get_http_artifact` ed `exec`; nota di precedenza del `request_ref` nelle `interpretations` del pod.

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_http_history_tools.py (append)
def test_descriptions_teach_the_chain():
    tools = {t.name: t for t in build_hunter_tools()}
    assert "candidate" in tools["search_http_history"].description
    assert "capture_state" in tools["get_http_artifact"].description
    assert "lineage" in tools["exec"].description


def test_request_ref_precedence_is_reported():
    spec = {"d4_typed_base": {
        "target_identity": {"url": "http://target.example/"},
        "payload_vector_space": {
            "request_ref": "http_01J0000000000000000000000A",
            "method": "GET", "path": "/inline",
            "mutations": [{"location": "query", "name": "q", "values": ["x"]}],
        }}}
    pod = HuntingHttpPod(project_id="proj-1",
                         replay_fn=lambda p, a, o: {"status": 200 if o else 403},
                         transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    out = pod(spec)
    assert any("ignored" in str(item) for item in out["evidence"]["interpretations"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/attack/test_http_history_tools.py -q -p no:cacheprovider`
Expected: FAIL: le tre stringhe non ci sono e nessuna interpretation parla di "ignored"

- [ ] **Step 3: Write minimal implementation**

```python
# src/polymerhus/attack/hunting/hunter_tools.py - description di search
        "Search this project's recorded HTTP request/response history. Filters "
        "are conjunctive: {side, namespace, key, op, value} with side in "
        "request|response|connection|context|timing, namespace in core|header|"
        "cookie|query|form|body|tls, op in eq|contains|prefix|gte|lte|absent "
        "(absent = the transaction does NOT carry that key: use it for the "
        "control group). Returns sanitized summaries: a list of candidates, not "
        "a verification. Use the returned artifact_id as "
        "payload_vector_space.request_ref to replay a baseline."

# description di get
        "Fetch one recorded HTTP transaction by artifact_id from this project. "
        "Use it to inspect a candidate before committing it as a request_ref "
        "(header names are visible here, values of sensitive headers are "
        "redacted) and to check request.body.capture_state: only `captured` is "
        "replayable. The view is sanitized: no body content is returned. "
        "Cross-project ids are not found."

# description di exec
        "Run a terminal command inside the target network namespace. Do NOT "
        "re-create a recorded request by hand here: a hand-written curl loses "
        "the replay lineage (derived_from / replay_kind stay null and the "
        "artifact looks like original traffic). Use the spec's request_ref."
```

```python
# src/polymerhus/attack/hunting/hunting_pod.py, dentro __call__, dopo la riga
# `pvs = ((spec.get("d4_typed_base") or {}).get("payload_vector_space") or {})`
        if isinstance(pvs, dict) and pvs.get("request_ref") and (
            pvs.get("method") or pvs.get("path")
        ):
            self._inline_ignored = True
```

```python
# src/polymerhus/attack/hunting/hunting_pod.py, in _run_request_ref, prima di
# costruire l'envelope di ritorno
        if getattr(self, "_inline_ignored", False):
            interpretations.append(
                "request_ref is present: the inline method/path were ignored"
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/attack -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/attack/hunting/hunter_tools.py src/polymerhus/attack/hunting/hunting_pod.py tests/attack/test_http_history_tools.py
git commit -m "docs(hunting): teach the search/get/replay chain in the tool descriptions"
```

---

### Task 7: Proiezione esplicita del capture context

**Files:**
- Modify: `kali/http_history/sanitize.py`
- Test: `tests/kali/test_http_history_sanitize.py`

**Interfaces:**
- Produces: `sanitize_artifact` espone un `capture_context` costruito campo per campo; `source_ip` non compare piu nell'output.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_sanitize.py (append)
from kali.http_history.models import CaptureContext, HttpArtifact
from kali.http_history.sanitize import sanitize_artifact


def test_capture_context_is_projected_explicitly():
    artifact = HttpArtifact(
        artifact_id="http_01J0000000000000000000000A",
        project_id="proj-1",
        capture_context=CaptureContext(
            exec_id="e1", session_id="s1", source_ip="172.30.0.2"
        ),
    )
    view = sanitize_artifact(artifact)
    assert set(view["capture_context"]) == {
        "session_id", "run_id", "spec_id", "variant_ref", "exec_id",
        "derived_from", "replay_kind",
    }
    assert "172.30.0.2" not in str(view)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_sanitize.py -q -p no:cacheprovider`
Expected: FAIL: `source_ip` e presente nel dict

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/sanitize.py
_EXPOSED_CONTEXT_FIELDS = (
    "session_id", "run_id", "spec_id", "variant_ref", "exec_id",
    "derived_from", "replay_kind",
)


def _context_view(artifact: HttpArtifact) -> dict:
    """Explicit projection: anything not listed here never crosses the
    boundary (`source_ip` is the internal namespace address and stays out)."""
    return {name: getattr(artifact.capture_context, name)
            for name in _EXPOSED_CONTEXT_FIELDS}
```

```python
# kali/http_history/sanitize.py, in sanitize_artifact
        "capture_context": _context_view(artifact),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/sanitize.py tests/kali/test_http_history_sanitize.py
git commit -m "fix(http-history): project the capture context explicitly (source_ip stays inside)"
```

---

### Task 8: Lineage etichettabile su execute_command

**Files:**
- Modify: `kali/mcp_server.py`, `kali/http_history/service.py`
- Test: `tests/kali/test_http_history_service.py`

**Interfaces:**
- Produces: `execute_command(..., derived_from="", replay_kind="")` e `HttpHistoryService.execute(..., derived_from="", replay_kind="")`; i due valori entrano nel `CaptureContext` del lease.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_service.py (append)
from kali.http_history.service import ExecOutcome


def test_execute_can_label_a_manual_replay(tmp_path):
    seen = {}

    class _Lease:
        namespace = "kali-http-0001"

    class _Leases:
        def acquire(self, *, session_id, project_id, context):
            seen["context"] = context
            return _Lease()

        def release(self, lease):
            pass

    service = HttpHistoryService(
        config=HttpHistoryConfig(store_root=str(tmp_path)),
        lease_manager=_Leases(),
        runner=lambda command, session_id, timeout_s, namespace=None: ExecOutcome(
            stdout="", stderr="", returncode=0, duration_ms=1
        ),
    )
    service.execute(
        "curl -sS http://t/", "s1", project_id="proj-1",
        derived_from="http_01J0000000000000000000000A", replay_kind="mutated",
    )
    assert seen["context"].derived_from == "http_01J0000000000000000000000A"
    assert seen["context"].replay_kind == "mutated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_service.py -q -p no:cacheprovider`
Expected: FAIL con `TypeError: execute() got an unexpected keyword argument 'derived_from'`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/service.py, firma di execute: due parametri in coda
    def execute(
        self,
        command: str,
        session_id: str,
        timeout_s: int = 300,
        project_id: str = "",
        run_id: str = "",
        spec_id: str = "",
        variant_ref: str = "",
        derived_from: str = "",
        replay_kind: str = "",
    ) -> dict:
```

```python
# kali/http_history/service.py, nel CaptureContext costruito per l'acquire
                    context=CaptureContext(
                        session_id=session_id,
                        run_id=run_id,
                        spec_id=spec_id,
                        variant_ref=variant_ref,
                        exec_id=exec_id,
                        derived_from=derived_from or None,
                        replay_kind=replay_kind or None,
                    ),
```

```python
# kali/mcp_server.py: stessa coppia di parametri nella firma pubblica e nella
# chiamata al servizio
def execute_command(
    command: str,
    session_id: str,
    timeout_s: int = 300,
    project_id: str = "",
    run_id: str = "",
    spec_id: str = "",
    variant_ref: str = "",
    derived_from: str = "",
    replay_kind: str = "",
) -> dict:
    ...
        result = _get_service().execute(
            command, session_id, timeout_s, project_id=project_id,
            run_id=run_id, spec_id=spec_id, variant_ref=variant_ref,
            derived_from=derived_from, replay_kind=replay_kind,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/service.py kali/mcp_server.py tests/kali/test_http_history_service.py
git commit -m "feat(http-history): allow a manual replay to carry lineage"
```

---

### Task 9: Client app-side e binding di search/get nell'hunter

**Files:**
- Create: `src/polymerhus/app/clients/kali_http_history.py`
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py`, `src/polymerhus/attack/hunting/runtime.py`
- Test: `tests/attack/test_kali_http_history_client.py`, `tests/attack/test_http_history_wiring.py`

**Interfaces:**
- Produces: `structured_payload(result) -> dict` (puro), `default_http_search_fn(project_id, filters, cursor, limit, text) -> dict`, `default_http_get_fn(project_id, artifact_id, include_body=False) -> dict`, `default_replay_fn(project_id, artifact_id, overrides) -> dict` in `polymerhus.app.clients.kali_http_history`. I primi tre sono **sincroni**, perche i tool li invocano sincronamente.
- Produces: `build_production_hunting_agent(..., http_search_fn=None, http_get_fn=None)` che li passa a `build_hunter_tools`.
- Consumes: `run_coro_blocking` da `polymerhus.recon.control.async_bridge`; il pattern e lo stesso di `recon.domain.pod.default_exec_fn`.

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/test_kali_http_history_client.py
"""Shape extraction for the app-side HTTP-history client (no live MCP)."""
from __future__ import annotations

from polymerhus.app.clients.kali_http_history import structured_payload


def test_structured_payload_reads_the_artifact_dict():
    assert structured_payload({"structured_content": {"summaries": []}}) == {
        "summaries": []
    }


def test_structured_payload_returns_error_on_a_bare_message():
    out = structured_payload("boom")
    assert out["error"] == "unstructured_response"
    assert "boom" in out["detail"]
```

```python
# tests/attack/test_http_history_wiring.py
"""The hunting tools stop degrading when the seams are bound."""
from __future__ import annotations

import json

from polymerhus.attack.hunting.hunter_tools import build_hunter_tools


def test_build_hunter_tools_with_seams_is_not_degraded():
    def search(project_id, filters, cursor, limit, text):
        return {"summaries": [{"artifact_id": "http_A"}]}

    def get(project_id, artifact_id, include_body):
        return {"artifact_id": artifact_id}

    tools = {
        tool.name: tool
        for tool in build_hunter_tools(
            project_id="proj-1", http_search_fn=search, http_get_fn=get,
        )
    }
    out = json.loads(tools["search_http_history"].invoke({}))
    assert out["summaries"][0]["artifact_id"] == "http_A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/attack/test_kali_http_history_client.py tests/attack/test_http_history_wiring.py -q -p no:cacheprovider`
Expected: FAIL: `ModuleNotFoundError: polymerhus.app.clients.kali_http_history`

- [ ] **Step 3: Write minimal implementation**

```python
# src/polymerhus/app/clients/kali_http_history.py
"""App-side SYNC client for the kali HTTP-history tools (#196).

The hunter tools invoke their seams synchronously, so every callable here
bridges to the async MCP client with `run_coro_blocking` - the same pattern
`recon.domain.pod.default_exec_fn` uses for `execute_command`.
"""
from __future__ import annotations

from typing import Any


def structured_payload(result: Any) -> dict:
    """Pure: the tool result carries its dict either bare or under
    `structured_content`. Anything else is an error, never a silent success."""
    structured: Any = result
    if isinstance(structured, dict) and "structured_content" in structured:
        structured = structured["structured_content"]
    else:
        structured = getattr(structured, "structured_content", None) or structured
    if isinstance(structured, dict):
        return structured
    return {"error": "unstructured_response", "detail": str(result)[:400]}


def _call_tool(name: str, args: dict) -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415

    from polymerhus.app.config import config  # noqa: PLC0415
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    async def _run():
        client = MultiServerMCPClient(
            {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
        )
        tools = await client.get_tools()
        tool = next(tool for tool in tools if tool.name == name)
        return await tool.ainvoke(
            {"type": "tool_call", "name": name, "id": name, "args": args}
        )

    try:
        return structured_payload(run_coro_blocking(_run()))
    except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
        return {"error": "http_history_failed",
                "detail": f"{type(exc).__name__}: {exc}"}


def default_http_search_fn(project_id, filters, cursor, limit, text) -> dict:
    return _call_tool("search_http_history", {
        "project_id": project_id, "filters": filters or [], "cursor": cursor,
        "limit": limit, "text": text,
    })


def default_http_get_fn(project_id, artifact_id, include_body=False) -> dict:
    return _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": artifact_id,
    })


def default_replay_fn(project_id, artifact_id, overrides) -> dict:
    """The pod's replay seam: read the baseline status, or replay with the
    overrides and read the new artifact's status back."""
    if not overrides:
        view = _call_tool("get_http_artifact", {
            "project_id": project_id, "artifact_id": artifact_id})
        return {"status": (view.get("response") or {}).get("status")}
    result = _call_tool("replay_http_request", {
        "project_id": project_id, "artifact_id": artifact_id, "overrides": overrides,
    })
    if result.get("error"):
        return {"status": None, "error": result}
    view = _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": result.get("artifact_id")})
    return {"status": (view.get("response") or {}).get("status"),
            "artifact_id": result.get("artifact_id")}
```

```python
# src/polymerhus/attack/hunting/hunting_agent.py: aggiungere i due parametri a
# build_production_hunting_agent e passarli dove chiama build_hunter_tools
def build_production_hunting_agent(*, store, run_id, project_id, memory_store=None,
                                   graph_view_fn=None, exec_fn=None,
                                   http_search_fn=None, http_get_fn=None):
    ...
        tools = build_hunter_tools(
            store=memory_store, project_id=project_id, hunt_store=hunt_store,
            graph_view_fn=graph_view_fn, kb_fn=kb_fn, exec_fn=exec_fn,
            http_search_fn=http_search_fn, http_get_fn=http_get_fn,
        )
```

```python
# src/polymerhus/attack/hunting/runtime.py, in _default_hunter_builder
    from polymerhus.app.clients.kali_http_history import (  # noqa: PLC0415
        default_http_get_fn, default_http_search_fn,
    )

    return build_production_hunting_agent(
        store=hunt_store, run_id=run_id, project_id=project_id,
        memory_store=hunter_store,
        graph_view_fn=ReadOnlyGraphView(project_id).read,
        exec_fn=default_exec_fn,
        http_search_fn=default_http_search_fn,
        http_get_fn=default_http_get_fn,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/attack/test_kali_http_history_client.py tests/attack/test_http_history_wiring.py tests/attack/test_http_history_tools.py -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Live verification (stack attivo)**

```bash
KALI_MCP_URL=http://localhost:8000/mcp .venv/bin/python -c "from polymerhus.app.clients.kali_http_history import default_http_search_fn as s; print(s('e2e-143615e044', [], None, 1, None)['summaries'][0]['artifact_id'])"
```

Expected: un `http_...` reale, non `http_history_unavailable`.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/app/clients/kali_http_history.py src/polymerhus/attack/hunting/hunting_agent.py src/polymerhus/attack/hunting/runtime.py tests/attack/test_kali_http_history_client.py tests/attack/test_http_history_wiring.py
git commit -m "feat(hunting): bind the http-history search/get seams in production"
```

---

### Task 10: Il pod di produzione sa replayare un request_ref

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/agents.py`, `pod/prompts.py`, `pod/pod.py`, `attack/hunting/runtime.py`
- Test: `tests/attack/pod/test_replay_tool.py`

**Interfaces:**
- Produces: `runner_react_tools(..., replay_fn=None, project_id="")` aggiunge un tool `replay` con args `{"artifact_id": str, "overrides": dict | None}` che ritorna `{"status": int|null, "artifact_id": str|null}`; il tool e assente quando `replay_fn is None`.
- Consumes: `default_replay_fn` dal Task 9.

Nota di design: questa e la scelta minima che rende raggiungibile il contratto #196 senza riscrivere il pod. L'alternativa (instradare gli spec con `request_ref` a `HuntingHttpPod`) cambia il dispatch e non e richiesta da questo piano.

- [ ] **Step 1: Write the failing test**

```python
# tests/attack/pod/test_replay_tool.py
"""The production runner can execute a spec's request_ref."""
from __future__ import annotations

import json

from polymerhus.attack.hunting.pod.agents import runner_react_tools


def _tools(**kwargs):
    return {
        tool.name: tool
        for tool in runner_react_tools(
            exec_fn=lambda *a, **k: None,
            memory_store=None, spec_id="s", log=None, variant_ref="v0", **kwargs,
        )
    }


def test_replay_tool_is_absent_without_the_seam():
    assert "replay" not in _tools()


def test_replay_tool_returns_the_status_of_the_new_artifact():
    seen = {}

    def replay_fn(project_id, artifact_id, overrides):
        seen["args"] = (project_id, artifact_id, overrides)
        return {"status": 200, "artifact_id": "http_NEW"}

    tools = _tools(replay_fn=replay_fn, project_id="proj-1")
    out = json.loads(tools["replay"].invoke(
        {"artifact_id": "http_OLD", "overrides": {"query": {"q": "x"}}}
    ))
    assert out["status"] == 200
    assert seen["args"] == ("proj-1", "http_OLD", {"query": {"q": "x"}})


def test_replay_tool_reports_a_missing_reference_as_null_status():
    tools = _tools(replay_fn=lambda *a: {"status": None}, project_id="proj-1")
    out = json.loads(tools["replay"].invoke({"artifact_id": "http_MISSING"}))
    assert out["status"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/attack/pod/test_replay_tool.py -q -p no:cacheprovider`
Expected: FAIL con `TypeError: runner_react_tools() got an unexpected keyword argument 'replay_fn'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/polymerhus/attack/hunting/pod/agents.py, firma estesa di runner_react_tools
def runner_react_tools(exec_fn, memory_store, spec_id, log, variant_ref, *,
                       kb_fn=None, kb_lookup=None, graph_view_fn=None,
                       browser=None, replay_fn=None, project_id=""):
    ...
    if replay_fn is not None:
        @tool
        def replay(artifact_id: str, overrides: dict | None = None) -> str:
            """Replay a recorded request by artifact_id applying the declared
            deterministic overrides, and return the new artifact's status. Use
            this when the spec carries payload_vector_space.request_ref instead
            of authoring a curl by hand."""
            return json.dumps(replay_fn(project_id, artifact_id, overrides or {}))

        tools.append(replay)
    return tools
```

```python
# src/polymerhus/attack/hunting/pod/prompts.py, nel testo dello stretch P0
# (feasibility) aggiungere una riga:
#   "If the spec carries `payload_vector_space.request_ref`, do not author a
#    curl: call the `replay` tool with the declared mutations and read the
#    status it returns."
```

```python
# src/polymerhus/attack/hunting/pod/pod.py: propagare un parametro opzionale
# `replay_fn=None` da arun_pod fino a runner_react_tools (default None, cosi il
# contract tier resta invariato), e passarlo a pod_harness().
# src/polymerhus/attack/hunting/runtime.py, in _default_pod_builder
    from polymerhus.app.clients.kali_http_history import default_replay_fn  # noqa: PLC0415

    return await arun_pod(
        spec, run_id=run_id, memory_store=memory_store,
        project_id=project_id, spec_id=spec_id, browser=browser,
        replay_fn=default_replay_fn,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/attack/pod -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/attack/hunting/pod/agents.py src/polymerhus/attack/hunting/pod/prompts.py src/polymerhus/attack/hunting/pod/pod.py src/polymerhus/attack/hunting/runtime.py tests/attack/pod/test_replay_tool.py
git commit -m "feat(pod): give the production runner a replay tool for request_ref specs"
```

---

### Task 11: Igiene operativa dello store handle

**Files:**
- Modify: `kali/http_history/service.py`
- Test: `tests/kali/test_http_history_service.py`

**Interfaces:**
- Produces: la cache `_stores` e limitata a `_STORE_CACHE_MAX` (default 32), con eviction LRU e `close()` dello store evitto; uno store evitto viene riaperto al bisogno.

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_http_history_service.py (append)
def test_store_cache_is_bounded(tmp_path, monkeypatch):
    from kali.http_history import service as service_module

    monkeypatch.setattr(service_module, "_STORE_CACHE_MAX", 2)
    service = _service(tmp_path)
    for index in range(4):
        service.store(f"proj-{index}")
    assert len(service._stores) <= 2
    assert "proj-0" not in service._stores
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_service.py -q -p no:cacheprovider`
Expected: FAIL con `AttributeError: module ... has no attribute '_STORE_CACHE_MAX'`

- [ ] **Step 3: Write minimal implementation**

```python
# kali/http_history/service.py
from collections import OrderedDict

_STORE_CACHE_MAX = 32  # open SQLite handles kept per MCP process (LRU)
```

```python
# nel costruttore
        self._stores: OrderedDict[str, HttpHistoryStore] = OrderedDict()
```

```python
# sostituendo il corpo di store()
    def store(self, project_id: str) -> HttpHistoryStore:
        with self._lock:
            store = self._stores.get(project_id)
            if store is not None:
                self._stores.move_to_end(project_id)
                return store
            store = self._store_factory(project_id)
            self._stores[project_id] = store
            while len(self._stores) > _STORE_CACHE_MAX:
                _, evicted = self._stores.popitem(last=False)
                try:
                    evicted.close()
                except Exception:  # noqa: BLE001 - eviction never fails a read
                    pass
            return store
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/kali tests/attack -q -p no:cacheprovider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/service.py tests/kali/test_http_history_service.py
git commit -m "fix(http-history): bound the per-project store connection cache"
```

---

## Self-Review

**Copertura dei problemi.** P0 wiring: Task 9 e 10. P0 replay senza body: Task 1. P0 falsi positivi WAF: Task 5. P1 indici e ANALYZE: Task 2. P2 negazione: Task 3 e 4. P3 sanitizzazione: Task 7. P3 lineage: Task 8. P5 contratto: Task 6. Igiene (busy_timeout, LRU): Task 2 e 11. Base di rete e WAF (SNAT, rate limiter, splice): dichiarata fuori scope, richiede un piano separato con prerequisiti infrastrutturali.

**Placeholder.** Nessun TBD/TODO: ogni step porta il codice o il comando esatto.

**Coerenza dei nomi.** `BodyUnavailableError` (Task 1) e l'unico nome nuovo usato in `_error_payload`. `default_http_search_fn`/`default_http_get_fn` (Task 9) hanno la firma che `HttpHistorySearchTool`/`HttpHistoryGetTool` invocano; `default_replay_fn` (Task 9) e consumato da `runner_react_tools` (Task 10) con la stessa firma a tre argomenti. `_allowed`/`_defence_signal` (Task 5) non sono ridefiniti altrove. `optimize()` (Task 2) e usato solo dalla verifica manuale. `_STORE_CACHE_MAX` (Task 11) e patchato nel test con lo stesso nome.

**Nota sui test di performance.** Il guadagno degli indici covering e verificato in modo deterministico con `EXPLAIN QUERY PLAN` (Task 2, Step 5) e non con un'asserzione temporale, che in CI sarebbe instabile.
