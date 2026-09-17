# HTTP Proxy History (#196) — Test evidence

Risponde a tre domande, con i numeri dei run reali:

1. **cosa è stato testato e con che esito**, su ogni target esplorato;
2. **che differenza c'è fra il log delle chiamate e gli artifact** salvati;
3. **a che punto siamo**: l'issue è dichiarabile fixata, e il branch è mergiabile.

Design e architettura: `http-proxy-history-design.md`.

---

## 1. I target esplorati

| Target | Cos'è | Cosa esercita | Esito |
|---|---|---|---|
| `172.28.0.20` (IP lab) | server HTTP deterministico del compose (`http-e2e-target`) | gate crawl-only, delta report, cattura HTTP | **verde** |
| `example.com` (Internet, HTTPS) | dominio IANA dietro Cloudflare | TLS reale, DNS pubblico, CDN/WAF observation | **verde** |
| `soupmarket.shop` (lab HTTPS) | OWASP Juice Shop dietro nginx, certificato **self-signed** — il target degli e2e del 16-20 luglio | TLS con CA dell'operatore, replay su dominio | **verde** (dopo il fix CA) |
| `172.28.0.21` (fixture WAF) | OWASP **ModSecurity CRS** dietro un forwarder TCP trasparente | blocco 403 su payload, controllo 200 | **verde** |
| `172.28.0.22` (fixture challenge) | challenge in stile vendor (`cf-ray`, `cf-mitigated`) con cookie come controllo | cattura della sfida + **interpretazione** a valle | cattura **verde**, interpretazione **lacuna misurata** |

Tutti i target sono dell'operatore o pubblici e autorizzati: niente siti di terzi dietro WAF
(non autorizzabili, e senza poter spegnere la difesa non esisterebbe controllo).

---

## 2. Log delle chiamate vs artifact: due registri, due punti di vista

Il sistema produce **due** tracce di ogni esecuzione, e non sono intercambiabili:

| | **Log delle chiamate** (tool log / stdout dei tool) | **Artifact** (HTTP history) |
|---|---|---|
| Cos'è | il punto di vista del **processo** | il punto di vista del **filo** |
| Chi lo scrive | il chiamante (test/recon) e il tool stesso | mitmproxy + addice |
| Contenuto | comando eseguito, stdout/stderr integrali, `returncode`, durata, `session_id` | metodo/URL/versione, header inviati, cookie, query, form, status, header di risposta, body (`size`/`capture_state`), connessione (indirizzi, protocollo, TLS/SNI/ALPN), tempi, errori |
| La richiesta inviata | **solo se il tool la stampa** | sempre, decodificata |
| La risposta | **solo i campi che il tool espone** | completa, come è arrivata |
| Identificatore riusabile | no (è testo) | `artifact_id` ULID |
| Riproducibile | no | sì, con override dichiarati e lineage |
| Correlazione | `session_id` nel nome del file/riga | `capture_context` completo (progetto/run/pod/asset/exec) |
| Granularità | una riga per invocazione | una riga per **transazione** (un comando ne fa N) |

Il ponte fra i due è `http_artifact_refs`: la lista di id che il terminale restituisce al pod a
fine chiamata, cercata per `exec_id`. Senza quel campo, i due registri non sono collegabili — ed
è esattamente lo stato in cui versava il recon prima di questo lavoro.

### 2.1 Affiancati, sullo stesso fatto

**a) httpx, target IP lab** — il tool log contiene la riga JSON che httpx ha stampato:

```json
{"timestamp":"2026-09-17T10:31:12.048Z","port":"80","url":"http://172.28.0.20","method":"GET",
 "host":"172.28.0.20","path":"/","header":{...},"time":"5.247108ms","tech":["Python:3.12.14"],
 "status_code":200,"content_length":65,"failed":false}
```

L'artifact della **stessa** richiesta contiene ciò che quella riga non ha:

```json
{"artifact_id":"http_01M2QEQ7DC6JM96BB3JFSFR20W",
 "capture_context":{"run_id":"ef27ec78-…","spec_id":"172.28.0.20","exec_id":"01M2QEQ6R87S521V843ZASWRV5"},
 "request":{"method":"GET","url":"http://172.28.0.20/","headers":[["Host","172.28.0.20"],
            ["User-Agent","…Firefox/124.0"],["Accept-Charset","utf-8"],["Connection","close"]]},
 "response":{"status":200,"headers":[["Server","BaseHTTP/0.6 Python/3.12.14"],["Content-Length","65"],
             ["X-E2E-Target","http-e2e-target"]]},
 "connection":{"client_address":"172.30.0.2:37820","server_address":"172.28.0.20:80","tls":false},
 "timings":{"total_ms":1.96}}
```

Il `User-Agent` inviato **non esiste** nel log di httpx: senza artifact, "quale richiesta ho
fatto?" è irrispondibile.

**b) katana, stesso target** — il log contiene il `raw` della richiesta e della risposta perché
*katana sceglie di stamparli*; è un caso fortunato, non una garanzia: nessun altro tool del
fleet lo fa, e il log resta comunque privo di id, contesto e connessione.

**c) dominio reale (soupmarket.shop)** — l'artifact della radice porta header che il log non
mostra (`Server: nginx/1.30.1`, `X-Frame-Options`, `Content-Encoding: gzip`), la dimensione reale
del body (3098 B), l'ALPN negoziato e l'indirizzo sorgente nel namespace del lease
(`172.30.0.2`): la prova che la richiesta è passata dal percorso di cattura.

**d) WAF** — il log dice `code=403`; l'artifact dice **403 di chi**: la pagina dell'engine, il
body (146 B), e nel caso della challenge i marker `cf-ray` / `cf-mitigated` che il log non
riporta affatto.

### 2.2 Cosa resta solo nel log

Per completezza, l'inverso: il log è l'unico posto dove si vede **come il tool ha interpretato**
ciò che ha visto (le sue conclusioni: `tech`, `words`, `lines`, `knowledgebase`), il suo
`returncode`, lo stderr, e i file di stdout integrali — cioè il materiale su cui il recon
costruisce il delta report. I due registri sono complementari: il log dice *cosa il tool ha
capito*, l'artifact dice *cosa è successo sul filo*.

---

## 3. Esiti per target

### 3.1 IP lab, HTTP, crawl-only (`httpx` + `katana -d 3`)

```text
project 81aa8c04-1849-4255-a6b3-b9dc8d92cc33   run ef27ec78-dca0-4f17-95bb-749d5e76e53a
wall 13.9 s   httpx success 637 ms   katana success 10.613 s
```

| Voce | Valore |
|---|---|
| `stats.capture` | httpx `{sent: true, refs: 1}`, katana `{sent: true, refs: 2}` |
| artifact del run | 3: `GET /` (httpx), `GET /` e `GET /robots.txt` (katana), tutti 200 |
| `spec_id` | httpx `172.28.0.20` (seed), katana `http://172.28.0.20` (BaseURL) |
| replay | baseline httpx + header dichiarato → `200`, `replay_kind=mutated` |
| delta report | `total=8 kept=8 dropped=0 collected=1 unexplained=0` in entrambe le direzioni |
| gate control | positivo (`out_of_scope_host`, `static_presentational_endpoint`) |
| orchestratore | 1 attore, **0 turni**, `steering_signal_reads=[0,0]` |

### 3.2 Internet, HTTPS (example.com)

| Voce | Valore |
|---|---|
| artifact | `GET https://example.com/` → 200, `tls=true`, `sni=example.com`, `Server: cloudflare`, 33.9 ms |
| interpretazione | httpx classifica `cdn_name=cloudflare`, `cdn_type=waf` |
| replay | `GET https://example.com/` con mutazione → **200**, `tls=true` |
| nota | questa è la prova che TLS viene **intercettato** e registrato su Internet, non solo in lab |

### 3.3 Lab HTTPS self-signed (soupmarket.shop) — e il fix CA

Prima del bundle CA (fase intermedia, dopo aver installato la CA solo nello store di sistema):

| | Valore |
|---|---|
| artifact sul target | 3, tutti con `error = "Certificate verify failed: self-signed certificate"`, `tls=false` |
| `stats.capture` | `{sent: true, refs: 2|3}` — ma il traffico non è ispezionabile |

Dopo il bundle (`ssl_verify_upstream_trusted_ca`, opt-in via `KALI_HTTP_UPSTREAM_CA`):

```text
project 4991ff4e-cd40-4d3b-ac77-10b5cbb88f31   run 1217282a-000a-4512-ab4e-1053f66463d9
wall 20.2 s   httpx refs 2 / 16 asset   katana refs 36 / 293 asset
```

| Voce | Valore |
|---|---|
| artifact | 36 sul target, **tutti** `tls=true` / `sni=soupmarket.shop`, zero errori di trasporto |
| status | `200 ×24`, `401 ×4`, `500 ×8` — tutti risposte **dell'applicazione** (`error = null`) |
| replay | `GET https://soupmarket.shop/` con mutazione → **200**, `derived_from` presente |
| grafo | 39 nodi: Domain 1, BaseURL 1, Endpoint 11, Header 24, Technology 1, Parameter 1 |

### 3.4 Fixture WAF (ModSecurity CRS) — blocco e controllo

Quattro richieste via lease, tutte con `capture_warning: null`:

| Prova | Status | Difesa registrata |
|---|---|---|
| payload XSS | **403** | pagina di blocco dell'engine, body 146 B |
| **controllo** (query benigna) | **200** | risposta dell'app, body 71 B |
| challenge | **403** | `cf-ray`, `cf-mitigated: challenge`, body 277 B |
| **controllo** (cookie) | **200** | risposta dell'app, body 65 B |

**Replay** (mutazione dichiarata su ogni baseline): blocco → 403/146 B, controllo → 200/71 B,
challenge → 403/277 B, controllo con cookie → 200/65 B. Ogni replay è un artifact nuovo con
`derived_from` e la mutazione visibile sul wire: gli artifact sono **riutilizzabili**, non solo
salvati.

### 3.5 Challenge vista dal recon: la lacuna misurata

```text
run 3e2d2e22-ecc2-45fe-babd-a348b7c614dc   status complete   wall 15.1 s
httpx   success   capture {sent:true, refs:2}   10 asset
katana  success   capture {sent:true, refs:3}   10 asset
grafo: 15 nodi — IP 1, BaseURL 1, Endpoint 1, Header 10, Technology 2
  BaseURL http://172.28.0.22   server = "… cloudflare"   title = "Just a moment..."
  Header cf-ray, cf-mitigated   (persistiti, non interpretati)
```

La cattura è corretta; **l'interpretazione no**: la pagina di sfida è diventata superficie
applicativa. I marker sono già nello store, quindi il fix è a valle (E.2) e non richiede di
toccare il capture plane.

---

## 4. Regressioni e gate

| Tier | Comando | Esito |
|---|---|---|
| capture plane (kali) | `pytest tests/kali -q -p no:cacheprovider` | **128 passed**, zero skip |
| contesto di cattura nel pod | `pytest tests/recon/test_pod_capture_context.py tests/recon/test_jobs.py -q` | **51 passed** |
| aggregazione stats | `pytest tests/recon/test_pipeline.py -q -p ambient_ticker` | **25 passed** (478 s) |
| binding dei tool (hunting) | `pytest tests/attack/test_http_history_wiring.py tests/attack/test_kali_http_history_client.py tests/attack/pod/test_replay_tool.py tests/attack/test_http_history_tools.py -q` | **14 passed** |
| gate live crawl-only + cattura + replay | `pytest tests/e2e/test_recon_crawl_katana_depth.py -q -s` | **3 passed** (2 seam + 1 live) |
| gate live #196 (storico) | `KALI_MCP_URL=http://localhost:8000/mcp pytest tests/e2e/test_http_proxy_history.py -q` | **1 passed**, zero skip |

Nota ambientale dichiarata: in questa sandbox `asyncio.run` + `asyncio.to_thread` non torna mai
da `loop.shutdown_default_executor()`; il tier della pipeline è stato eseguito **per file** con
un plugin di test fuori dal repo che neutralizza quell'attesa. Non è una modifica di prodotto e
non tocca il codice.

---

## 5. Verdetto

### 5.1 L'issue #196 è fixata?

**Tre criteri su quattro sono attuati e verificati; il primo è parziale per costruzione.**

| Criterio | Verdetto | Evidenza |
|---|---|---|
| ogni request/response outbound del container kali è registrata | **parziale**: traffico in lease (con `project_id`) sulle porte 80/443 | §3.1-§3.4: ogni esecuzione con contesto ha prodotto artifact; il resto non è catturabile per design dichiarato |
| interrogabile per qualunque attributo | **sì** | query per `context/run_id`, `context/spec_id`, status, header, marker del body |
| durevole e con id stabile | **sì**, con tetto di byte (1 GiB/progetto) e retention 0 | artifact ancora presenti dopo i run; replay riusciti sugli id salvati |
| riferimento per identificatore da spec/pod | **sì** | `request_ref` + tool `replay` cablati in produzione (14 test), replay live su 4 baseline |

Quindi: **si può dichiarare la #196 fixata solo accompagnandola da una nota di scope** ("traffico
di esecuzione legato a un progetto, porte web, degrado fail-open visibile in `stats.capture`"),
oppure la si tiene aperta per il residuo (exec fuori dal percorso pod, porte non web, QUIC).

**Fuori da entrambe le chiusure resta E.2** (sfida WAF non interpretata): la cattura è completa,
l'interpretazione no. È una lacuna misurata e riproducibile con il fixture, non un'ipotesi.

### 5.2 Si può mergiare?

**Sì.** Il branch è coerente, testato e documentato; nessun segreto nel repo. Prima del merge
servono solo operazioni, non altro codice:

1. **pulire l'albero**: tre `PROMPT-*.md` risultano cancellati e non committati (residuo di
   sessioni precedenti) più un prompt untracked — vanno ripristinati o committati;
2. **rebuild dell'immagine agent** in CI: l'agent container non monta `src/`, quindi
   `--force-recreate` da solo serve il codice dell'immagine (per kali basta il recreate, monta
   `./kali`);
3. **rieseguire i gate** dopo il rebuild: `tests/kali`, `test_http_proxy_history.py`,
   `test_recon_crawl_katana_depth.py`;
4. **decidere i follow-up** (§5.3) o accettarli come debito dichiarato in questo documento.

### 5.3 Follow-up non bloccanti

1. **E.2** — challenge detection a valle (fixture e test pronti, il test nasce rosso).
2. **Ignore-list della telemetria dei tool** (`api.pdtm.sh`, 2 artifact per run).
3. **Porte non web / QUIC** — decisione di topologia.
4. **CA dell'operatore** come parte del deploy, non estratta dall'handshake.

---

## 6. Come si riproducono i gate

```bash
# unit
PYTHONPATH=src .venv/bin/python -m pytest tests/kali tests/recon/test_pod_capture_context.py -q

# live crawl-only su IP (zero skip: stack giù => fail)
PYTHONPATH=src .venv/bin/python -m pytest tests/e2e/test_recon_crawl_katana_depth.py -q -s

# gate #196 storico
KALI_MCP_URL=http://localhost:8000/mcp KALI_HTTP_E2E_TARGET=http://172.28.0.20/ \
  .venv/bin/python -m pytest tests/e2e/test_http_proxy_history.py -q

# dominio con TLS self-signed (CA dell'operatore)
KALI_HTTP_UPSTREAM_CA=/data/upstream-ca.crt docker compose --env-file <checkout>/.env \
  -p polymerhus -f docker-compose.yml -f docker-compose.e2e.yml up -d --force-recreate kali

# fixture WAF + challenge
docker compose --env-file <checkout>/.env -p polymerhus \
  -f docker-compose.yml -f docker-compose.e2e.yml up -d waf-e2e-target waf-e2e-front challenge-e2e-target
```
