# Walkthrough — HTTP history #196: come funziona, prima e dopo, limiti

Documento didattico. Racconta **cosa registra** il capture plane, **come** lo fa, e cosa è
cambiato con questo branch. Tutti i numeri e gli estratti vengono da due run reali degli
stessi job, non da esempi costruiti:

| | Run | Progetto | Cosa rappresenta |
|---|---|---|---|
| **PRIMA** | `947cba53-2c09-4a97-af5e-62f5e260ef8b` | `3e200c6e-edf9-4583-9ee6-7972bded36f3` | recon crawl-only con i pod **non** collegati al capture plane |
| **DOPO** | `ef27ec78-dca0-4f17-95bb-749d5e76e53a` | `81aa8c04-1849-4255-a6b3-b9dc8d92cc33` | stessi job, dopo il fix di questo branch |

---

## 1. In una frase

Prima: i tool di recon **parlavano con i target e nessuno scriveva niente**, salvo quello che
il tool decideva di stampare su stdout.

Adesso: ogni richiesta che un pod fa passare dal "terminale" di kali viene registrata da un
proxy locale come **artifact indirizzabile** — metodo, URL, header, cookie, query, stato,
dimensioni, tempi, connessione — correlato al progetto, al run e al pod, e **riproducibile**
con una mutazione dichiarata.

L'analogia è Burp Suite, ridotto all'osso: un recorder + un indice, senza UI, senza
intercettazione manuale, che vive dentro il container kali e serve i pod e l'hunting.

---

## 2. Il problema (com'era)

Il terminale di kali (`execute_command`) eseguiva una shell e restituiva solo
`{stdout, stderr, returncode, duration_ms}`. Nessun proxy, nessun hook di trasporto: la
richiesta HTTP **sparita** nel momento in cui lasciava il processo del tool.

Due conseguenze:

1. **Nessuna riproducibilità.** Non si poteva dire "riesegui la richiesta sicura che il recon
   ha fatto alle 10:31:12", né ricostruirla fedelmente: nel log del tool c'è ciò che il tool
   ha *stampato*, non ciò che ha *mandato*.
2. **Nessuna attribuzione.** Anche ammettendo di ricostruire una richiesta, non c'era modo di
   legarla al run e al pod che l'aveva generata.

Il run **PRIMA** lo mostra in tre punti, tutti coerenti fra loro:

```json
// tool-log.jsonl (run 947cba53), invocazione httpx
{"index": 1, "job": "httpx", "command": "httpx -u 172.28.0.20 -sc -title -server -td -fr -silent -json -irh ",
 "returncode": 0, "duration_ms": 602, "http_artifact_refs": [], "capture_warning": null}
// idem per katana: "http_artifact_refs": []
```

```text
# interrogazione dello store per il run
filters = [context/core/run_id == "947cba53-..."]  ->  0 risultati

# unica riga presente nel progetto
GET http://172.28.0.20/  ->  200   context.run_id = ""   context.spec_id = ""
# ^ è il preflight del lease, non il recon: nessuna attribuzione

# recon_jobs.stats dei due job
httpx:  [commands, consumed, exec_*, failed, pods, produced_*, success]   # nessuna chiave capture
katana: idem
```

Nessun errore, nessun warning, run `complete`, delta `unexplained == 0`: il fallimento era
**silenzioso**.

---

## 3. Modello architetturale (vista d'insieme)

### 3.1 I confini: dove passa il dato, e dove no

```text
┌───────────────── processo agent (uvicorn :8080, PYTHONPATH=/srv/src) ──────────────────┐
│  API HTTP ──▶ pipeline recon ──▶ job agent (MAX_PODS concorrenti) ──▶ POD (LangGraph)  │
│                                                                        │               │
│        il pod NON parla col target: l'unico modo è il seam exec_fn ────┘               │
│                          (command, session_id, timeout_s, capture_context)             │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │  MCP streamable-http :8000
┌───────────────── container kali ──────────┼────────────────────────────────────────────┐
│  mcp_server.execute_command(...)  ──▶  HttpHistoryService                              │
│        │                                     │                                         │
│        │                              LeaseManager.acquire(session_id, project_id, ctx) │
│        │                                     │  namespace dedicato + REDIRECT 80/443    │
│        │                                     ▼                                          │
│        │                            il tool gira dentro 172.30.0.x                      │
│        │                                     │  HTTP/HTTPS                             │
│        │                              mitmproxy  ──▶  target 172.28.0.20                 │
│        │                                     │                                          │
│        │                              addon + normalizer ──▶ store (SQLite + blob)      │
│        │                                     │                    + indice EAV          │
│        └──── refs = search(context/exec_id == exec_id) ◀─────────┘                      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                            │
                    frontiera del modello: escono SOLO view sanitizzate
                    (niente body, header/cookie sensibili redatti)
```

Quattro confini da tenere a mente:

| Confine | Regola |
|---|---|
| pod ↔ target | il pod non apre connessioni proprie: se non passa da `exec_fn` non viene registrato |
| agent ↔ kali | solo il contratto MCP; nessuna condivisione di memoria o di filesystem |
| kali ↔ target | il traffico esce dal namespace del lease (sorgente `172.30.0.x`), non dall'IP del container |
| store ↔ modello | il body e i segreti non attraversano: solo `size`/`capture_state` e valori redatti |

### 3.2 I componenti e chi possiede cosa

| Componente | Responsabilità | Possiede | File |
|---|---|---|---|
| pod di recon | costruire il contesto di cattura e inoltrarlo | `capture_context`, `stats.capture` del pod | `recon/domain/pod.py` |
| pipeline | fondere i frammenti dei pod | copertura per job (`sent`/`refs`/`warning`) | `recon/control/pipeline.py` |
| `execute_command` (MCP) | superficie per il chiamante, sanitizzazione di stdout | contratto pubblico dello storico | `kali/mcp_server.py` |
| `HttpHistoryService` | progetto/exec/lease/ref, replay, tetto di storage | `exec_id`, throttle dei limiti | `kali/http_history/service.py` |
| `LeaseManager` + backend | namespace, REDIRECT, TTL, pool | l'isolamento di rete per esecuzione | `namespaces.py` |
| addon mitmproxy + normalizer | trasformare un flow in un artifact | la verità registrata (record) | `addon.py`, `normalize.py` |
| store | durabilità, indice, retention/cap, GC dei blob | il dato e la sua interrogabilità | `store.py`, `index.py` |
| sanitizer | proiezione model-facing | ciò che è visibile a modello/Langfuse | `sanitize.py` |
| replay (plan + sender) | rispedire una baseline con override dichiarati | lineage (`derived_from`, `replay_kind`) | `replay.py`, `sender.py` |

### 3.3 I contratti (le firme che tengono insieme il modello)

| Seam | Firma essenziale | Chi lo usa |
|---|---|---|
| esecuzione dal pod | `exec_fn(command, session_id, timeout_s, capture_context=None) -> ExecResult{stdout, stderr, returncode, duration_ms, exec_id, http_artifact_refs, capture_warning}` | pod |
| esecuzione MCP | `execute_command(command, session_id, timeout_s, project_id, run_id, spec_id, variant_ref, derived_from, replay_kind)` | client sync, test |
| ricerca | `search_http_history(project_id, filters, cursor, limit, text) -> {summaries, next_cursor}` | pod/hunter, UI, test |
| lettura | `get_http_artifact(project_id, artifact_id) -> artifact sanitizzato` | pod/hunter, test |
| replay | `replay_http_request(project_id, artifact_id, overrides, capture_context) -> {artifact_id, derived_from, replay_kind}` | pod/hunter, test |
| stato | `proxy_status() -> {proxy, routing, namespaces, store, capture}` | healthcheck, diagnosi |
| aggregazione | `capture_job_stats(pod_exports) -> {sent, refs, warning}` | pipeline |

La proprietà è volutamente asimmetrica: il **contesto** è del chiamante (solo lui sa che cosa
stava lavorando), l'**`exec_id`** e l'**artifact** sono di kali (solo il proxy sa cosa è
passato sul filo), la **fusione** è della pipeline (solo lei vede tutti i pod di un job).

### 3.4 Il modello dati

```text
flows            una riga per artifact: record_json (la verità, schema http-artifact/v1) + created_at
attributes       indice sparsa: (side, namespace, key, text_value|numeric_value) per OGNI scalare
flows_fts        indice full-text (ricerca libera su url/header/marker del body)
bodies           blob content-addressed (sha256) + tabella di riferimento, GC quando nessuno li usa
meta             last_purge (audit dell'ultima potatura)
```

| Elemento | Scelta | Perché |
|---|---|---|
| documento completo per artifact | JSON validato (pydantic) | l'artifact è autosufficiente: si legge senza join |
| indice EAV | una riga per attributo, namespace `core/header/cookie/query/form/body/tls` | "interrogabile per qualunque attributo" senza migrazioni di schema |
| body in blob | content-addressed | dedup, e il body non entra mai nelle viste |
| id | ULID con prefisso `http_` | stabile, ordinabile, indirizzabile |
| lineage | `derived_from` + `replay_kind` sul nuovo artifact | un replay è una richiesta **con storia**, non una richiesta nuova |
| limiti | `retention_s` (0) e `project_max_bytes` (1 GiB) | il tetto è sui byte; l'età non cancella (vedi §9) |

### 3.5 Ciclo di vita di un'esecuzione catturata

```text
1. il pod costruisce il contesto (project/run/spec/session) - o None se il progetto manca/feature off
2. execute: mint dell'exec_id  →  acquire del lease (namespace + REDIRECT)  →  run del comando
3. il proxy registra i flow del namespace, ognuno timbrato col contesto dell'exec_id
4. a fine comando, in un finally: refs = search(context/exec_id)  →  release del lease
5. il pod scrive l'esito nella sua export: {sent, refs, warning}
6. la pipeline fonde le export dei pod in recon_jobs.stats[].capture
7. (throttled, best-effort) enforce_limits sul progetto: byte cap
```

Il passo 4 è in `finally` di proposito: se il comando esplode, il lease **non** resta appeso e
gli artifact già registrati vengono comunque restituiti.

### 3.6 Modi di guasto: cosa fallisce aperto e cosa chiude

| Situazione | Comportamento | Perché |
|---|---|---|
| proxy irraggiungibile | il comando gira, `capture_warning` valorizzato, `refs=[]` | la ricognizione non deve diventare inutile per un guasto del recorder |
| pool di namespace esaurito | idem, con `PoolExhaustedError` nel warning | fail-open **dichiarato**, visibile in `stats.capture` |
| nessun `project_id` (exec fuori dal percorso pod) | nessun lease, nessuna cattura, nessun errore | la cattura è per progetto: senza progetto non c'è dove scrivere |
| body oltre il cap | artifact registrato con `capture_state="omitted"` | si perde il contenuto, non la transazione |
| replay su baseline con body dichiarato ma assente | **rifiutato** (`body_unavailable`) | fail-**closed**: un replay senza corpo falsificherebbe l'esperimento |
| indice corrotto o assente | ricostruibile dal `record_json` | l'indice è derivato, il documento è la verità |

### 3.7 Invarianti di design

1. **La cattura non è mai un gate.** Nessun percorso di ricon degrada perché il recorder è
   giù: cambia solo ciò che si può dimostrare dopo.
2. **Il fallimento è visibile.** `sent` distingue "non ho chiesto" da "ho chiesto e non è
   arrivato niente"; un `refs=0` con `sent=true` non può essere scambiato per una cattura
   riuscita.
3. **Un solo scrittore per verità.** Il record lo scrive il proxy; la sanitizzazione è una
   proiezione, non una seconda verità.
4. **Il confine del modello è esplicito.** Ciò che non è nella proiezione (body, `source_ip`,
   header sensibili) non esiste per il modello.
5. **La lineage non si perde.** Ogni replay porta `derived_from`; ogni artifact porta il
   contesto dell'esecuzione che l'ha prodotto.
6. **I limiti sono dichiarati dove mordono.** Tetto di byte, cap del body, pool, porte
   redirette: ognuno è un comportamento scritto in questo documento, non una sorpresa.

## 4. Come funziona adesso

### 4.1 Il percorso di una richiesta

```text
  POD (recon, in-process nell'agent)
   │  exec_fn(command, session_id, timeout_s, capture_context)
   │  capture_context = { project_id, run_id, spec_id, variant_ref }
   ▼
  MCP  kali → execute_command(command, session_id, project_id, run_id, spec_id, ...)
   │
   │  1. il servizio apre un exec_id (ULID) per QUESTA chiamata
   │  2. prende un lease: un namespace di rete dedicato + regole REDIRECT tcp/80 e tcp/443
   │  3. esegue il comando DENTRO quel namespace  ← qui gira il tool
   ▼
  namespace 172.30.0.x  ──HTTP/HTTPS──▶  mitmproxy  ──▶  target 172.28.0.20
                                             │
                                             │  ogni richiesta/risposta completa viene
                                             │  normalizzata e scritta nello store del progetto
                                             ▼
                        /data/<project>/http-history/history.sqlite3  (+ blob dei body)
                                             │
   ◀── 4. a fine comando: search(context/exec_id == exec_id) → http_artifact_refs[]
```

I quattro pezzi, in parole semplici:

| Pezzo | Ruolo | Dove |
|---|---|---|
| **contesto di cattura** | dice "questa esecuzione appartiene a questo progetto/run/pod" | `recon/domain/pod.py`, `CaptureContext` |
| **lease di namespace** | dà al tool una rete sua, con il traffico web deviato sul proxy | `kali/http_history/namespaces.py` |
| **proxy + normalizzatore** | trasforma un flow in un artifact (HAR-like) e lo scrive | `kali/http_history/addon.py`, `normalize.py` |
| **store + indice** | tiene l'artifact e proietta ogni attributo in righe interrogabili | `kali/http_history/store.py`, `index.py` |

### 4.2 Il contesto: le quattro chiavi

Quando il pod invoca il terminale porta con sé:

| Chiave | Valore nel run DOPO (job httpx) | A cosa serve |
|---|---|---|
| `project_id` | `81aa8c04-…` | isolamento: lo store è per progetto |
| `run_id` | `ef27ec78-…` | "tutto il traffico di questo run" |
| `spec_id` | `172.28.0.20` | "cosa ha chiesto il pod incaricato dell'asset X" |
| `session_id` | `ef27ec78-…-0-httpx-880af8cc` | quale pod/iterazione |

`exec_id` non arriva dal pod: lo **minta kali** per ogni chiamata. È la chiave con cui, a fine
comando, si va a cercare nello store tutto ciò che è stato registrato in quella finestra e lo
si restituisce al chiamante come lista di id — è il filo che riporta gli artifact al pod
giusto anche con più pod in parallelo.

`spec_id` è il discriminatore dell'asset del pod (`url`, altrimenti un hash stabile
dell'asset): httpx è seedato con l'IP nudo `172.28.0.20`, katana consuma il `BaseURL`
`http://172.28.0.20`, ed è esattamente quello che si vede nei due artifact.

### 4.3 Cosa c'è dentro un artifact

Struttura di un artifact (schema `http-artifact/v1`):

```text
artifact_id            ULID stabile (http_01M2…), la chiave riusabile
project_id             isolamento
capture_context        { session_id, run_id, spec_id, variant_ref, exec_id, derived_from, replay_kind }
request                http_version, method, url, headers[], cookies[], query[], form[],
                       body{size, encoding, capture_state, capture_reason}, timestamp start/end
response               idem + status, reason
connection             client_address, server_address, protocol, tls, sni, alpn
timings                total_ms
error                  errore di trasporto, se c'è stato (null se la transazione è completa)
derived_from / replay_kind   lineage di un replay
```

Il body **non** attraversa il confine verso il modello: nel view sanitizzato ci sono solo
`size` e `capture_state` (`none`, `empty`, `captured`, `omitted`, `truncated`); i byte restano
nello store e li usa solo il percorso di replay. Gli header/cookie sensibili sono redatti
(`[redacted]`) quando il *nome* matcha la lista sensibile.

### 4.4 Risposta reale, vista dal lato artifact (run DOPO, httpx)

```json
{
  "artifact_id": "http_01M2QEQ7DC6JM96BB3JFSFR20W",
  "capture_context": {"session_id": "ef27ec78-…-0-httpx-880af8cc",
                      "run_id": "ef27ec78-…", "spec_id": "172.28.0.20",
                      "exec_id": "01M2QEQ6R87S521V843ZASWRV5"},
  "request": {"method": "GET", "url": "http://172.28.0.20/", "http_version": "HTTP/1.1",
              "headers": [["Host","172.28.0.20"],
                          ["User-Agent","Mozilla/5.0 (…rv:124.0) Gecko/20100101 Firefox/124.0"],
                          ["Accept-Charset","utf-8"], ["Accept-Encoding","gzip"],
                          ["Connection","close"]],
              "query": [], "form": [], "cookies": [],
              "body": {"size": 0, "capture_state": "empty"}},
  "response": {"status": 200, "reason": "OK", "http_version": "HTTP/1.0",
               "headers": [["Server","BaseHTTP/0.6 Python/3.12.14"], ["Date","…"],
                           ["Content-Type","text/plain; charset=utf-8"],
                           ["Content-Length","65"], ["X-E2E-Target","http-e2e-target"]],
               "body": {"size": 65, "encoding": "utf-8", "capture_state": "captured"}},
  "connection": {"client_address": "172.30.0.2:37820", "server_address": "172.28.0.20:80",
                 "protocol": "http", "tls": false},
  "timings": {"total_ms": 1.96},
  "error": null
}
```

Due cose che vale la pena notare: il `client_address` è `172.30.0.x`, cioè **il namespace del
lease** — è la prova che la richiesta è passata dal percorso di cattura; e il `User-Agent` è
quello vero mandato da httpx, che il tool **non** stampa nel proprio output.

---

## 5. Tool log vs artifact: cosa sa ognuno dei due

Il "tool log" è il registro che il test/recon tiene delle invocazioni: comando + stdout
integrale + returncode + durata + (adesso) il contesto e i ref. È il punto di vista del
**processo**. L'artifact è il punto di vista del **filo**.

| Domanda | Tool log (`tool-log.jsonl` + `stdout/*.out`) | Artifact (`get_http_artifact`) |
|---|---|---|
| Quale comando è stato lanciato | sì (`command`) | no, non è il suo livello |
| Cosa ha **stampato** il tool | sì, integrale | no |
| Cosa è **partito davvero** | solo ciò che il tool ha deciso di stampare | sì: metodo, URL, versione, header, cookie, query, form |
| Cosa è **tornato davvero** | solo ciò che il tool ha deciso di stampare | sì: status, reason, header, cookie, dimensione body, stato di cattura |
| Tempi | `duration_ms` del processo | `timings.total_ms` + timestamp di request e response |
| Connessione | no | indirizzi client/server, protocollo, tls/sni/alpn |
| Identità di correlazione | `session_id` nel nome + contesto registrato dal test | `capture_context` completo, scritto dallo store |
| Identificatore riusabile | no (è testo) | `artifact_id` ULID |
| Riproducibile | no | sì, `replay_http_request` con override a vocabolario chiuso |

Il caso concreto, dalla run DOPO. Lo stdout di httpx è lo stesso di PRIMA (618 byte PRIMA,
619 DOPO: cambiano solo i valori di timestamp/durata) e contiene solo questo:

```json
{"timestamp":"2026-09-17T10:31:12.048Z","port":"80","url":"http://172.28.0.20","input":"172.28.0.20",
 "scheme":"http","webserver":"BaseHTTP/0.6 Python/3.12.14","content_type":"text/plain","method":"GET",
 "host":"172.28.0.20","host_ip":"172.28.0.20","path":"/",
 "header":{"content_length":"65","content_type":"text/plain; charset=utf-8","date":"…","server":"…",
           "x_e2e_target":"http-e2e-target"},
 "time":"5.247108ms","a":["172.28.0.20"],"tech":["Python:3.12.14"],"words":1,"lines":5,
 "status_code":200,"content_length":65,"failed":false}
```

Lì dentro **non c'è la richiesta**: niente header inviati, niente connessione, niente
identificatore. C'è la risposta solo per i campi che httpx ha scelto di esporre. Dal solo
tool log non si può ricostruire la richiesta da rieseguire; dall'artifact sì, ed è
esattamente quello che il replay fa.

---

## 6. PRIMA vs DOPO, sugli stessi job

| | PRIMA (`947cba53`) | DOPO (`ef27ec78`) |
|---|---|---|
| `http_artifact_refs` nel tool log (httpx) | `[]` | `["http_01M2QEQ7DC6JM96BB3JFSFR20W"]` |
| `http_artifact_refs` nel tool log (katana) | `[]` | 2 id (`…9P44GT9…`, `…9PB94M5…`) |
| `capture_warning` | `null` (nessuno sapeva di non star catturando) | `null` (e ref > 0) |
| `capture_context` nel tool log | assente (il seam non lo registrava) | `{project, run, spec_id, variant_ref}` per ogni invocazione |
| artifact dello store per `context/run_id` | **0** | **3** |
| artifact totali del progetto | 1 (solo il preflight, `run_id=""`) | 3 del run + preflight + replay |
| `recon_jobs.stats` per job | nessuna chiave `capture` | `{sent: true, refs: 1\|2, warning: null}` |
| riproducibilità | nessuna | replay con mutazione dichiarata → 200 |
| delta report | `total=8 kept=8 dropped=0 unexplained=0` | identico |
| stato dei job | httpx e katana `success` | httpx e katana `success` |
| durata tool | httpx 602 ms, katana 10.576 s | httpx 637 ms, katana 10.613 s |

Il delta report è rimasto **identico** perché non usa gli artifact: confronta lo stdout reale
dei tool con il grafo. Il capture plane è un livello **in più**, e il fatto che i due numeri
coincidano (`refs > 0` e delta invariato) dice che registrare non ha alterato ciò che il recon
ha capito.

### 6.1 Cosa si può chiedere allo store, adesso

```text
# tutto il traffico di un run
search_http_history(project_id=<proj>, filters=[{"side":"context","namespace":"core",
                    "key":"run_id","op":"eq","value":"ef27ec78-…"}])
  → 3 artifact, url: http://172.28.0.20/ e http://172.28.0.20/robots.txt

# cosa ha chiesto il pod incaricato dell'asset X
filters=[{"side":"context","namespace":"core","key":"spec_id","op":"eq","value":"http://172.28.0.20"}]
  → i 2 artifact di katana (GET / e GET /robots.txt), entrambi 200

# e per attributo qualsiasi, non solo per contesto
filters=[{"side":"response","namespace":"core","key":"status","op":"eq","value":200}]
filters=[{"side":"request","namespace":"header","key":"user-agent","op":"contains","value":"Firefox"}]
filters=[{"side":"body","namespace":"body","key":"marker","op":"contains","value":"marker="}]
```

### 6.2 Il replay, in pratica

```text
replay_http_request(project_id, artifact_id="http_01M2QEQ7DC6JM96BB3JFSFR20W",
                    overrides={"headers": {"X-Polymerhus-Replay-ef27ec78": "e2e-crawl-depth"}})
  → artifact_id = "http_01M2QEQMSDA7EMRQ6GEZMVEJPG"
     derived_from = "http_01M2QEQ7DC6JM96BB3JFSFR20W", replay_kind = "mutated"
```

Nell'artifact del replay l'header dichiarato è **sul wire** (compare nella lista degli header
inviati) e lo status è 200: la baseline registrata è stata rispedita al target cambiando una
sola cosa, e la modifica è tracciata (`derived_from` + `replay_kind`) invece di essere una
richiesta nuova senza storia. Gli override sono un vocabolario **chiuso** (metodo, url/path/
query, header/cookie, body/form/json, rimozioni): nessuna shell, nessuna espressione.

---

## 7. Perché il buco era invisibile, e cosa è stato cambiato

Due cause indipendenti, entrambe silenziose.

**Causa 1 — il contesto non passava dal seam.** Il pod inoltra il contesto solo a un
esecutore la cui firma lo dichiara (ispezione della firma, per non rompere i fake a tre
argomenti). Il seam usato dal test aveva tre parametri, quindi il pod chiamava il terminale
**senza** contesto → kali non prendeva il lease → nessun redirect → nessuna cattura. Il
`default_exec_fn` di produzione invece lo dichiara: la produzione *avrebbe* catturato, ma
nessun test lo stava verificando, quindi il difetto è vissuto indisturbato.

**Causa 2 — le stats perdevano la copertura.** Le statistiche del job erano costruite con una
lista esplicita di campi, e il sotto-dizionario `capture` del pod non veniva mai fuso: anche
quando la cattura accadeva, `recon_jobs.stats` non poteva dirlo.

Tre cambi:

| Cambiamento | Effetto | File |
|---|---|---|
| il seam dichiara `capture_context` e lo inoltra; il pod lo costruisce e lo registra | il traffico del recon finisce nello store | `recon/domain/pod.py`, `recon/config.py` |
| `capture_job_stats` fonde i frammenti dei pod | `stats.capture = {sent, refs, warning}` verificabile a DB | `recon/control/pipeline.py` |
| l'`execute` di kali invoca `enforce_limits` (throttled, best-effort) | il tetto di storage esiste davvero | `kali/http_history/service.py`, `config.py`, `docker-compose.yml` |

Più un test E2E che asserisce la catena **intera** (tool log → stats → store → replay) e due
test veloci che pinnano la regressione silenziosa della firma.

---

## 8. Le decisioni di design (e perché)

| Decisione | Motivo |
|---|---|
| `spec_id` = discriminatore dell'asset del pod | è l'unica domanda che nessun altro campo risponde: *"cosa ha chiesto il pod incaricato di X"*. `run_id` dice il run, `session_id` dice l'iterazione, `exec_id` dice la chiamata |
| cattura **accesa di default**, kill-switch `POD_HTTP_CAPTURE=0` | il fallimento che chiude è la perdita silenziosa di evidenza riproducibile; i costi (fingerprint del proxy, latenza) sono visibili |
| `sent` separato da `refs` | "non ha mai chiesto la cattura" e "ha chiesto e non è arrivato niente" sono fatti diversi: il primo si tollera, il secondo è un guasto |
| `refs` sommati, `sent` in OR, warning distinti conservati | un job con più pod non deve né nascondere un guasto dietro un pod pulito, né dichiararsi catturato per merito di un solo pod |
| byte cap 1 GiB/progetto attivo, retention 0 | il cap copre la crescita illimitata; cancellare per età elimina evidenza **anche senza pressione di disco**, che è la deviazione consapevole |
| indice EAV (una riga per attributo) invece di un blob | "interrogabile per qualunque attributo" è un requisito dell'issue, non un extra; il pacchetto resta la verità, l'indice è la forma sparsa (Parte A) |

---

## 9. Limiti attuali (dichiarati)

| Limite | Cosa non copre | Dove è dichiarato |
|---|---|---|
| `REDIRECT` solo tcp/**80 e 443** | un job su porta non standard non viene registrato | Parte D, C.11 |
| cattura legata al **lease** (`project_id`) | un `execute_command` senza `project_id` (diagnostica manuale, script fuori dal percorso pod) non passa dal proxy | C.11, criterio 1 "parziale" |
| **pool** di namespace = `KALI_HTTP_NAMESPACE_POOL=8` (oggi = `MAX_PODS=8`) | oltre il pool il lease fallisce: il comando gira **comunque**, ma non catturato (fail-open). Ora lo dice: `stats.capture = {sent: true, refs: 0, warning: "capture unavailable: PoolExhaustedError…"}` | C.11, Parte D |
| **body cap** `KALI_HTTP_MAX_BODY_BYTES=5 MiB` | oltre la soglia il body non è salvato (`capture_state="omitted"`); un replay su una baseline con body dichiarato **rifiuta** invece di inventare | C.2 |
| **byte cap** 1 GiB/progetto | a saturazione i più vecchi artifact vengono evacuati (retention 0) | C.11, C.9 |
| **fingerprint TLS** | il target vede mitmproxy, non il client del pod | Parte B, C.11 |
| **solo HTTP(S) applicativo** | niente DNS/UDP, niente traffico del browser/DOM (quello è #51 / Steel) | Parte D |
| **lineage del replay** | l'artifact del replay porta `derived_from` e `replay_kind`, ma **non** eredita `run_id`/`spec_id` | C.11 |
| **assenza non dimostrabile** | si può provare che ogni invocazione ha riportato ref > 0 e che gli artifact sono nello store; non si può provare dall'esterno che **nessun** pacchetto sia sfuggito | C.11 |

---

## 10. Dove sta il codice

| Area | File |
|---|---|
| contesto di cattura e forwarding dal pod | `src/polymerhus/recon/domain/pod.py`, `src/polymerhus/recon/config.py` |
| aggregazione della copertura nelle stats del job | `src/polymerhus/recon/control/pipeline.py` |
| esecuzione, lease, ref lookup, tetto di storage | `kali/http_history/service.py` |
| lease di namespace e REDIRECT | `kali/http_history/namespaces.py` |
| proxying e normalizzazione del flow | `kali/http_history/addon.py`, `normalize.py`, `models.py` |
| store, indice EAV, retention/cap | `kali/http_history/store.py`, `index.py` |
| replay (piano + sender nel namespace) | `kali/http_history/replay.py`, `sender.py` |
| confine modello (sanitizzato, redazione) | `kali/http_history/sanitize.py` |
| superficie MCP | `kali/mcp_server.py` |
| client app-side per l'hunting | `src/polymerhus/app/clients/kali_http_history.py` |
| test | `tests/kali/*`, `tests/recon/test_pod_capture_context.py`, `tests/recon/test_pipeline.py`, `tests/e2e/test_recon_crawl_katana_depth.py`, `tests/e2e/test_http_proxy_history.py` |

---

## 11. Glossario minimo

| Termine | Significato qui |
|---|---|
| **artifact** | una transazione HTTP registrata, con id stabile (`http_01…`) |
| **capture context** | progetto/run/pod/asset a cui l'esecuzione appartiene |
| **exec_id** | identificatore di **una** chiamata a kali; è la chiave con cui si raccolgono gli artifact prodotti in quella finestra |
| **lease** | il prestito temporaneo di un namespace di rete dedicato, con il traffico web deviato sul proxy |
| **spec_id** | il discriminatore dell'asset del pod: "cosa stava lavorando questo pod" |
| **replay** | rispedire una baseline registrata cambiando solo override dichiarati, con lineage verso l'originale |
| **sanitizzato** | la vista per modello/Langfuse: nessun body, header/cookie sensibili redatti |
| **fail-open** | se la cattura non è disponibile il comando gira lo stesso, ma lo dichiara (`capture_warning`, `stats.capture`) |

---

## 12. Stato rispetto all'issue

Tre dei quattro criteri di #196 sono attuati e verificati (interrogabilità per attributo,
durabilità + id stabile, riferimento per identificatore dal pod/hunter). Il primo — *"ogni
request/response in uscita dal container kali è registrata"* — è **parziale**: vale per il
traffico in lease sulle porte 80/443. La tabella criterio-per-criterio, con i run di
accettazione, è in `http-proxy-history-hardening-decisions.md` §C.11.

### 12.1 Che endpoint è stato testato davvero

Sì, un endpoint HTTP **reale** — ma di **laboratorio**, non di produzione:

| | Valore |
|---|---|
| Target | `172.28.0.20:80`, container `http-e2e-target` (server HTTP python che risponde su `/` e `/robots.txt`) |
| Protocollo esercitato | **solo HTTP**, nessun TLS (negli artifact `connection.tls = false`) |
| Cosa è stato provato sul filo | richieste vere del processo del tool (httpx, katana) verso un socket vero, `200` con body di 65 byte, header di risposta reali |
| Cosa **non** è stato provato | un sito Internet, HTTPS/SNI, redirect/CDN, un target con WAF o challenge, porte ≠ 80 |
| Perché | il perimetro della prova è `172.28.0.20` (target nudo, mai URL) e la rete è quella del compose; i limiti che ne derivano sono elencati in §9 |

Conseguenza dichiarata: il costo del fingerprint TLS del proxy e la cattura su `:443` restano
**non misurati** qui, anche se il percorso è implementato (`REDIRECT` su tcp/80 e tcp/443).
