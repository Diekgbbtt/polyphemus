# Rate-Limit Posture Store — Design

**Data:** 2026-09-25
**Stato:** approvata a sezioni in chat; in attesa della review di questo file
**Contesto:** follow-up della issue #238, priorità 1 dell'operatore.
La priorità 2 (concorrenza non applicata nel run live) è un lavoro di debugging
separato e NON è coperta da questa spec.

---

## 1. Problema

Da #238 la postura di rate limit di un bersaglio viene misurata a inizio run e
persistita in `recon_runs.stats["rate_limit"]` (`rate-profile/v2`). Quella
forma ha due limiti:

1. **È per-run.** Una run è un evento; la postura è uno stato del progetto che
   sopravvive alla run e serve anche alle fasi che vengono dopo.
2. **Non è leggibile dalle altre fasi.** La fase di hunting esegue comandi su
   Kali (`attack/hunting/pod/tools.py::default_exec_fn` →
   `recon.domain.pod.default_exec_fn`) senza sapere quale sia il limite noto
   per il target che sta colpendo.

Oggi il traffico di hunting è di fatto **non governato**: l'exec seam di hunting
non passa alcuna `traffic_policy`, quindi il lease è di sola cattura e il
governor non applica nulla.

## 2. Obiettivo e criterio di successo

La postura corrente di ogni target di un progetto è disponibile come file YAML
semplice sotto `data/<project_id>/rate-limit/`, ed è leggibile da qualunque fase
tramite (a) la store class del codice e (b) un unico tool agent-facing in sola
lettura. La fase di hunting, prima di mandare traffico, può risolvere l'host
verso la postura applicabile.

Successo significa:

- un file per target, sovrascritto dalla misura più recente;
- nessuna divergenza tra il file e il record per-run di Postgres;
- il tool risponde in modo distinto per "target noto", "host non coperto",
  "nessuna postura", "file illeggibile";
- il traffico di hunting **non** viene limitato (decisione dell'operatore), e
  il file lo dichiara esplicitamente.

## 3. Decisioni acquisite

Decisioni prese dall'operatore in chat; non si rinegoziano in implementazione.

| # | Decisione |
|---|-----------|
| D1 | Più target per progetto: **un file di postura per `target_key`**, non un file per progetto. |
| D2 | Lo YAML **convive** con `recon_runs.stats`: il file è la postura corrente di progetto, lo stats è il registro immutabile per-run. Nessuna sostituzione. |
| D3 | Il tool per gli agenti è **in sola lettura**. Il controllore è l'unico scrittore. |
| D4 | Hunting riceve **informazione, non enforcement**: nessun throttle, nessuna modifica al lease, al proxy o al governor. |
| D5 | Se la scrittura del file fallisce, la run **fallisce** (stessa disciplina dell'envelope di admission). |
| D6 | Il file dichiara sé stesso `advisory: true`: nessun lettore può scambiarlo per enforcement. |

## 4. Non-obiettivi

- Impedire o limitare il traffico di hunting (enforcement): rimandato, richiede
  che il lease porti un insieme di policy e che il proxy risolva l'host.
- Sostituire `recon_runs.stats` o `stats["traffic_admission"]`.
- Scrivere la postura da parte degli agenti.
- Conservare lo storico nel file: la storia resta in Postgres.

## 5. Layout su disco

```
data/<project_id>/
├── auth/                     (esistente)
└── rate-limit/
    ├── acme.com.yaml
    ├── api.acme.com.yaml
    └── 93.184.216.34.yaml
```

- `rate-limit` è una voce **fissa** dello scaffold in
  `src/polymerhus/app/data_root.py::PROJECT_SCAFFOLD`. Nessun altro modulo
  crea directory.
- Il nome del file è il `target_key` passato da `validate_path_component`
  (lo stesso guardiano di `project_id`). Un `target_key` che non è un singolo
  componente di path sicuro **fa fallire la scrittura in modo rumoroso**, mai
  sanificato in silenzio.
- La directory viene creata pigramente alla prima scrittura per i progetti
  esistenti (precedente auth store); per i progetti nuovi la crea
  `ensure_project`.

## 6. Contratto del file

Envelope sottile attorno al profilo già validato:

```yaml
version: rate-limit-posture/v1
source_run_id: <run_id che ha prodotto la misura>
advisory: true
profile: { ...rate-profile/v2 serializzato... }
```

- `profile` è la serializzazione dello **stesso** oggetto `RateProfile` che il
  pipeline ha appena persistito in `stats["rate_limit"]`. In lettura viene
  ri-validato con lo stesso modello (`RateProfile.model_validate`): nessuno
  schema nuovo, nessuna deriva possibile con il contratto di misura.
- `source_run_id` rende ogni lettura riconciliabile con il record della run.
- `advisory: true` è deliberato: chi legge deve vedere che il limite è noto ma
  non imposto.
- Versione del file: `rate-limit-posture/v1`.

L'envelope è un modello pydantic chiuso (`extra="forbid"`), come ogni contratto
del repo: un campo inatteso è un difetto di cablaggio, non un campo ignorato.

## 7. Store (lato codice)

Modulo nuovo `src/polymerhus/app/rate_limit/`:

```
src/polymerhus/app/rate_limit/
├── __init__.py
├── store.py
└── tool.py
```

Interfacce:

```python
POSTURE_VERSION = "rate-limit-posture/v1"

class PostureUnreadableError(ValueError): ...
class PostureWriteError(ValueError): ...

@dataclass(frozen=True)
class PostureRecord:
    target_key: str
    profile: RateProfile
    source_run_id: str
    fresh: bool

class RateLimitPostureStore:
    def __init__(self, root: str | Path | None = None) -> None: ...
    def write(self, project_id: str, profile: RateProfile,
              source_run_id: str) -> Path: ...
    def read(self, project_id: str, target_key: str) -> PostureRecord | None: ...
    def list_targets(self, project_id: str) -> list[str]: ...
    def resolve(self, project_id: str, host: str) -> PostureRecord | None: ...
```

Regole:

- Scrittura **atomica** (temp file nella stessa directory + `os.replace`) e
  serializzata **per progetto** con un `threading.Lock` per `project_id`
  (precedente `AuthStore`).
- `read` restituisce `None` **solo** se il file non esiste. Un file corrotto o
  non validabile solleva `PostureUnreadableError`: **illeggibile ≠ assente**.
  Questa è una divergenza deliberata dal precedente auth store, che degrada a
  vuoto: qui un file rotto che rispondesse "nessuna postura" verrebbe letto
  come "nessun limite noto", il silenzio che #238 esiste per eliminare.
- `list_targets` elenca i file `.yaml` validi della cartella; una cartella
  assente restituisce `[]`.
- `resolve(project_id, host)` cerca tra le posture del progetto quella i cui
  `host_patterns` coprono l'host, con **la stessa semantica del governor**
  (`host_matches`: match esatto + wildcard `fnmatch`, case-insensitive). La
  semantica è **rispecchiata, non importata**: `kali` non è un package
  disponibile nell'immagine dell'agent, quindi il predicato si ri-implementa
  qui (il precedente `D220-7` "mirrored never imported upward") con un test che
  lo pinna. Se nessuna postura copre l'host, `resolve` restituisce `None`
  (l'host potrebbe essere un sottodominio scoperto dopo la misura).
- `fresh` è calcolato alla lettura con `RateProfile.is_fresh(now)`.

Dipendenza: lo store importa `RateProfile` da
`polymerhus.recon.domain.rate_limit`, che non importa a sua volta `app` —
nessun ciclo. L'import avviene a livello di modulo, non dentro le funzioni.

## 8. Tool agent-facing

`build_rate_limit_posture_tool(project_id: str, store: RateLimitPostureStore | None = None)`
in `app/rate_limit/tool.py`, sul precedente di `build_auth_store_tool`.

Il tool si chiama `rate_limit_posture`.

Operazioni (sola lettura): `list`, `get(target)`, `resolve(host)`.

Il contratto d'uso è renderizzato **verbatim** nella descrizione del tool
(precedente `AUTH_STORE_CONTRACT`, `GRAPH_VIEW_CONTRACT`,
`REPLAY_HTTP_REQUEST_DESCRIPTION`) e dice: cos'è una postura, che è **per
target**, che gli host in scope non misurati non hanno un limite noto (il valore
da assumere è quello conservativo), e che il file è **advisory e non imposto**.
Nessuna istruzione duplicata nel system prompt: una sola sorgente.

Quattro esiti distinti, mai collassati:

| Situazione | Risposta |
|---|---|
| Una postura copre l'host | `known_target`: postura + `fresh: true/false` |
| Il progetto ha posture ma nessuna copre l'host | `no_posture_for_host`: limite non misurato; valore da assumere = fallback conservativa, etichettata come assunzione |
| Il progetto non ha posture | `no_postures` |
| File corrotto o non validabile | `unreadable`: errore esplicito |

La fallback conservativa non è un numero inventato dal tool: è
`RateProfile.conservative(...)` (1 r/s, burst 1, concorrenza 1,
`source: conservative-fallback`), la stessa funzione di dominio che la
definisce per l'admission.

Il tool è **fail-open verso il turno**: non solleva mai dentro la conversazione,
restituisce JSON con `ok: false` e il motivo. Lo store resta fail-loud: è
l'adattatore che traduce il guasto in una risposta leggibile dal modello.

**Tensione dichiarata.** #238 dice che l'LLM non deve vedere numeri, perché non
deve poter allargare un budget. Questo tool glieli mostra. La distinzione che
regge è tra *autorità di lettura* e *autorità di scrittura*: il tool è
read-only, i contratti dei verdetti restano senza campi numerici, e nessun
numero letto rientra in una decisione. Il modello può **sapere** il limite, non
può **cambiarlo**.

## 9. Percorso di scrittura

Un solo punto scrive: `run_pipeline`, subito dopo `_persist_rate_profile`.

Ordine obbligato:

1. Postgres (`stats["rate_limit"]`, comportamento esistente, invariato);
2. YAML, dallo stesso oggetto `RateProfile` già validato.

Se la scrittura YAML solleva (`PostureWriteError` / I/O / nome non sicuro):
log rumoroso e run marcata `failed` **prima di qualunque fase**.

Guardia di recency: se il file esistente ha un `profile.measured_at`
**successivo** a quello in scrittura, non si sovrascrive — la misura più nuova
vince — si registra un warning e la run **continua**. Serve perché con run
concorrenti l'ordine di scrittura non coincide con l'ordine di misura.

## 10. Invarianti di coesistenza con Postgres

1. **Un solo scrittore**: il pipeline. Gli agenti non scrivono.
2. **Un solo oggetto**: lo YAML serializza lo stesso `RateProfile` appena
   persistito in `stats`; nessuna ri-derivazione.
3. **Provenienza**: `source_run_id` nel file.
4. **Test di non-divergenza**: dopo la scrittura, il payload del file e
   `stats["rate_limit"]` devono essere uguali.
5. **`advisory: true`**: mai confondibile con enforcement.

## 11. Integrazione in hunting

Binding del tool ai soli agenti che eseguono comandi su Kali:

- **Pod Runner** — `attack/hunting/pod/agents.py::runner_react_tools`;
- **Hunter** — `attack/hunting/hunter_tools.py::build_hunter_tools`.

Non al **Triager** (`triager_react_tools`): non tocca mai il target.

Flusso che il contratto insegna: prima di mandare traffico a un host,
`resolve(host)`; se esiste una postura, non superare il limite dichiarato; se
non esiste, sapere che il target non è stato misurato e che il valore da
assumere è quello conservativo. Poi esegue il comando come oggi.

**Cosa non si fa** (D4): nessuna modifica a `ExecTool`, a `default_exec_fn`,
agli argomenti dell'exec, al registry dei lease, al proxy o al governor;
nessun blocco, nessun throttle.

## 12. Errori e semantiche di fallimento

| Evento | Comportamento |
|---|---|
| File assente | `read`/`resolve` → `None`; il tool → `no_postures` / `no_posture_for_host` |
| YAML corrotto o non validabile | `PostureUnreadableError`; il tool → `unreadable` |
| Nome di target non sicuro | `PostureWriteError`; la run fallisce |
| I/O fallita in scrittura | `PostureWriteError`; la run fallisce |
| Postura in scrittura più vecchia di quella su disco | nessuna sovrascrittura + warning; la run continua |
| Postura scaduta | leggibile, `fresh: false` |

## 13. Testing

Store (`tests/app/test_rate_limit_posture_store.py`):
scrittura atomica, lock per progetto, `list_targets` su cartella assente,
`resolve` con match esatto e wildcard, flag di freschezza, rifiuto di un nome
non sicuro, `PostureUnreadableError` su file corrotto.

Tool (`tests/app/test_rate_limit_posture_tool.py`):
i quattro esiti distinti, sola lettura (nessuna operazione di scrittura),
fail-open verso il turno, nessun segreto nel risultato.

Percorso di scrittura (`tests/recon/test_rate_limit_posture_write.py`):
successo → file presente e uguale a `stats` (test di non-divergenza);
fallimento I/O → run `failed` e nessuna fase eseguita; postura più vecchia →
nessuna sovrascrittura, run che continua.

Scaffold (`tests/test_data_root.py`): `rate-limit` presente nello scaffold di
progetto.

Binding hunting: il tool presente in `runner_react_tools` e
`build_hunter_tools`, assente in `triager_react_tools`.

## 14. Fuori scope / lavoro successivo

La priorità 2 — concorrenza non applicata nel run live — non è coperta qui.
Ha un piano separato (`docs/superpowers/plans/2026-09-25-issue-238-live-concurrency-fix.md`)
e segue il percorso di debugging sistematico: strumentazione, oracolo nel gate,
esperimento discriminante, fix mappato sull'evidenza.

Aggiornamenti di modello attesi in implementazione (CLAUDE.md: il modello si
tiene corrente nello stesso cambio): `src/polymerhus/app/CONTEXT.md` per il
nuovo modulo `app/rate_limit`, e `src/polymerhus/recon/CONTEXT.md` solo se il
vocabolario della postura persistita cambia.

## 15. Impatto sui prompt e sul workflow dell'orchestrator

**Nessuna modifica al workflow dell'orchestrator di recon.** Verificato:

- il system prompt dell'actor è **uno solo**: `_load_orchestrator_prompt()`
  (`orchestrator_agent.py`) concatena `prompts/auth-gateway.md` e
  `prompts/rate-limit-gateway.md`; i due turni condividono sessione e thread, e
  il turn brief seleziona la disciplina. Restano **due** turni prima della
  fase 0, come affermano `docs/design/technical-architecture.md` e
  `src/polymerhus/recon/CONTEXT.md`.
- la scrittura della postura è un atto deterministico del pipeline (§9), non
  un turno del modello: non esiste un turno da aggiungere, né un brief, né una
  sezione di prompt.
- `prompts/rate-limit-gateway.md` dichiara che la superficie tool di quel turno
  è **esattamente due** (`map_rate_limit`, `test_rate_limit_variant`). Il tool
  di lettura della postura **non** va legato all'orchestrator di recon: il suo
  binding è in hunting (§11). Legarlo qui romperebbe quel contratto.

La persistenza resta quindi invisibile al modello: nessun verdetto cambia, e la
disciplina "il controllore possiede i numeri e la loro persistenza" non si
sposta di un millimetro.

Documentazione da allineare nello stesso cambio (CLAUDE.md: il modello si tiene
corrente mentre si costruisce):

- `docs/design/rate-limit-job-admission-operations.md` (runbook operativo #238):
  oggi elenca dove si leggono `stats.rate_limit` / `stats.traffic_admission`;
  va aggiunta la seconda superficie di persistenza
  `data/<project_id>/rate-limit/<target_key>.yaml` con la sua semantica
  (postura corrente di progetto, advisory, non enforcement) e la regola di
  precedenza in caso di divergenza.
- `src/polymerhus/app/CONTEXT.md`: il nuovo modulo `app/rate_limit` e la sua
  ownership del bucket.
