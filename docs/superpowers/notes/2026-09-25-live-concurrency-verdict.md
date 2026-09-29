# Verdict — the live concurrency ceiling was never applied (#238)

**Esito:** il ramo nominato è **(a2) risoluzione**, sottocaso **host non
coperto**, con una causa meccanica più precisa di quella che il piano
prevedeva: il governor confrontava l'**IP** inferito dal modo *transparent*,
non l'hostname che il client ha chiesto.

## L'esperimento (una sola variabile: il tempo di lettura)

- Stack: `polyphemus-238-e2e`, immagini `polymerhus-kali:issue-238-e2e` /
  `polymerhus-agent:issue-238-e2e` ricostruite dal commit `79cb551e` (Task 1
  strumentazione + Task 2 oracolo).
- Il contenitore `kali` è stato **ricreato** prima dell'esperimento, così i
  contatori del governor (per processo) partono da zero e sono attribuibili.
- Un sampler dentro il container ha letto ogni 0.5 s, per tutta la run, sia il
  registry dei lease (`/run/kali-http/registry.sqlite3`) sia lo snapshot del
  governor (`/data/governor-status.json`): le righe di lease sono **transitorie**
  (vengono cancellate al rilascio), quindi l'unico modo di vederle è campionarle.
- Run: scenario `high_limit`, progetto `e2e-admission-high_limit`,
  `run_id=6c50da9f-9d9e-4ea1-a2ab-6a4067b1f550`.
- L'oracolo (Task 2) fallisce come atteso:
  `AssertionError: high_limit: the target observed max_in_flight=29 with max_concurrency=1`

## Le tre viste, stessa finestra

| Vista | Valore osservato |
|---|---|
| **Policy persistita** (`recon_runs.stats.rate_limit.traffic_policy`, run `6c50da9f`) | `target_key=high-limit.e2e.local`, `host_patterns=["high-limit.e2e.local"]`, `rate_per_s=10.0`, `burst=10`, **`max_concurrency=1`** |
| **Policy registrata nel lease** (campionata viva: `source_ip=172.30.0.2`, `project=d8f0fa49-e2c1-42e4-ad9b-c742e2494c43`) | **armata**: lo stesso payload `traffic-policy/v2`, presente in 71 campioni consecutivi attraverso tutto il burst |
| **Contatori del governor** (snapshot dell'addon, in-process) | `admitted=0`, `buckets=0`, `peak_inflight=0`, `waited_s=0.0`, `duplicate_releases=0`, `keys=[]` |
| **Contatori dell'addon** | `governed=0`, `governor_refusals=0`, `governor_failed=0`, `recorded=5165`, `unscoped=0` |
| **Quello che il bersaglio ha visto** | `requests=5164`, **`max_in_flight=29`**, 5000 eventi registrati, **3374 con `in_flight > 1`**, 4752 route distinte (la wordlist ffuf) |

Timeline dei contatori (dal sampler, t in secondi dall'inizio):

```
 t_s  recorded governed admitted peak  leases(ip:armed|null)
57.6      394        0        0    0   172.30.0.2:P      <- lease armata
72.2      738        0        0    0   172.30.0.2:P      <- inizia il burst ffuf
79.2     3417        0        0    0   172.30.0.2:P
89.2     5157        0        0    0   172.30.0.2:P
92.2     5165        0        0    0   172.30.0.2:P      <- fine
```

Il lease è armato, 4764 flow passano dal proxy in 20 s, e il governor non
ammette **nemmeno una** richiesta: nessun bucket, nessun rifiuto, nessun wait.

## Ramo nominato e meccanismo

**(a2) risoluzione** — il flow non veniva associato alla policy, e la mancata
associazione era **silenziosa** (`GovernorDecision(governed=False)` con
`request` che ritorna senza rifiutare e senza contare).

Ipotesi meccanicistica in una frase: *l'addon passava a `host_matches`
l'`request.host` di mitmproxy, che in modo transparent è l'IP della connessione
(`172.29.0.9`) e non l'hostname della policy (`high-limit.e2e.local`), quindi
ogni flow di un lease armato risultava "non di competenza" e proseguiva non
governato.*

Prove che fissano il meccanismo:

1. Il contratto di mitmproxy lo dichiara (`mitmproxy/http.py`):
   `Request.host` — "inferred from the proxy mode (e.g. an IP in transparent
   mode)"; `Request.pretty_host` — "Like `Request.host`, but using
   `Request.host_header` … preferred … useful in transparent mode where
   `Request.host` is only an IP address".
2. Il log di mitmdump della finestra contiene **5167** righe
   `GET http://172.29.0.9/...` e **zero** righe con
   `http://high-limit.e2e.local`.
3. L'artefatto catturato per la stessa richiesta ffuf porta invece
   `url: http://high-limit.e2e.local/.svnignore` e `Host: high-limit.e2e.local`:
   la cattura usa `pretty_url` (hostname), il governor usava `host` (IP). Le due
   viste dello stesso flow divergevano, e a decidere il governo era quella
   sbagliata.
4. `addon.governed == 0` con `governor_refusals == 0` esclude ogni altro esito
   del ramo `request`: non c'è stato né un rifiuto locale, né un'eccezione, né
   una decisione governata.

## Perché gli altri rami sono esclusi

| Ramo | Esclusione (numeri) |
|---|---|
| **(a1) armamento** | Il lease è armato con l'esatto payload v2 (`max_concurrency=1`, `host_patterns=["high-limit.e2e.local"]`) per tutta la finestra del burst (71 campioni). La policy persistita e quella registrata coincidono. Il canale exec→lease→registry ha funzionato. |
| **(b) chiave o istanza** | `governor.buckets == 0` e `admitted == 0`: il governor non ha mai creato un bucket, quindi non esiste una questione di chiave (`project_id`/`target_key`) o di istanza multipla. Uno sbaglio di chiave mostrerebbe `admitted > 0` con `buckets >= 1`. |
| **(c) rilascio** | `duplicate_releases == 0` e `waited_s == 0.0` con `admitted == 0`: nessun permesso è mai stato preso, quindi nessun rilascio può essere anticipato o duplicato. |

## Correzione al framing del finding

Il finding diceva "il rate risultava applicato, la concorrenza no". I numeri
dicono un'altra cosa: **il governor non ha governato nulla in quella finestra**,
né rate né concorrenza. I `429` visibili nel log del proxy sono del **limiter
del bersaglio** (`X-RateLimit-Limit: 15`, il fixture `high_limit`), non del
governor. La lettura "il rate funziona" nascondeva il fatto che il piano di
governo era completamente disconnesso: è esattamente il silenzio che ha
permesso al difetto di sopravvivere.

## Dettagli del piano che non tornano con il codice reale (registrati, non aggirati in silenzio)

1. **`sqlite3` non esiste nell'immagine kali**: la query del Task 3 sul registry
   dei lease non è eseguibile come scritta (`exec: "sqlite3": executable file
   not found`). La vista è stata raccolta con il python del container (modulo
   `sqlite3`), che è la stessa sorgente.
2. **Le righe di lease sono transitorie**: `NamespaceLeaseManager.release`
   cancella la riga a fine exec, quindi una lettura *dopo* la run non può mai
   mostrare la policy registrata. La vista va **campionata durante** la run.
3. **I contatori del governor sono per processo e cumulativi**: l'attribuzione a
   una singola run richiede un proxy fresco (fatto: container ricreato) e, nel
   gate, un confronto per **delta** invece che sul valore assoluto.
