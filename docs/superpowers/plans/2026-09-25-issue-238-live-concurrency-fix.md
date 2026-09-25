# Issue #238 Live Concurrency Fix — Debugging Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging. This is a DIAGNOSIS FIRST plan: Tasks 1-2 build the instrument and the oracle, Task 3 produces the discriminating evidence, Task 4 applies the fix the evidence names, Task 5 closes the remaining enforcement gaps. Do NOT guess a fix before Task 3 is recorded.

**Goal:** il bersaglio non deve mai osservare più richieste in volo di `max_concurrency` quando esiste una policy armata — oggi osserva 30 con `max_concurrency = 1`.

**Architecture:** il governor vive nel processo mitmdump e tiene una bucket per `(project_id, target_key)`; il proxy risolve il lease dal `source_ip` del flow; il controller passa la policy nel seam exec. Il difetto sta in uno dei tre anelli (armamento, risoluzione, meccanismo) e va localizzato con il confronto tra i contatori del governor e ciò che vede il target.

**Tech Stack:** Python 3.12, mitmproxy addon, SQLite (registry dei lease), Postgres, Docker Compose (stack E2E `polyphemus-238-e2e`), pytest.

**Spec / contesto:** `docs/design/rate-limit-job-admission-operations.md`,
`docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md`,
e il finding live: run `high_limit`, policy `max_concurrency = 1`, picco
osservato dal target 30 richieste in volo, 3416 eventi con `in_flight > 1`,
primo picco sulla route `/.svnignore` (wordlist `ffuf`), flow catturati dal
proxy Kali.

## Global Constraints

- Non si tocca il comportamento di produzione prima di avere l'evidenza di Task 3.
- Il governor è **fail-closed**: un guasto non deve mai diventare egresso libero.
- Il rate e la concorrenza sono **aggregati per `(project_id, target_key)`**; il `source_ip` è solo trasporto di lookup e non entra mai nella chiave.
- Ogni correzione arriva con un test che falliva prima e con la mutazione avversariale corrispondente uccisa.
- Lo stack E2E privato non deve mai toccare lo stack dell'operatore (`172.29/16`, porta `18080`, progetto `polyphemus-238-e2e`).

## Review Focus

- Con **zero richieste** al target l'asserzione di concorrenza non deve passare per vacuïetà: la si valuta solo se il target ha visto traffico.
- Un **host fuori scope** non deve essere conteggiato come violazione: la policy è per target, non per tutto l'egresso del container.
- Un contatore del governor **più basso** di quello del target non è un successo: significa che parte del traffico non era governata.
- Il gate deve restare verde sulle 7 posture esistenti senza allentare alcuna asserzione già presente.
- La correzione non deve cambiare il comportamento del **rate** (già applicato): solo la concorrenza.

---

### Task 1: Rendi leggibili i contatori del governor e dell'addon

**Files:**
- Modify: `kali/http_history/addon.py`
- Modify: `kali/http_history/service.py` (`proxy_status`)
- Test: `tests/kali/test_governor_status_snapshot.py`

**Interfaces:**
- Produces: `HttpHistoryAddon.runtime_counters() -> dict`,
  `HttpHistoryAddon._publish_runtime_counters(force: bool = False)`,
  `proxy_status()["traffic_governor"]["runtime"]`

- [ ] **Step 1: Write the failing test**

```python
# tests/kali/test_governor_status_snapshot.py
import json

from kali.http_history.addon import HttpHistoryAddon
from kali.http_history.governor import TargetGovernor


def test_runtime_counters_expose_the_governor_and_the_addon(tmp_path):
    addon = HttpHistoryAddon(root=tmp_path, governor=TargetGovernor())

    counters = addon.runtime_counters()

    assert counters["governor"]["peak_inflight"] == 0
    assert counters["governor"]["admitted"] == 0
    assert counters["governor"]["duplicate_releases"] == 0
    assert "governed" in counters["addon"]
    assert "governor_refusals" in counters["addon"]


def test_publish_writes_one_snapshot_file(tmp_path):
    addon = HttpHistoryAddon(root=tmp_path, governor=TargetGovernor())

    addon._publish_runtime_counters(force=True)

    payload = json.loads((tmp_path / "governor-status.json").read_text(encoding="utf-8"))
    assert payload["governor"]["buckets"] == 0
    assert "addon" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/kali/test_governor_status_snapshot.py -q`
Expected: FAIL with `AttributeError: 'HttpHistoryAddon' object has no attribute 'runtime_counters'`

- [ ] **Step 3: Write the minimal implementation**

In `kali/http_history/addon.py` (aggiungi gli import `json`, `os`, `time`,
`pathlib.Path` se assenti, la costante `_STATUS_PUBLISH_INTERVAL_S = 1.0`, e
in `__init__` l'attributo `self._last_publish = 0.0`):

```python
    def runtime_counters(self) -> dict:
        """The live governance counters of THIS proxy process (#238 live fix).

        The MCP service cannot read them across the process boundary, so the
        addon publishes a snapshot the service re-exposes through
        `proxy_status()`. The discriminator that separates "the governor never
        saw the traffic" from "the governor governed it badly" is
        `governor.peak_inflight` against the fixture's own `max_in_flight`.
        """
        governor = self.governor.status() if self.governor is not None else {}
        with self._lock:
            addon = dict(self._status)
        return {"addon": addon, "governor": governor}

    def _publish_runtime_counters(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < _STATUS_PUBLISH_INTERVAL_S:
            return
        self._last_publish = now
        path = Path(self.root) / "governor-status.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.runtime_counters(), sort_keys=True),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError:
            with self._lock:
                self._status["governor_failed"] += 1
                self._status["governor_last_error"] = "status_publish_failed"
```

Chiama `self._publish_runtime_counters()` in coda all'hook `request` e
`self._publish_runtime_counters(force=True)` in `done()`.

In `kali/http_history/service.py::proxy_status()`, dopo aver costruito
`traffic_governor`:

```python
        runtime = self._read_governor_status()
        if runtime is not None:
            traffic_governor["runtime"] = runtime
```

e il lettore:

```python
    def _read_governor_status(self) -> dict | None:
        """The addon's published snapshot, or None when it is absent/unreadable.
        Absence is not an error: a fresh proxy has not published yet."""
        from pathlib import Path  # noqa: PLC0415
        import json  # noqa: PLC0415

        path = Path(self.config.store_root) / "governor-status.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/kali/test_governor_status_snapshot.py tests/kali -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kali/http_history/addon.py kali/http_history/service.py \
  tests/kali/test_governor_status_snapshot.py
git commit -m "feat(kali): publish the live governor counters for diagnosis"
```

---

### Task 2: Il gate diventa un oracolo della concorrenza

**Files:**
- Modify: `tests/e2e/test_rate_limit_admission_e2e.py`
- Test: lo stesso file (è il gate)

**Interfaces:**
- Consumes: il counters del fixture (`max_in_flight`), la policy persistita in
  `stats["rate_limit"]["traffic_policy"]`, `proxy_status()["traffic_governor"]["runtime"]`

- [ ] **Step 1: Scrivi l'asserzione (fallisce sullo stato attuale)**

In `_run_scenario`, dopo aver letto `counters = observed["target"]` e lo stats
della run:

```python
    max_in_flight = int(counters.get("max_in_flight") or 0)
    policy = (run_stats.get("rate_limit") or {}).get("traffic_policy") or {}
    ceiling = int(policy.get("max_concurrency") or 0)
    if ceiling and counters.get("requests"):
        assert max_in_flight <= ceiling, (
            f"{scenario.posture}: the target observed max_in_flight="
            f"{max_in_flight} with max_concurrency={ceiling}"
        )
```

E, quando lo stack espone il runtime del governor (Task 1), l'accordo tra le
due viste:

```python
    governor_peak = (
        ((proxy_status.get("traffic_governor") or {}).get("runtime") or {})
        .get("governor", {})
        .get("peak_inflight")
    )
    if governor_peak is not None and counters.get("requests"):
        assert governor_peak <= ceiling or governor_peak <= max_in_flight, (
            f"{scenario.posture}: governor peak_inflight={governor_peak} "
            f"exceeds both the ceiling {ceiling} and the target's "
            f"observed peak {max_in_flight}"
        )
```

La seconda asserzione non è ridondante: se il governor dichiara un picco più
basso di quello visto dal target, parte del traffico non era governata — ed è
il sintomo del ramo (a).

- [ ] **Step 2: Verifica che fallisca**

Run: `sh scripts/issue_238_e2e_stack.sh gate-once live-concurrency-oracle`
Expected: FAIL con il messaggio `the target observed max_in_flight=30 with max_concurrency=1`

Se invece il gate passa, il finding precedente non è riproducibile su questo
stack: fermati e documenta la differenza prima di toccare il codice.

- [ ] **Step 3: Commit dell'oracolo**

```bash
git add tests/e2e/test_rate_limit_admission_e2e.py
git commit -m "test(e2e): assert the concurrency ceiling from the target's view"
```

---

### Task 3: L'esperimento discriminante e il verdetto

**Files:**
- Create: `docs/superpowers/notes/2026-09-25-live-concurrency-verdict.md`

**Interfaces:**
- Consumes: Task 1 (counters), Task 2 (oracle), il registry dei lease, la policy persistita
- Produces: un verdetto scritto che nomina UN ramo tra (a), (b), (c) con i numeri che lo provano

- [ ] **Step 1: Raccogli le tre viste nello stesso momento**

```bash
# 1. il gate, che ora porta l'asserzione: il messaggio di fallimento contiene
#    il picco visto dal TARGET per ogni postura
sh scripts/issue_238_e2e_stack.sh gate-once diag-live

# 2. la policy PERSISTITA della run (fonte di verità del controller)
docker compose -p polyphemus-238-e2e -f docker-compose.yml -f docker-compose.e2e.yml \
  exec -T postgres psql -U polymerhus -d polymerhus -Atc \
  "select run_id, stats->'rate_limit'->>'outcome', \
          stats->'rate_limit'->'traffic_policy'->>'target_key', \
          stats->'rate_limit'->'traffic_policy'->>'max_concurrency', \
          stats->'rate_limit'->'traffic_policy'->>'host_patterns', \
          stats->'rate_limit'->'traffic_policy'->>'rate_per_s' \
     from recon_runs order by started_at desc limit 3;"

# 3. la policy REGISTRATA nel lease e i contatori del governor
docker compose -p polyphemus-238-e2e -f docker-compose.yml -f docker-compose.e2e.yml \
  exec -T kali sqlite3 /run/kali-http/registry.sqlite3 \
  "select source_ip, project_id, substr(coalesce(traffic_policy,'<null>'),1,160), \
          created_at, expires_at from leases;"
docker compose -p polyphemus-238-e2e -f docker-compose.yml -f docker-compose.e2e.yml \
  exec -T kali cat /data/governor-status.json
```

- [ ] **Step 2: Applica la tabella di decisione**

| Evidenza | Ramo | Significato |
|---|---|---|
| riga lease con `traffic_policy` `<null>`, scaduta, o `source_ip` diverso da quello del flusso | (a1) armamento | il proxy non ha mai avuto una policy da applicare |
| riga lease armata ma `addon.governed` ≈ 0 e `governor.admitted` ≈ 0 | (a2) risoluzione | il flow non è stato associato alla riga (resolver senza `lookup_registration`, `source_ip` non risolto, o host che non matcha `host_patterns` → `GovernorDecision(False)` silenzioso) |
| `governor.peak_inflight` ≈ 1 con target a 30 | (a) | stesso esito di (a1)/(a2): il governor non ha governato quel traffico |
| `governor.peak_inflight` = 30 | (b) meccanismo | il governor governava ma con chiave o istanza sbagliata |
| `governor.admitted` molto sopra l'atteso, `waited_s` ≈ 0, `duplicate_releases` > 0 | (c) release | il permesso torna libero troppo presto o più volte |

- [ ] **Step 3: Scrivi il verdetto**

Crea `docs/superpowers/notes/2026-09-25-live-concurrency-verdict.md` con:

- i tre numeri affiancati per la stessa finestra temporale (policy persistita /
  policy registrata / contatori del governor) e il picco visto dal target;
- il ramo nominato e perché gli altri sono esclusi;
- l'ipotesi meccanicistica in una frase ("il flow non risolveva la riga perché…").

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/notes/2026-09-25-live-concurrency-verdict.md
git commit -m "docs(238): record the live concurrency discriminator"
```

---

### Task 4: Applica il fix che l'evidenza nomina

**Files:** dipendono dal ramo (sotto). In ogni caso il test vive nel modulo
che possiede il codice corretto, e il gate di Task 2 deve diventare verde.

**Interfaces:**
- Consumes: il verdetto di Task 3
- Produces: una sola correzione, con un test che falliva prima

Esegui **solo** il ramo che il verdetto nomina. Gli altri restano non toccati.

- [ ] **Ramo (a1) — la policy non arrivava al lease**

  Percorso da verificare in ordine: `pipeline` → `extra["traffic_policy"]` →
  `run_job`/`pod_invoke` → `domain/pod.py` (`_accepts_traffic_policy`,
  `kwargs["traffic_policy"]`) → `default_exec_fn` (`args["traffic_policy"]`) →
  `kali.mcp_server.execute_command` → `service.execute` → `registry.register`.

  Test che deve fallire prima: in
  `tests/recon/test_pod_traffic_policy_forwarding.py`, un test che chiama
  `default_exec_fn(..., traffic_policy={...})` con un `execute_command`
  registrato come fake e asserisce che il kwarg arriva intatto nel payload MCP.
  Mutazione da uccidere: rimuovere `args["traffic_policy"] = traffic_policy`.

  ```python
  def test_default_exec_fn_forwards_the_policy(monkeypatch):
      seen = {}

      class _Tool:
          name = "execute_command"

          async def ainvoke(self, payload):
              seen.update(payload.get("args") or {})
              return {"structured_content": {}}

      monkeypatch.setattr(
          "polymerhus.recon.domain.pod._mcp_tools", lambda: [_Tool()]
      )
      from polymerhus.recon.domain.pod import default_exec_fn

      default_exec_fn("true", "sess-1", 5, None, {"version": "traffic-policy/v2"})

      assert seen["traffic_policy"] == {"version": "traffic-policy/v2"}
  ```

- [ ] **Ramo (a2) — il flow non risolveva la riga**

  Due sottocasi, entrambi da sanare:
  1. **host non coperto**: su un lease armato, un host che non matcha
     `host_patterns` oggi esce **silenziosamente** non governato
     (`GovernorDecision(governed=False)`). Rendilo visibile: incrementa un
     contatore dedicato (`ungoverned_host`) e registra `last_ungoverned_host`;
     il gate di Task 2 lo legge e fallisce se compare su una postura
     target-facing. Se l'operatore vuole il fail-closed pieno, questo diventa un
     rifiuto locale; la decisione va presa esplicitamente, non silenziosamente.
  2. **resolver legacy**: se l'addon costruito in produzione non espone
     `lookup_registration`, il governo non si applica affatto. Test: costruire
     l'addon con `addon_entry.build_addons()` (o l'entry E2E) e asserire che il
     resolver iniettato espone `lookup_registration`.

- [ ] **Ramo (b) — la chiave di stato o l'istanza**

  Verifica nell'ordine: (i) il `project_id` visto dal proxy è lo stesso di
  quello registrato (un `project_id` vuoto in un hop crea un secondo bucket);
  (ii) `target_key` identico tra lease diversi per lo stesso host (niente
  varianti `host` vs `host:port`); (iii) una sola istanza di
  `TargetGovernor` per processo (l'addon è costruito una volta sola).

  Test: in `tests/kali/test_governor_key_aggregation.py`, due `acquire`
  concorrenti con lo stesso `(project_id, target_key)` e
  `max_concurrency=1` devono serializzarsi (il secondo attende), mentre due
  `source_ip` diversi devono **condividere** la stessa bucket.

- [ ] **Ramo (c) — il rilascio del permesso**

  Il rilascio avviene negli hook `response`/`error`. Se l'evidenza mostra
  `duplicate_releases > 0` con `peak_inflight` alto, il permesso viene
  restituito due volte o troppo presto. Test: in
  `tests/kali/test_governor_release_timing.py`, un flow che non ha ancora
  ricevuto risposta non deve liberare lo slot; un `response` seguito da
  `error` sullo stesso flow non deve ammettere due volte.

- [ ] **Verifica finale del fix**

Run: `sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-concurrency`
Expected: PASS su entrambe le run, con l'asserzione di Task 2 attiva.

Run: `python -m pytest tests/kali tests/recon tests/attack -q`
Expected: PASS

- [ ] **Commit**

```bash
git add -A
git commit -m "fix(kali): enforce the measured concurrency ceiling live"
```

---

### Task 5: Certifica i quattro enforcement A10 dal punto di vista del target

**Files:**
- Modify: `tests/e2e/test_rate_limit_admission_e2e.py`
- Modify: `scripts/issue_238_e2e_stack.sh` (solo se serve una postura in più)

**Interfaces:**
- Consumes: i servizi `kali-failing-governor` e `kali-capture-off` già in `docker-compose.e2e.yml`, il counters del fixture
- Produces: quattro asserzioni live che oggi non esistono

- [ ] **Bucket condiviso tra due pod dello stesso `(project_id, target_key)`**

  Scenario: due job target-facing materializzati nella stessa run (o due run
  concorrenti sullo stesso progetto e target). Asserzione: il rate aggregato
  osservato dal fixture non supera `rate_per_s`, e `governor.buckets == 1` per
  quella chiave.

- [ ] **Isolamento tra progetti diversi**

  Scenario: due progetti con lo stesso target. Asserzione: `governor.keys`
  contiene due chiavi, e il traffico di ciascuno rispetta il proprio budget
  senza sommarsi né bloccarsi.

- [ ] **Eccezione del governor ⇒ zero egress**

  Scenario: avvia l'agent contro `kali-failing-governor` e lancia una run.
  Asserzione: il fixture registra **zero** richieste (`counters["requests"] == 0`)
  e la run riporta un `refusal` strutturato nell'envelope di admission.

  ```bash
  # lo stack E2E espone già il servizio; il test punta l'agent lì e asserisce
  sh scripts/issue_238_e2e_stack.sh gate-once failing-governor
  ```

- [ ] **Capture-off con rate e concorrenza ancora applicati**

  Scenario: avvia l'agent contro `kali-capture-off`. Asserzione: il fixture
  osserva lo stesso rate e lo stesso tetto di concorrenza della postura, e lo
  store di cattura resta vuoto (`capture.enabled == false`).

- [ ] **Commit**

```bash
git add tests/e2e/test_rate_limit_admission_e2e.py scripts/issue_238_e2e_stack.sh
git commit -m "test(e2e): certify the four enforcement properties from the target"
```

---

## Self-Review

**Copertura del problema:** il finding (concorrenza non applicata) è coperto da
Task 1 (strumento), Task 2 (oracolo), Task 3 (discriminante), Task 4 (fix).
Gli altri quattro punti aperti di A10 sono Task 5.

**Placeholder scan:** nessun TBD. Task 4 è deliberatamente ramificato sulla
diagnosi: ogni ramo ha la sua azione concreta, il suo file di test e la sua
mutazione. Questo è il punto del percorso di debugging — un fix non ancora
nominato dall'evidenza non si scrive.

**Type consistency:** `runtime_counters()`, `_publish_runtime_counters(force=)`
e la chiave `traffic_governor["runtime"]` sono usati con lo stesso nome in Task
1, Task 2 e Task 3; il counters del fixture resta `max_in_flight`.
