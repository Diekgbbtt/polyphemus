# HTTP Proxy History (#196) — Design e walkthrough

Questo è **l'unico** documento di design per la HTTP proxy history. Sostituisce il decision
record, i due walkthrough precedenti, la spec del 2026-09-12, i piani TDD e la pagina di
operations: tutto ciò che era sparso è stato fuso qui, con lo stato reale del codice.

Compagno di questo documento (e unico altro): `http-proxy-history-test-evidence.md`, che
raccoglie i run su ogni target esplorato, il confronto fra log delle chiamate e artifact, e il
verdetto su chiusura e merge.

Stato: **branch `feat/http-history-hardening`**, ultimo commit `4585251`.

---

## 1. Pre-issue: com'era il sistema, e cosa mancava davvero

### 1.1 Il terminale cieco

Kali era (per il resto del sistema) un terminale che esegue comandi:

```text
execute_command(command, session_id) -> {stdout, stderr, returncode, duration_ms}
```

Nessun proxy, nessun hook di trasporto, nessuna traccia di *cosa* il comando avesse chiesto ai
target. Le conseguenze non erano estetiche:

1. **Nessuna riproducibilità.** Il pod D6 registrava una `RawObservation` il cui `request` era la
   stringa del comando, con un `probe_ref` che ne era l'hash: da lì non si risale né a una
   richiesta strutturata né a una transazione. Una spec dell'hunting doveva **ri-scrivere** a mano
   metodo, URL, header, cookie, parametri e body nel `payload_vector_space`, perdendo lo stato
   autenticato di partenza e incoraggiando l'agente a ricostruire (o inventare) dettagli di
   trasporto.
2. **Nessuna attribuzione.** Ammesso di poter ricostruire una richiesta, non c'era modo di legarla
   al progetto, al run e all'unità di lavoro che l'aveva generata.
3. **Nessuna prova del contrario.** Langfuse è osservabilità esterna e best-effort; la capture
   browser di Steel è in-memory e deduplicata; il log D6 è command-shaped. Nessuno dei tre può
   rispondere a "quali transazioni HTTP ha fatto questo pod, e quale era la risposta?".

### 1.2 I quattro criteri di #196

| # | Criterio dell'issue | Dove è oggi |
|---|---|---|
| 1 | ogni request/response in uscita dal container kali è registrata, con ampiezza HAR-like | **parziale**: vale per il traffico **in lease** (con `project_id`) sulle porte **80/443** |
| 2 | gli artifact sono interrogabili per qualunque attributo registrato | **attuato** (indice EAV + FTS) |
| 3 | gli artifact sono durevoli e indirizzabili con un id stabile | **attuato** (SQLite + blob + ULID), con tetto di byte |
| 4 | una spec dell'hunter (o il pod) può riferire una richiesta sicura per identificatore | **attuato** (`request_ref` + tool `replay`, senza layer di validazione: ruling #191) |

### 1.3 I difetti che l'implementazione ha dovuto chiudere

Trovati per strada, in ordine di scoperta (tutti con prova, vedi §3 e il test evidence):

1. la filiera era cablata solo nei test: `search/get/replay` rispondevano `http_history_unavailable`
   in produzione, e il pod non aveva il tool di replay;
2. il runner del lease usava `bash -lc`: il profilo di login ricostruiva `PATH` e i tool
   risolvevano al binario sbagliato (o mancavano), con il banner MOTD in testa allo stdout;
3. il seam di esecuzione del recon non dichiarava `capture_context`: i pod giravano **senza
   lease**, quindi nulla veniva registrato — silenziosamente, con run verde;
4. la copertura di cattura del pod moriva nell'aggregazione: `recon_jobs.stats` non aveva la
   chiave `capture`, quindi non si poteva nemmeno sapere che la cattura non era avvenuta;
5. `enforce_limits` esisteva ed era testato, ma **nessuno lo invocava**: con la cattura accesa di
   default lo store cresceva senza limite;
6. dentro il namespace in lease **il DNS non esisteva** (il resolver del container è su
   `127.0.0.11`, cioè il loopback del *container*): il replay via `curl` non risolveva alcun
   hostname, e il difetto era invisibile al recon perché httpx/katana portano resolver propri;
7. il proxy **verifica** il certificato upstream: un target di laboratorio con certificato
   self-signed non era catturabile (502 al client), e installare la CA "alla Debian" non bastava
   perché mitmproxy verifica contro **certifi**, non contro lo store di sistema.

---

## 2. Post-issue: il design attuale

### 2.1 Architettura e confini

```text
┌────────────── processo agent (uvicorn :8080) ──────────────┐
│ API → pipeline recon → job agent (MAX_PODS) → POD          │
│                                   │ exec_fn(cmd, sid,      │
│                                   │  timeout, capture_ctx) │
└───────────────────────────────────┼────────────────────────┘
                                    │ MCP streamable-http :8000
┌────────────── container kali ─────┼────────────────────────┐
│ mcp_server.execute_command ──▶ HttpHistoryService          │
│        │                            │                      │
│        │                     LeaseManager.acquire          │
│        │                            │ namespace + REDIRECT │
│        │                            ▼  (tcp/80, tcp/443)   │
│        │                    tool in 172.30.0.x             │
│        │                            │ HTTP/HTTPS           │
│        │                     mitmdump ──▶ target           │
│        │                            │                      │
│        │                     addon + normalizer ──▶ store  │
│        └── refs = search(context/exec_id) ◀────────┘       │
└────────────────────────────────────────────────────────────┘
                     frontiera del modello: solo view sanificate
```

| Confine | Regola |
|---|---|
| pod ↔ target | il pod non apre connessioni proprie: senza `exec_fn` non c'è cattura |
| agent ↔ kali | solo il contratto MCP; niente memoria o filesystem condivisi |
| kali ↔ target | il traffico esce dal namespace del lease (sorgente `172.30.0.x`), mai dall'IP del container |
| store ↔ modello | body e segreti non attraversano: solo `size`/`capture_state` e valori redatti |

Quattro unità indipendenti, come da design originale: **capture plane** (mitmproxy, routing
trasparente, normalizzazione), **store** (id immutabili, indice, blob content-addressed),
**access plane** (MCP search/get/replay con isolamento per progetto), **integrazione** (contesto
di cattura, riferimenti D6, risoluzione deterministica di `request_ref`).

### 2.2 Walkthrough: la vita di una richiesta

```text
1.  il pod costruisce il contesto: project_id, run_id, spec_id (asset), session_id
      - spec_id = discriminatore dell'asset del pod (url, altrimenti hash stabile)
2.  exec_fn(command, session_id, timeout_s, capture_context)   [solo se il seam lo dichiara]
3.  MCP execute_command(...) → il servizio minta un exec_id per QUESTA chiamata
4.  acquire di un lease: namespace dedicato + veth 172.30.0.<n> + REDIRECT tcp/80 e tcp/443
5.  il namespace riceve il suo /etc/resolv.conf: nameserver = gateway del lease
      (il forwarder sul gateway inoltra al resolver del container: nomi compose e pubblici)
6.  il tool gira con `ip netns exec`; il suo traffico web finisce su mitmdump
7.  l'addon risolve la sorgente (registry source_ip → contesto) e normalizza il flow
8.  il record è scritto nello store del progetto; i body vanno in blob content-addressed
9.  a fine comando, in un `finally`: refs = search(context/exec_id == exec_id) → release del lease
10. il pod scrive l'esito nella sua export: stats.capture = {sent, refs, warning}
11. la pipeline fonde le export dei pod in recon_jobs.stats[].capture
12. (throttled, best-effort) enforce_limits sul progetto: byte cap
```

Il passo 3 e il passo 9 sono la spina dorsale della correlazione: **l'`exec_id` è mintato dal
servizio**, non dal chiamante, e la ricerca a fine comando è l'unica cosa che lega una lista di
artifact alla singola chiamata — anche con più pod in parallelo. Il passo 9 sta in `finally`
perché un comando che esplode non deve lasciare appeso un lease né perdere gli artifact già
registrati.

### 2.3 Il modello dati

```text
/data/<project_id>/http-history/
├── history.sqlite3          (WAL)
└── bodies/<sha256>.blob
```

| Tabella | Contenuto |
|---|---|
| `flows` | una riga per artifact: `record_json` (la verità, schema `http-artifact/v1`) + `created_at` |
| `attributes` | indice sparsa `(side, namespace, key, text_value|numeric_value)` per OGNI scalare |
| `flows_fts` | full-text su url/header/marker del body |
| `bodies` | blob content-addressed + riferimento, con GC di quelli non più usati |
| `meta` | audit dell'ultima potatura |

Un artifact: `artifact_id` (ULID), `project_id`, `capture_context` (session/run/spec/variant/
exec/derived_from/replay_kind), `request` e `response` (versione, metodo/status, header, cookie,
query/form, body con `size`/`encoding`/`capture_state`), `connection` (indirizzi, protocollo,
tls, sni, alpn), `timings`, `error`, `derived_from`, `replay_kind`, `created_at`.

Scelte e perché:

| Scelta | Motivo |
|---|---|
| documento completo per artifact | autosufficiente: si legge senza join |
| indice EAV invece di un blob unico | "interrogabile per qualunque attributo" senza migrazioni di schema |
| body come blob content-addressed | dedup, e il body non entra mai nelle viste modello |
| `capture_state` esplicito (`none/empty/captured/omitted/truncated`) | mai una troncatura silenziosa |
| lineage `derived_from` + `replay_kind` | un replay è una richiesta **con storia** |
| prefisso ULID `http_` | stabile, ordinabile, indirizzabile |

### 2.4 Interrogare l'indice

Ogni riga dell'indice è `(side, namespace, key, valore)`. `side` ∈
`{request, response, connection, context, timing}`; `namespace` ∈
`{core, header, cookie, query, form, body, tls}`. I filtri sono congiuntivi e supportano
`eq | contains | prefix | gte | lte | absent` (più la ricerca full-text), sempre ristretti dal
`project_id` prima di applicare i filtri utente. Esempi reali:

```text
context/core/run_id      eq      <run>              tutto il traffico di un run
context/core/spec_id     eq      <asset>            cosa ha chiesto il pod che lavorava X
response/core/status     eq      200                per esito
request/header/user-agent contains Firefox          per client
body/body/marker         contains marker=            per marcatore nel corpo
```

### 2.5 I contratti

| Seam | Firma essenziale |
|---|---|
| esecuzione dal pod | `exec_fn(command, session_id, timeout_s, capture_context=None) -> ExecResult{stdout, stderr, returncode, duration_ms, exec_id, http_artifact_refs, capture_warning}` |
| esecuzione MCP | `execute_command(command, session_id, timeout_s, project_id, run_id, spec_id, variant_ref, derived_from, replay_kind)` — retro-compatibile |
| ricerca | `search_http_history(project_id, filters, cursor, limit, text) -> {summaries, next_cursor}` |
| lettura | `get_http_artifact(project_id, artifact_id, include_body=False)` — `include_body=True` rifiutato qui |
| replay | `replay_http_request(project_id, artifact_id, overrides, capture_context)` |
| stato | `proxy_status() -> {mcp, proxy, routing, namespaces, store, capture}` |
| aggregazione | `capture_job_stats(pod_exports) -> {sent, refs, warning}` |

Il vocabolario degli override di replay è **chiuso**: `method`, `url`/`path`, `query`,
`header(s)`, `cookie(s)`, `remove_header(s)`, `body`/`form`/`json`. Mai un comando shell, mai
un'espressione. La proprietà è asimmetrica di proposito: il **contesto** è del chiamante, l'**id**
e il **record** sono di kali, la **fusione** è della pipeline.

Configurazione (compose → container kali):

| Variabile | Default | Significato |
|---|---|---|
| `KALI_HTTP_CAPTURE_ENABLED` | `true` | interruttore diagnostico |
| `KALI_HTTP_HISTORY_ROOT` | `/data` | radice dello store (volume) |
| `KALI_HTTP_MAX_BODY_BYTES` | 5 242 880 | cap per body; oltre → `omitted`, mai troncato in silenzio |
| `KALI_HTTP_NAMESPACE_POOL` | 8 | lease concorrenti |
| `KALI_HTTP_LEASE_TTL_S` / `KALI_HTTP_ACQUIRE_TIMEOUT_S` | 900 / 30 | TTL e backpressure (`PoolExhaustedError`) |
| `KALI_HTTP_PROXY_HOST` / `PORT` | `127.0.0.1` / `8080` | listener di mitmdump |
| `KALI_HTTP_RETENTION_S` | `0` | retention per età (0 = non cancellare) |
| `KALI_HTTP_PROJECT_MAX_BYTES` | `1073741824` | tetto byte per progetto (1 GiB) |
| `KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S` | 60 | throttle del trimmer |
| `KALI_HTTP_UPSTREAM_CA` | *(vuoto)* | CA dell'operatore per upstream self-signed |
| `POD_HTTP_CAPTURE` (lato agent) | `1` | kill-switch della cattura nel pod |

### 2.6 I due prerequisiti di rete e trust (imparati sul campo)

**DNS nel lease.** Il container riceve da Docker `nameserver 127.0.0.11`, che è il resolver
embedded di Docker **sul loopback del container**: in un namespace figlio quell'indirizzo è il
loopback *del namespace*, e non risponde. Ogni lease scrive quindi il proprio
`/etc/resolv.conf` (che `ip netns exec` bind-monta da `/etc/netns/<ns>/`) con il **gateway del
lease** come primo nameserver, e un `DnsForwarder` inoltra da lì al resolver del container: il
lease vede le stesse risposte (nomi del compose e nomi pubblici). `/etc/hosts` viene copiato nel
namespace per non perdere gli alias. Un listener per gateway, legato alla vita del lease; una
query non inoltratile viene scartata, mai inventata. Solo UDP (dichiarato).

**Trust upstream.** mitmdump verifica il certificato del sito che registra. Per un target con
certificato self-signed l'operatore punta `KALI_HTTP_UPSTREAM_CA` a un file contenente la sua
CA, e la bootstrap fa **due** cose: la installa nello store di sistema (serve ai client dentro
il lease, es. il `curl` del replay) **e** costruisce un bundle `store di default + CA operatore`
che l'entrypoint passa a mitmdump via `ssl_verify_upstream_trusted_ca`. La seconda è
indispensabile: mitmproxy verifica contro **certifi**, non contro lo store di sistema — un
primo run lo ha dimostrato fallendo con lo stesso errore subito dopo che `curl` aveva iniziato a
funzionare. Si è preferito questo a `ssl_insecure` (che accetterebbe **qualsiasi** upstream, e
in un piano che registra prove significherebbe fidarsi del peer sbagliato). Il flag è
**opt-in**: il bundle vive sul volume, ma senza il knob non viene usato.

### 2.7 Fail-open e fail-closed

| Situazione | Comportamento | Perché |
|---|---|---|
| proxy irraggiungibile | comando eseguito, `capture_warning` valorizzato, `refs=[]` | la ricognizione non deve morire per un guasto del recorder |
| pool di namespace esaurito | idem, con `PoolExhaustedError` nel warning | degrado **dichiarato**, visibile in `stats.capture` |
| exec fuori dal percorso pod (nessun `project_id`) | nessun lease, nessuna cattura, nessun errore | la cattura è per progetto |
| body oltre il cap | artifact registrato, `capture_state="omitted"` | si perde il contenuto, non la transazione |
| replay su baseline con body dichiarato ma assente | **rifiutato** (`body_unavailable`) | fail-closed: un replay senza corpo falsificherebbe l'esperimento |
| lookup cross-progetto / id inesistente | `not_found` | nessuna enumerazione tra progetti |
| indice corrotto | ricostruibile dal `record_json` | l'indice è derivato, il documento è la verità |

### 2.8 Invarianti

1. **La cattura non è mai un gate**: nessun percorso di recon degrada perché il recorder è giù.
2. **Il fallimento è visibile**: `sent` distingue "non ho chiesto" da "ho chiesto e non è arrivato
   niente"; `refs=0` con `sent=true` non può passare per cattura riuscita.
3. **Un solo scrittore per verità**: il record lo scrive il proxy, la sanitizzazione è una
   proiezione.
4. **Il confine del modello è esplicito**: ciò che non è nella proiezione (body, `source_ip`,
   header sensibili) non esiste per il modello; i segreti restano nello store solo per il replay.
5. **La lineage non si perde**: ogni replay porta `derived_from`; ogni artifact porta il contesto
   dell'esecuzione.
6. **I limiti sono dichiarati dove mordono**: cap del body, tetto di byte, pool, porte redirette.

### 2.9 Le decisioni, e perché

| Decisione | Perché |
|---|---|
| mitmproxy **dentro** kali, routing trasparente | niente sidecar, niente nuova frontiera di routing; kali ha già `NET_ADMIN` |
| proxy **passivo** | registra, non modifica: una modifica al traffico falserebbe le misure |
| `exec_id` mintato dal servizio + registry `source_ip → contesto` | la correlazione non dipende da finestre temporali o dall'ordine dei comandi |
| lease per esecuzione | isolamento e attribuzione; il pool dà backpressure esplicita |
| pacchetto come verità + indice EAV + FTS | interrogabilità senza migrazioni, documento autosufficiente |
| body content-addressed con `capture_state` | dedup e nessuna troncatura silenziosa |
| `spec_id` = asset del pod | risponde a "cosa ha chiesto il pod incaricato di X", che nessun altro campo copre |
| cattura **accesa di default** + `POD_HTTP_CAPTURE=0` | il fallimento che chiude è silenzioso; i costi sono visibili |
| tetto di byte 1 GiB + retention **0** | il cap copre la crescita; cancellare per età elimina evidenza senza pressione di disco |
| `capture_context` inoltrato per ispezione della firma | i fake a tre argomenti continuano a funzionare; nessuna rottura dei test |
| CA operatore invece di `ssl_insecure` | fidarsi di qualsiasi upstream falsifica ogni artifact |

---

## 3. Pre → post: i difetti chiusi

| # | Sintomo (pre) | Causa | Fix | Prova |
|---|---|---|---|---|
| 1 | `search/get/replay` → `http_history_unavailable`; il pod non aveva il tool di replay | i callable non erano iniettati nel builder di produzione | client sync app-side + binding in `runtime.py` (`search/get` nell'hunter, `replay` nel pod) | 14 test in `tests/attack`; gate live `tests/e2e/test_http_proxy_history.py` |
| 2 | `httpx` risolveva al CLI Python, `katana`/`naabu`/… "MISSING", banner MOTD nello stdout | runner del lease con `bash -lc` (il profilo ricostruisce `PATH`) | runner non-login (`bash -c`) + guard del MOTD in `postrun.sh` | preflight del lease via MCP: `/root/go/bin/httpx`, `status_code=200`, `rc=0`, nessun banner |
| 3 | tool log con `http_artifact_refs: []`, store vuoto, run verde | il seam di test non dichiarava `capture_context` → nessun lease | seam capture-aware + forwarding condizionato dalla firma | `tests/recon/test_pod_capture_context.py`, e2e live |
| 4 | `recon_jobs.stats` senza chiave `capture` | il frammento del pod non veniva fuso | `capture_job_stats` additivo (`refs` somma, `sent` OR, warning conservati) | unit + e2e (`stats.capture` per job) |
| 5 | store senza limite, `enforce_limits` mai chiamato | nessun chiamante in produzione | invocazione throttled e best-effort dall'`execute` + cap 1 GiB | `tests/kali/test_http_history_service.py` |
| 6 | `curl` nel lease: `Could not resolve host` (rc 6) | `/etc/resolv.conf` copiato puntava al resolver del container | resolver per-lease sul gateway + `DnsForwarder` + copia di `/etc/hosts` | 7 test + prova live (`getent`, `curl`, replay HTTPS) |
| 7 | HTTPS verso target self-signed: 502, artifact con `Certificate verify failed` | mitmdump verifica l'upstream contro certifi | `KALI_HTTP_UPSTREAM_CA` → store di sistema **e** bundle per il proxy (opt-in) | 6 test + run su `soupmarket.shop` (36 transazioni TLS, 0 errori) |

### 3.1 Cosa **non** è cambiato (e va bene così)

Il delta report del recon (stdout dei tool ↔ grafo) è rimasto identico: la cattura è un livello
**in più**, non un percorso alternativo. Il controllo positivo del gate, le guardie di lancio
(400 su seed mancante, su IPv6, su job sconosciuti), il comando katana byte-identico al template
e `-ct 240s` non sono stati toccati.

---

## 4. Moduli e file

| Area | File |
|---|---|
| contesto di cattura e forwarding dal pod | `src/polymerhus/recon/domain/pod.py`, `src/polymerhus/recon/config.py` |
| copertura di cattura nelle stats del job | `src/polymerhus/recon/control/pipeline.py` |
| client app-side (hunting) | `src/polymerhus/app/clients/kali_http_history.py` |
| superficie MCP | `kali/mcp_server.py` |
| esecuzione, lease, ref lookup, limiti, replay | `kali/http_history/service.py` |
| lease di namespace, resolver per-lease | `kali/http_history/namespaces.py`, `kali/http_history/dns.py` |
| trust upstream (CA + bundle) | `kali/http_history/trust.py`, `kali/postrun.sh`, `kali/entrypoint.sh` |
| proxying e normalizzazione | `kali/http_history/addon.py`, `normalize.py`, `models.py` |
| store, indice, FTS, retention/cap | `kali/http_history/store.py`, `index.py` |
| replay (piano + sender nel namespace) | `kali/http_history/replay.py`, `sender.py` |
| confine modello | `kali/http_history/sanitize.py` |
| fixture e2e (target, WAF, challenge, preflight) | `tests/e2e/http_e2e_target.py`, `http_challenge_target.py`, `tcp_forwarder.py`, `docker-compose.e2e.yml` |

Test: `tests/kali/*` (contratto dello store e della superficie MCP), `tests/recon/test_pod_capture_context.py`
(contesto e copertura nel pod), `tests/recon/test_pipeline.py` (aggregazione),
`tests/e2e/test_recon_crawl_katana_depth.py` (gate live crawl-only + cattura + replay),
`tests/e2e/test_http_proxy_history.py` (gate storico #196), `tests/attack/*` (binding dei tool).

---

## 5. Limiti e rischi residui

| Limite | Effetto | Trigger per riaprirlo |
|---|---|---|
| cattura solo **in lease** e solo su **tcp/80 + tcp/443** | traffico su porte non web non registrato; un `execute_command` senza `project_id` non passa dal proxy | un job reale su porta non standard, o la necessità di cattura fuori dal percorso pod |
| **QUIC/HTTP3** rifiutato (UDP/443) e dichiarato | un client che insiste su HTTP/3 non viene catturato | target che serve solo HTTP/3 |
| **pool** di namespace = `MAX_PODS` (8) | oltre il pool: degrado fail-open, visibile in `stats.capture` | concorrenza per job superiore al pool |
| **fingerprint TLS** del proxy | il target vede mitmproxy, non il tool | WAF che verifica il fingerprint (misurato: Cloudflare su `example.com` non ha bloccato) |
| **retention 0** + tetto 1 GiB/progetto | a saturazione i più vecchi artifact vengono evacuati | necessità di conservazione a lungo termine su progetti grandi |
| body cap 5 MiB | oltre: `omitted`, replay rifiutato se il body è dichiarato | payload grandi ricorrenti |
| **challenge WAF non rilevata** a valle (C.3/E.2) | una pagina di sfida viene ingerita come superficie applicativa: evidenza che *sembra* pulita | decidere E.2: etichettare `inconcludente`, mai `symptom-confirmed` |
| **telemetria dei tool** nello store | httpx/katana contattano `api.pdtm.sh`: 2 artifact per run con un `machine_id` | rumore nelle query, o policy su identificatori di macchina |
| CA fornita dall'operatore | il target self-signed è catturabile solo con `KALI_HTTP_UPSTREAM_CA` | — (per design: la fiducia è una decisione) |
| client con **certificate pinning** | osservabili solo come flow falliti/incompleti | target mobile/desktop con pinning |

---

## 6. Stato dell'issue e merge readiness

### 6.1 #196 è "fixato"?

Tre criteri su quattro sono **attuati e verificati** (interrogabilità per attributo, durabilità +
id stabile, riferimento per identificatore da pod/hunter). Il primo — "ogni request/response in
uscita dal container kali è registrata" — è **parziale per costruzione**: vale per il traffico
**in lease** sulle porte **80/443**.

Quindi la risposta è: **sì, con una dichiarazione di scope**, oppure no se il criterio 1 va letto
alla lettera ("*ogni* richiesta del container"). Le due strade:

1. **chiudere** con la nota: "registrazione per il traffico delle esecuzioni legate a un progetto,
   sulle porte web, con degrado fail-open dichiarato in `stats.capture`";
2. **tenere aperto** con un follow-up tracciato per il residuo (exec fuori dal percorso pod, porte
   non web, QUIC).

In entrambi i casi resta fuori dalla chiusura il punto **E.2** (sfida WAF non interpretata):
la cattura è completa, l'interpretazione no — è una lacuna *dichiarata*, non un silenzio, ma è
esattamente la classe di errore ("evidenza che sembra pulita") che la Parte B del design
considerava la più pericolosa.

### 6.2 Si può mergiare?

**Sì**, il branch è mergiabile, con queste precondizioni operative:

| Precondizione | Stato |
|---|---|
| albero di lavoro pulito | **no**: tre `PROMPT-*.md` risultano cancellati e non committati (residuo di sessioni precedenti) più un prompt untracked. Vanno ripristinati o committati *prima* del merge |
| nessun segreto nel repo | sì: la CA del laboratorio vive in un volume docker (`/data/upstream-ca.crt`), il symlink `.env` del worktree è git-ignored, negli artifact/doc non ci sono credenziali |
| test verdi | sì: unit tier del capture plane e del pod, gate live su tre target (numeri nel test evidence) |
| nessun comportamento nuovo non dichiarato | sì: il DNS per-lease è un fix sempre attivo e testato; il trust upstream è **opt-in**; il tetto di byte ha un default ma è throttled e best-effort |
| documentazione consolidata | sì: questo documento + il test evidence; le sette pagine precedenti sono state rimosse |
| codice servito in produzione | **da fare al deploy**, non al merge: l'immagine agent non monta `src/`, quindi serve un **rebuild** (CI) perché il branch sia attivo; per kali basta `--force-recreate` (monta `./kali`) |

Sequenza consigliata: pulire l'albero → rebase sul branch di destinazione → rebuild
`polymerhus-agent` → `up -d --force-recreate kali agent` → rieseguire `tests/kali`,
`tests/e2e/test_http_proxy_history.py` e `tests/e2e/test_recon_crawl_katana_depth.py` →
merge.

### 6.3 Follow-up consigliati (non bloccanti)

1. **E.2 — challenge detection**: usare i marker che già registriamo (`cf-mitigated`, `cf-ray`,
   interstitial) per etichettare la sfida come inconcludente, mai `symptom-confirmed`.
   Il fixture è pronto e il test nasce rosso.
2. **Ignore-list della telemetria dei tool** (`api.pdtm.sh`) per non sporcare le query per run.
3. **Porte non web / QUIC**: decisione di topologia (Parte D del vecchio record, qui §5).
4. **CA fornita dall'operatore** come parte del deploy (non estratta dall'handshake).

---

## 7. Glossario

| Termine | Significato |
|---|---|
| **artifact** | una transazione HTTP registrata, con id stabile (`http_01…`) |
| **capture context** | progetto/run/pod/asset a cui un'esecuzione appartiene |
| **exec_id** | identificatore di **una** chiamata a kali; chiave di raccolta degli artifact di quella finestra |
| **lease** | prestito temporaneo di un namespace di rete con il traffico web deviato sul proxy |
| **spec_id** | discriminatore dell'asset del pod: "cosa stava lavorando questo pod" |
| **replay** | rispedire una baseline registrata cambiando solo override dichiarati, con lineage |
| **sanitizzato** | vista per modello/Langfuse: nessun body, valori sensibili redatti |
| **fail-open / fail-closed** | la cattura degrada dichiarando; la risoluzione di un riferimento fallisce invece di approssimare |
| **`stats.capture`** | `{sent, refs, warning}` per job: la prova, a DB, di cosa è stato catturato |
