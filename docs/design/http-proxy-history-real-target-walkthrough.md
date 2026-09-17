# Reportage — primo run del capture plane su un target reale (HTTPS)

Data: 2026-09-17. Obiettivo: verificare che il capture plane di #196 regga un **dominio
reale su TLS**, non solo il target di laboratorio nudo (`172.28.0.20`, HTTP).

Target scelto **dal repo**, non inventato: `soupmarket.shop` — è il laboratorio
dell'operatore (OWASP Juice Shop dietro nginx), mappato in `docker-compose.yml:154` →
`192.33.91.87`, usato negli e2e del 16/17/19/20 luglio (`STATE.md`,
`docs/design/amv-8-e2e-diagnosis.md`, `post-recon-curation-and-l1-remediation-plan.md`).
È l'unico target HTTPS della storia del progetto, quindi l'unico che esercita davvero TLS.

Intensità: `httpx` single-host + `katana -d 1` (default di produzione), `-ct 240s` inalterato.
Nessuna modifica ai job, nessun flag extra.

---

## 1. Cosa serviva prima di partire

| Prerequisito | Stato all'inizio | Cosa è stato fatto |
|---|---|---|
| Egress Internet dal container kali | OK (`curl https://example.com` → 200) | — |
| CA del proxy fidata dai **client** nel lease | OK (122 certificati, `mitmproxy` incluso) | — |
| DNS dentro il namespace in lease | **rotto** (`curl` → rc 6 su ogni hostname) | fix C.12: resolver per-lease + forwarder sul gateway |
| Verifica TLS **upstream** del proxy | **rotta** verso il lab (cert self-signed) | fix C.13 (questo reportage) |

### 1.1 Il fix C.13, e la lezione che l'ha richiesto

`mitmdump` gira **senza** `ssl_insecure`, quindi verifica il certificato del sito che registra.
Contro `soupmarket.shop` (leaf self-signed, `CN=soupmarket.shop`, SHA-256
`20:11:2A:5F:…:F1:E5`) la transazione non arrivava: il client riceveva 502 e l'artifact
registrava il perché.

Primo tentativo — installare la CA nel trust store Debian (`update-ca-certificates`), il modo
canonico, che **funziona per `curl`**: da lì in poi `curl https://soupmarket.shop` (senza `-k`)
risponde 200. Ma il run è **fallito lo stesso**:

```text
run 1d4cffee-98dc-4f2b-aac7-775a226400c3   (project df83dd19-…)
httpx   success   capture {sent: true, refs: 2}   assets 5
katana  success   capture {sent: true, refs: 3}   assets 5

artifact https://soupmarket.shop/
  error = {"type": "Error", "message": "Certificate verify failed: self-signed certificate"}
  tls = false   sni = soupmarket.shop   status = null
```

La causa: **mitmproxy non verifica contro il trust store di sistema**, verifica contro la
propria sorgente CA (certifi). Installare la CA "alla Debian" la rende fidata a tutti **tranne
che al proxy** — il che spiega un fallimento che sembrava contraddire la verifica di `curl`.

Il fix: un **bundle** per l'upstream = store di default + CA dell'operatore, passato al proxy.

```text
postrun.sh :  python -m kali.http_history.trust  $KALI_HTTP_UPSTREAM_CA
              ├─ install_upstream_ca()     → /usr/local/share/ca-certificates/…   (client)
              └─ build_upstream_bundle()   → /data/mitmproxy/upstream-ca-bundle.pem
entrypoint :  mitmdump … --set ssl_verify_upstream_trusted_ca=/data/mitmproxy/upstream-ca-bundle.pem
```

Verifica del bundle in container: `operator_ca_in_bundle: True`, 122 certificati (nessuna CA
pubblica persa). Se la CA era già nello store, il bundle non la duplica.

---

## 2. Il run verde

```text
project  4991ff4e-cd40-4d3b-ac77-10b5cbb88f31
run      1217282a-000a-4512-ab4e-1053f66463d9
status   complete          wall 20.2 s          target soupmarket.shop (HTTPS)
```

| job | status | exec | `stats.capture` | asset prodotti | Endpoint curati |
|---|---|---|---|---|---|
| httpx | success | 1.414 s | `{sent: true, refs: 2, warning: null}` | 16 | — |
| katana | success | 15.233 s | `{sent: true, refs: 36, warning: null}` | 293 | 11 |

Grafo risultante: 39 nodi — `Domain` 1, `BaseURL` 1, `Endpoint` 11, `Header` 24,
`Technology` 1, `Parameter` 1; 11 nodi con `properties.source = "katana"`.

### 2.1 Gli artifact: TLS, sempre

38 artifact nello store per il run: 36 sul target + 2 di telemetria dei tool (vedi §4).

| Classe | Quanti | Note |
|---|---|---|
| `200` | 24 | SPA (`chunk-*.js`), `juice-shop/build/**`, `/rest/user/whoami`, `/api/Challenges`, `/api/Feedbacks` |
| `401` | 4 | `/rest/saveLoginIp`, `/rest/user/authentication-details/`, `/api/Users`, `/rest/user/change-password` |
| `500` | 8 | `/rest/user/login`, `/rest/user/reset-password`, `/rest/admin`, `/rest/web3`, `/rest/continue-code/*` |
| errore di trasporto | **0** | TLS intercettato e completato su tutte le transazioni |

Su tutti e 36: `connection.tls = true`, `connection.sni = soupmarket.shop`,
`connection.protocol = https`. L'artifact della radice, per intero (estratto):

```json
{
  "artifact_id": "http_01M2QKDQ9A6Y5K4VW8HVGWMJEV",
  "capture_context": {"run_id": "1217282a-…", "spec_id": "soupmarket.shop",
                      "exec_id": "01M2QKDPHH0MQ3GC4YJ08FKEAJ"},
  "request": {"method": "GET", "url": "https://soupmarket.shop/",
              "headers": [["Host","soupmarket.shop"],
                          ["User-Agent","Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:77.0) …Firefox/77.0"],
                          ["Accept-Charset","utf-8"], ["Accept-Encoding","gzip"], ["Connection","close"]]},
  "response": {"status": 200, "reason": "OK",
               "headers": [["Server","nginx/1.30.1"], ["Content-Type","text/html; charset=UTF-8"],
                           ["Transfer-Encoding","chunked"], ["Access-Control-Allow-Origin","*"],
                           ["X-Content-Type-Options","nosniff"], ["X-Frame-Options","SAMEORIGIN"],
                           ["Feature-Policy","payment 'self'"], ["X-Recruiting","/#/jobs"],
                           ["ETag","W/\"26af-19fa7e9e591\""], ["Content-Encoding","gzip"]],
               "body": {"size": 3098, "encoding": "binary", "capture_state": "captured"}},
  "connection": {"client_address": "172.30.0.2:43236", "server_address": "192.33.91.87:443",
                 "tls": true, "sni": "soupmarket.shop", "alpn": "b''", "protocol": "https"},
  "timings": {"total_ms": 52.898},
  "error": null
}
```

Cose che si vedono **solo** qui e non nel log di un tool: `Server: nginx/1.30.1`, gli header di
sicurezza dell'app, `Transfer-Encoding: chunked`, la dimensione reale del body (3098 B, gzip),
l'ALPN negoziato, il tempo di transazione e — soprattutto — l'indirizzo sorgente `172.30.0.2`,
cioè il **namespace del lease**: la prova che quella richiesta è passata dal percorso di cattura.

### 2.2 Il replay, su HTTPS e su dominio

```text
baseline: http_01M2QKDQ9A6Y5K4VW8HVGWMJEV   GET https://soupmarket.shop/   → 200
mutazione dichiarata: {"headers": {"X-Polymerhus-Replay": "real-target"}}
replay:   http_01M2QKEAJHPM9G5JK9ST4B5238   GET https://soupmarket.shop/   → 200
          derived_from = baseline, replay_kind = "mutated", tls = true
```

È il primo replay del progetto che attraversa DNS + TLS + lease su un dominio vero: fino a
questo giro il sender (`curl` nel namespace) non risolveva nemmeno il nome.

---

## 3. Cosa ha fatto il recon, visto dagli artifact

Il crawl a profondità 1 su una SPA Juice Shop ha prodotto 36 transazioni in 15 secondi:

1. **superficie SPA**: `chunk-DYXK4NW4.js`, `chunk-5K74DZ2F.js`, … (8 bundle) → 200;
2. **API REST dell'app**: `/rest/user/whoami` 200, `/api/Challenges` 200, `/api/Feedbacks` 200;
3. **endpoint che richiedono autenticazione**: `/api/Users`, `/rest/saveLoginIp`,
   `/rest/user/authentication-details/` → **401** (comportamento dell'app: `error = null`);
4. **endpoint che rispondono 500 a un GET senza payload**: `/rest/user/login`,
   `/rest/user/reset-password`, `/rest/admin`, `/rest/web3` → **500**, body 750 B,
   `Server: nginx/1.30.1`.

La distinzione fra "il target ha risposto male" e "non siamo riusciti a parlarci" è esattamente
ciò che il capture plane serve a rendere evidente, e qui si vede in due minuti: gli 8 `500`
sono risposte dell'applicazione, non errori di trasporto.

---

## 4. Scoperte collaterali

1. **I tool chiamano casa, e finisce nello store.** In entrambi i run compaiono artifact per
   `https://api.pdtm.sh/api/v1/tools/httpx?…&machine_id=…&utm_source=docker&v=v1.12.0` e
   `…/katana?…` → 200: è il check di aggiornamento di ProjectDiscovery, traffico **dei tool**,
   non del recon. Due conseguenze da decidere: rumore nelle query per run, e un `machine_id`
   che finisce in un artifact. Candidato: ignore-list per host di telemetria nota.
2. **Il proxy non maschera il fingerprint TLS** (noto, B/C.11): il target vede il proxy come
   client, non il tool.
3. **Nessun WAF/CDN su questo target**: `soupmarket.shop` è nginx diretto. Il caso "WAF" resta
   quello osservato su `example.com` (Cloudflare, `cdn_type: waf` rilevato da httpx e registrato
   negli artifact); un WAF che **sfida** (challenge/rate-limit) resta la parte aperta di C.3 e
   richiede un target dell'operatore dietro un WAF.
4. **`alpn = b''`** sulla connessione intercettata verso questo target: nessun ALPN negoziato,
   da rivedere se un target lo pretende.

---

## 5. Limiti residui, aggiornati

| Limite | Stato dopo questo run |
|---|---|
| DNS nel lease | **chiuso** (C.12) |
| upstream self-signed | **chiuso** (C.13, bundle `KALI_HTTP_UPSTREAM_CA`), con un onere: la CA va fornita dall'operatore. Qui è stata estratta dall'handshake (trust-on-first-use) perché è il laboratorio dell'operatore; in produzione il file va consegnato, non raccolto |
| porte ≠ 80/443 (QUIC/UDP 443 rifiutato) | invariato |
| pool namespace ≥ pod concorrenti | invariato; il degrado resta visibile in `stats.capture` |
| body cap 5 MiB, byte cap 1 GiB/progetto, retention 0 | invariati |
| telemetria dei tool registrata | **nuovo**, da decidere (ignore-list?) |
| fingerprint TLS del proxy | invariato, e visibile proprio negli artifact di questo run |

---

## 6. Come ripetere il test

```bash
# 1. CA del target di laboratorio nella trust del proxy (una volta)
docker exec polymerhus-kali-1 sh -c 'echo | openssl s_client -connect soupmarket.shop:443 \
  -servername soupmarket.shop 2>/dev/null | openssl x509 -outform PEM > /data/upstream-ca.crt'
cd <worktree>
KALI_HTTP_UPSTREAM_CA=/data/upstream-ca.crt docker compose \
  --env-file <checkout>/.env -p polymerhus -f docker-compose.yml -f docker-compose.e2e.yml \
  up -d --force-recreate kali

# 2. verifica PRIMA di lanciare il recon
docker exec polymerhus-kali-1 curl -sS -o /dev/null -w '%{http_code}\n' https://soupmarket.shop   # 200
docker exec polymerhus-kali-1 ls -l /data/mitmproxy/upstream-ca-bundle.pem                        # esiste

# 3. il run via API: settings.recon.target_seed = soupmarket.shop, jobs = [httpx, katana]
#    poi store per context/run_id, artifact per spec_id, replay con mutazione dichiarata
```

Evidenze: artifact nello store del progetto `4991ff4e-cd40-4d3b-ac77-10b5cbb88f31`,
run `1217282a-000a-4512-ab4e-1053f66463d9`.

---

## 7. Riepilogo in cinque righe

1. Il capture plane **regge un target reale HTTPS**: 36 transazioni TLS intercettate, zero
   errori di trasporto, DNS e certificato upstream risolti.
2. La CA nel solo store di sistema **non bastava**: mitmproxy verifica altrove (certifi).
   Lezione registrata in C.13 e risolta col bundle.
3. Dagli artifact si legge l'applicazione (nginx 1.30.1, header di sicurezza, bundle SPA,
   API REST, 401/500 autentici) molto più di quanto mostri il log di un tool.
4. Il replay su dominio + TLS funziona, con lineage verso la baseline.
5. Restano fuori: WAF con sfida, porte non web, QUIC, e la telemetria dei tool da ripulire.

---

## 8. Test A — un target che si difende (WAF), con gruppo di controllo

I WAF commerciali non si possono provocare su siti di terzi (nessuna autorizzazione, e senza
poter spegnere la difesa non esiste controllo). Quindi la fixture è **locale e toggleable**,
nell'overlay e2e — due forme di difesa, entrambe sulla porta 80 (l'unica che il `REDIRECT` del
lease copre):

| Servizio | Cos'è | IP:porta |
|---|---|---|
| `waf-e2e-target` + `waf-e2e-front` | **OWASP ModSecurity CRS** (929 regole caricate): blocco 403 su payload. L'engine gira unprivileged su 8080 e un forwarder TCP trasparente lo espone sulla :80, perché l'immagine rifiuta le porte privilegiate | `172.28.0.21:80` |
| `challenge-e2e-target` | **challenge in stile vendor**: interstitial + `cf-ray` + `cf-mitigated: challenge`, e il **cookie come controllo** (stessa richiesta, sfida spenta) | `172.28.0.22:80` |

### 8.1 Cosa cattura il capture plane (funziona)

Quattro richieste, tutte via lease, tutte finite nello store con `capture_warning: null`:

| Prova | Comando | Status | Header del WAF | Body |
|---|---|---|---|---|
| **blocco** | `curl 'http://172.28.0.21/?q=<script>alert(1)</script>'` | **403** | `Server: nginx` | 146 B (pagina di blocco) |
| **controllo** (stessa fixture) | `curl 'http://172.28.0.21/?q=health'` | **200** | `Server: nginx` | 71 B (risposta dell'app) |
| **challenge** | `curl http://172.28.0.22/` | **403** | `cf-ray`, `cf-mitigated: challenge` | 277 B (interstitial) |
| **controllo** (cookie) | `curl -H 'Cookie: cf_clearance=1' http://172.28.0.22/` | **200** | — | 65 B (risposta dell'app) |

Il capture plane non ha bisogno di sapere che sta parlando con un WAF: registra status, header e
corpo come per qualsiasi transazione, e i marker della difesa restano **nello store**. Questo è
il pezzo che il test A doveva dimostrare, ed è verde.

### 8.2 Cosa fa il recon con una challenge (il buco, misurato)

Un run `httpx + katana` contro il fixture di challenge registra:

```text
httpx   success   stats.capture {sent: true, refs: 2, warning: null}   asset 10
katana  success   stats.capture {sent: true, refs: 3, warning: null}   asset 10

grafo: 15 nodi — IP 1, BaseURL 1, Endpoint 1, Header 10, Technology 2
  BaseURL http://172.28.0.22   server = "BaseHTTP/0.6 Python/3.12.14 cloudflare"
                               title  = "Just a moment..."
  Technology Cloudflare
  Header cf-ray, cf-mitigated            <- i marker SONO nello store
```

Nessun nodo, nessun campo e nessuna observation dice **"questa era una challenge"**: la pagina
di verifica è stata ingerita come superficie applicativa, con `title` preso dall'interstitial e
`Cloudflare` come tecnologia. È esattamente il falso positivo che C.3/E.2 descrivono — evidenza
che *sembra* pulita — e ora è **dimostrato con artifact**, non argomentato. I marker sono già
persistiti (`cf-ray`, `cf-mitigated`), quindi il fix è di **interpretazione**, non di cattura.

### 8.3 Come si esegue

```bash
# fixture
docker compose --env-file <checkout>/.env -p polymerhus \
  -f docker-compose.yml -f docker-compose.e2e.yml up -d waf-e2e-target waf-e2e-front challenge-e2e-target

# blocco + controllo, dal percorso di cattura
#   curl 'http://172.28.0.21/?q=<script>alert(1)</script>'   -> 403
#   curl 'http://172.28.0.21/?q=health'                      -> 200
#   curl http://172.28.0.22/                                 -> 403 + cf-ray
#   curl -H 'Cookie: cf_clearance=1' http://172.28.0.22/     -> 200

# challenge vista dal recon: seed = 172.28.0.22, jobs = [httpx, katana]
```

Il passo successivo (non fatto qui, da decidere) è E.2: etichettare la challenge — **mai**
`symptom-confirmed` su una risposta riconosciuta come sfida, esito **inconcludente** — usando i
marker che il capture plane già registra.
