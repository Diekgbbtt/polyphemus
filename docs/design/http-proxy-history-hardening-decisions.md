# HTTP-Proxy History #196 — Decisioni di design, trattamento dei rischi, registro dei problemi

**Status:** decision record — 2026-09-16
**Branch:** `feat/http-history-hardening` (fork `935be0f`, head `05e4a22`)
**Piano attuativo:** `docs/superpowers/plans/2026-09-16-http-history-hardening.md`
**Spec:** `docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md`
**Operazioni:** `docs/design/http-proxy-history-operations.md`

Questo documento non ripete il *cosa* (la spec) né il *come si installa* (l'ops doc):
registra le **decisioni di design**, i **rischi di rilevamento** e i **problemi noti** con
lo stato reale del trattamento. Ogni riga di stato punta a un commit e a un file: se una
decisione è stata presa ma non attuata, qui è scritto "Rinviato" o "Fuori scope" — non
"fatto".

## 0. Come leggere le tabelle di stato

| Stato | Significato |
|---|---|
| **Attuato** | in produzione sul branch, con commit + test |
| **Parziale** | chiusa la parte che genera il danno; resta un pezzo dichiarato |
| **Rinviato** | decisione presa, attuazione non in questo perimetro |
| **Fuori scope** | richiede un piano separato (prerequisiti infrastrutturali o decisione operatore) |
| **Decisione aperta** | serve una scelta dell'operatore, con un trade-off esplicito |

---

# Parte A — La decisione strutturale: pacchetto vs esplodere

## A.1 La domanda

Ogni transazione HTTP catturata può vivere in due forme:

1. **impacchettata** — un documento `http-artifact/v1` serializzato in `flows.record_json`;
2. **esplosa** — righe `(artifact_id, side, namespace, key, text_value, numeric_value)` nella
   tabella `attributes`, con i body in blob content-addressed.

La domanda non è "quale delle due è meglio", ma **quale delle due è la verità** e quale è
**l'indice**.

## A.2 Perché il pacchetto non è sostituibile

**A.2.1 L'ordine e i duplicati non hanno posto in una tabella piatta.**
Gli header HTTP sono una lista ordinata con duplicati ammessi: due `Set-Cookie`, lo stesso
header ripetuto, l'ordine che conta. Nel JSON sono una lista di coppie —
`[["Set-Cookie","sid=a"], ["Set-Cookie","theme=dark"], ["Host","..."]]`. Nell'EAV quelle tre
diventano tre righe che hanno perso la posizione: conservarla richiederebbe una colonna
`ordinal` su **ogni** riga di **ogni** lista (header, cookie, query, form). La spec promette
esplicitamente che *header order and duplicates survive as ordered pairs*: la forma piatta non
può mantenerla senza aggiungere colonne che oggi non esistono.

**A.2.2 La struttura annidata non si appiattisce senza perdita.**
Il record contiene oggetti dentro oggetti: `request` che contiene un `body`, `response` che ne
contiene un altro, `connection` e `timings` separati, `error` opzionale. La tripletta
`(side, namespace, key)` funziona per gli scalari ma non sa dire "questo status appartiene
all'oggetto `response`". Per farlo servono una tabella per entità — requests, responses,
headers, cookies, bodies, connections — cioè 6-8 tabelle più un join per ricostruire una
transazione.

**A.2.3 Assente, nullo e vuoto sono tre stati diversi.**
`"error": null`, la chiave assente e `"reason": ""` sono tre cose distinte. Nell'EAV sono tutte
"nessuna riga". La proiezione attuale **collassa già** questi stati per i campi core: è una
perdita accettata esattamente perché il JSON conserva la verità.

**A.2.4 Il fatto immutabile è naturalmente un oggetto unico.**
Un artifact si scrive una volta e non si aggiorna mai. Una riga con un valore dentro è la
rappresentazione naturale di un fatto atomico: non esistono stati parziali. In un EAV-only,
"l'artifact esiste" diventerebbe una proprietà **derivata** dall'aver scritto tutte le righe
giuste — un invariante da mantenere, non una proprietà che ottieni gratis.

**A.2.5 Il consumatore principale vuole il record intero.**
`get_http_artifact` restituisce la transazione completa; il replay rilegge la richiesta
completa per rispedirla. Sono entrambe letture di **un solo oggetto**. Con l'EAV come fonte
ogni lettura diventa una ricostruzione: un `GROUP BY` su ~40 righe più un assemblatore che
conosce lo schema a memoria (`kali/http_history/sanitize.py`, `replay.py`).

**A.2.6 La validazione vive nel modello, non nelle righe.**
Ogni lettura passa da `model_validate_json` contro `http-artifact/v1`: è lì che stanno i tipi,
i campi obbligatori, la versione dello schema (`kali/http_history/models.py`). Le righe di un
EAV non si validano come record: nessuno ti dice che le 40 righe sono complete, coerenti fra
loro, o della versione giusta.

## A.3 Perché serve comunque la forma sparsa

Se il pacchetto è così buono, perché non tenere solo quello? Perché la domanda *"quali
transazioni hanno questo header?"* sul JSON è una **scansione completa**: devi aprire ogni riga
e leggere dentro la stringa.

Ed è il punto centrale: **il linguaggio di query ha chiavi aperte**. Header, cookie, parametri
e campi form hanno nomi decisi dal bersaglio, illimitati — non possono essere colonne. La
forma sparsa non è una preferenza, è la conseguenza di quel requisito.

## A.4 La risposta: due domande obbligatorie, due strutture

Non è "impacchettato **invece di** spacchettato" — è **impacchettato come verità, spacchettato
come indice**:

| Domanda | Chi risponde | Costo se usi l'altro |
|---|---|---|
| "dammi questa transazione, fedele com'era" | JSON (`record_json`) | ricostruzione + perdita di ordine, duplicati e null |
| "quali transazioni hanno questo attributo" | attributi (`attributes`, indici + FTS) | scansione completa di tutti i record |

## A.5 L'argomento che rende la scelta irreversibile

**Dal pacchetto puoi sempre rigenerare l'indice; dall'indice non puoi rigenerare il
pacchetto.** Se domani serve filtrare su un campo che oggi non proietti, rileggi i JSON e
ricostruisci. Se avessi tenuto solo le righe, quel dato — e **il traffico passa una volta
sola** — sarebbe perso.

È questa asimmetria, non un gusto per il formato, a fissare la direzione.

## A.6 Il costo, misurato

Il costo della ridondanza è noto e quantificato nell'analisi #196:

| Misura | Pacchetto + indice | Solo pacchetto |
|---|---|---|
| spazio su disco | 116-128 MB / 10.000 flow | ~22 MB |
| scrittura | ~30× più lenta | baseline |
| query su attributo | indice (dopo il fix degli indici covering) | scansione completa |

Lo stesso dato è scritto fino a **quattro volte** (record + attributi + FTS + body blob). Non è
un difetto da correggere a colpi di refactor: è il prezzo dichiarato di avere **entrambe** le
proprietà invece di una.

## A.7 "Ha senso farlo rimanere così?"

**Sì**, con tre condizioni — che sono esattamente quelle su cui abbiamo agito (Task 2 e Task 11
del piano):

1. **Il costo di scrittura si paga una volta, il costo di lettura si paga sempre.** Gli indici
   devono essere *covering* per le query reali e la statistica del planner deve esistere:
   `attributes_text_cov` / `attributes_numeric_cov` con `artifact_id` in coda, `ANALYZE`, e i
   due indici non-covering rimossi (commit `0418011`,
   `kali/http_history/store.py`).
2. **La manutenzione non deve dipendere dall'operatore.** `busy_timeout` sui due writer
   concorrenti (addon + MCP) e cache degli handle limitata a LRU, altrimenti la scelta
   "impacchetta+esplodi" degrada in "database is locked" e handle leak (commit `0418011`,
   `7595fee`).
3. **I body restano content-addressed e non duplicati** — l'unica parte del pacchetto che non
   si è mai duplicata.

**Trigger di revisione** — se ricompare uno di questi, la decisione va riaparta:

- una query *legittima e ricorrente* resta lenta nonostante gli indici covering (allora il
  problema è la forma della proiezione, non la decisione);
- lo spazio per progetto diventa il vincolo operativo (allora entra in gioco la retention, non
  l'eliminazione del pacchetto);
- un consumatore nuovo chiede di leggere *tutti* i campi di *molti* record (allora serve una
  proiezione dedicata, non un cambio di fonte di verità).

## A.8 Se il costo diventa il problema: la proiezione pigra

Se il vincolo diventa il costo dell'indicizzazione, la strada **non** è buttare il pacchetto: è
**costruire l'indice più tardi**. La proiezione pigra tiene la fedeltà del pacchetto e sposta
il costo dell'indicizzazione dalla **cattura** alla **prima ricerca**:

- la cattura scrive solo `record_json` + body blob (percorso caldo, minimo);
- gli attributi di un artifact vengono proiettati alla prima ricerca che li tocca, e da quel
  momento l'indice è disponibile (e potabile in background);
- se la logica di proiezione cambia, l'indice si **rigenera** dal pacchetto (A.5), cosa
  impossibile nella direzione opposta.

Stato: **Rinviato** — è una decisione architetturale, non un piano. Va aperta solo se (e
quando) il costo misurato in A.6 diventa il collo di bottiglia: oggi la scelta corretta è
tenere la proiezione sincrona, perché il volume è basso e la correttezza dell'indice
immediato vale più del picco di scrittura.

---

# Parte B — Risk assessment: intercettazione e WAF

## B.1 Perimetro

Il piano di cattura non è passivo: **mitmproxy 12.2.3 su OpenSSL 4.0.1** termina la connessione
del client e ne apre una seconda verso l'origine. Tutto ciò che il target osserva sul secondo
tratto è generato da mitmproxy, non da curl. In più, ogni namespace in lease esce con lo
**stesso indirizzo IP** dopo il `MASQUERADE` della `/24`. Sono due proprietà che, insieme,
creano una superficie di rilevamento ampia.

## B.2 I vettori

| # | Cosa osserva il target | Perché il sistema lo produce | Rilevabilità |
|---|---|---|---|
| **V1** | Fingerprint TLS (JA3/JA4) del ClientHello | il ClientHello verso l'origine è di mitmproxy, non del client | alta (firma stabile e pubblica) |
| **V2** | Fingerprint HTTP/2 (SETTINGS, window, ordine pseudo-header) | lo stack h2 upstream è di mitmproxy (hyper-h2), non quello del client | alta su target che parlano h2 |
| **V3** | Ordine, casing e framing degli header | il proxy ricodifica il messaggio; hop-by-hop gestiti da lui | media (ordine preservato per h1, normalizzato per h2) |
| **V4** | Ciclo di vita delle connessioni upstream (pool, keep-alive, coalescing) | il pool è del proxy, condiviso da tutti i namespace | media |
| **V5** | IP sorgente | `MASQUERADE` su tutta la `/24`: un solo IP per container | alta |
| **V6** | Pattern temporale (baseline + N mutazioni in rapida sequenza) | il pod replaya la baseline e poi ogni variante | alta |
| **V7** | Anomalie di protocollo (es. `Content-Length` incoerente) | il bug del body omesso al replay | alta quando si verifica |
| **V8** | Assenza di QUIC dall'IP | `udp/443` è rigettato in `FORWARD` | bassa-media |

## B.3 I rischi e il loro stato

| # | Rischio | Gravità | Probabilità | Stato del trattamento |
|---|---|---|---|---|
| **R1** | Rate limiting aggregato sull'IP condiviso | alta | alta | **Fuori scope** — richiede identità di rete per lease + rate limiter nel capture plane (Parte D) |
| **R2** | Challenge e rate limit interpretati come esito applicativo | alta | alta su target protetti | **Parziale** — la classe 429/503/5xx è chiusa; la classe "challenge page" no |
| **R3** | Fingerprint stabile e identico ovunque | alta | media-alta | **Fuori scope** — splice TLS per-host (Parte D) |
| **R4** | Comportamento di connessione incoerente | media | media | **Fuori scope** — `connection_strategy` esplicito (Parte D) |
| **R5** | Inquinamento del canale di misura (challenge in body/marker/FTS) | media-alta | alta su target protetti | **Rinviato** — nessun marcatore di "risposta di difesa" nel record |
| **R6** | Anomalia da `Content-Length` incoerente | alta | bassa-media | **Attuato** — `335eb3f` |
| **R7** | Assenza di QUIC | bassa | bassa | **Fuori scope** — rileva solo con browser headless nei namespace |

### R2 in dettaglio: il rischio che corrompe le misure

È il più insidioso perché non rallenta: **falsifica**. La logica del pod mappava gli status
così:

```python
if 200 <= status < 400: return True    # allowed
if 400 <= status < 500: return False   # denied
return None                            # unknown
```

Da cui due falsi positivi diretti: un `403` di WAF è `denied` esattamente come un `403`
dell'applicazione; un `429` è `denied`, e una mutazione che cade fuori dalla finestra torna
`200` → la regola "baseline negata, mutazione ammessa" scatta → **sintomo confermato**; una
challenge page (Cloudflare, CAPTCHA, interstitial) è tipicamente un `200` → `allowed`.

Il vocabolario del design prevede già `specific-defence-prevention` fra gli esiti terminali:
la categoria esisteva, **il rilevatore no**.

**Cosa è stato chiuso** (`a6b5d50`,
`src/polymerhus/attack/hunting/hunting_pod.py`):

- `DEFENCE_STATUSES = frozenset({429, 503})` e `_defence_signal(status)` →
  `"rate-limited"` / `"server-error"` / `None`;
- `_allowed(status)` ritorna `None` per **qualunque** status classificato come difesa, quindi
  la regola del sintomo non può più scattare su un `429`, un `503` o un `5xx`;
- ogni `interpretations` del percorso `request_ref` porta `"defence": <signal|None>`, così il
  trail dice esplicitamente *"qui c'è stata una difesa"* invece di lasciar credere che il
  target abbia risposto come applicazione.

**Cosa resta aperto** (dichiarato, non nascosto):

- **nessun riconoscimento di challenge page**: header `cf-ray` / `x-akamai-*`, corpi di
  interstitial, `Server` noti **non** sono rilevati (verificato: nessun riferimento a questi
  marker nel codice hunting). Una challenge `200` continua quindi a essere letta come
  `allowed`;
- il segnale `defence` è registrato nel percorso `request_ref`; nel percorso a **vettori
  inline** la difesa non conferma più un sintomo (`_allowed` → `None`) ma **non viene
  etichettata** nel trail;
- l'esito terminale `specific-defence-prevention` **non** è ancora prodotto dal percorso
  deterministico: quel vocabolario resta raggiungibile solo dalla decisione del triager.

## B.4 Trattamenti in ordine di rapporto valore/sforzo

| # | Trattamento | Copre | Costo | Stato |
|---|---|---|---|---|
| 1 | Separare i segnali di difesa dall'esito applicativo (rate limit/5xx inconclusivi + segnale nel trail) | R2 (parziale), R5 | basso, tutto nel nostro codice | **Attuato** `a6b5d50` |
| 1b | Riconoscere i marker di challenge e mapparli su `specific-defence-prevention`, esporre il rilevatore anche al percorso deterministico | R2, R5 | basso-medio | **Rinviato** — decisione aperta E.2 |
| 2 | Identità di rete per lease: `SNAT` verso una pool, un indirizzo per namespace al posto del `MASQUERADE` della `/24` | R1 | medio-alto (serve pool instradabile) | **Fuori scope** |
| 3 | Rate limiter nel capture plane: token bucket per `(progetto, host)`, cap di concorrenza per host, backoff che rispetta `Retry-After` | R1, V6 | medio | **Fuori scope** |
| 4 | Ridurre il gap di fingerprint: `connection_strategy=lazy`, niente pooling aggressivo; `ignore_hosts` con splice TLS per gli host ad alto rischio (si registra il tunnel, non il contenuto) | R3, R4, R7 | medio | **Fuori scope** |
| 5 | Igiene della flotta: separare l'egress dello scanning da quello dell'hunting | R1 | medio | **Fuori scope** |
| 6 | Guard fail-closed sul body: converte il replay con framing incoerente in un errore | R6 | minimo | **Attuato** `335eb3f` |

Nota di design sul punto 4: il compromesso è **per-host**, non globale — splice dove la
fedeltà al client conta più della visibilità, MITM dove serve vedere il contenuto. Oggi il
sistema non ha questo controllo: il proxy decifra tutto, sempre.

## B.5 Verifiche sperimentali da eseguire (non ancora fatte)

Non un'opinione, un esperimento misurabile. **Nessuna di queste è stata eseguita**: sono il
prerequisito per dichiarare chiusa la Parte B.

1. **Confronto A/B su un target protetto**: la stessa richiesta inviata diretta (senza proxy) e
   attraverso il proxy, confrontando status, dimensione della risposta, presenza di challenge e
   hash del corpo.
2. **Fingerprint**: misurare JA3/JA4 e il fingerprint h2 nei due casi con un servizio di echo
   pubblico, per vedere esattamente cosa cambia.
3. **Rate limit**: N richieste sequenziali dalle due vie, per individuare la soglia e verificare
   che il proxy non la anticipi.
4. **Falsi positivi**: costruire un caso con baseline `403` e mutazione `429`/challenge e
   verificare che il pod **non** concluda `symptom-confirmed`. Con il codice attuale la metà
   "rate limit" di questo caso è coperta (test
   `tests/attack/test_hunting_pod.py::test_rate_limited_mutation_is_not_a_confirmed_symptom`);
   la metà "challenge page" no.

## B.6 Rischio residuo

Anche con tutto applicato, restare dietro un proxy di intercettazione è intrinsecamente
rilevabile: le difese che confrontano il fingerprint TLS con quello atteso per quel client
continueranno a vedere una differenza. La scelta vera non è "evitare la detection", è
**decidere dove la fedeltà al client conta più della visibilità del contenuto** — e oggi il
sistema non ha questo controllo. Averlo per-host (splice dove serve, MITM dove serve vedere) è
la modifica architetturale che sposta davvero il rischio, ed è Fuori scope qui.

---

# Parte C — Registro dei problemi

Formato: *cosa succede* → *decisione di design* → *attuazione* → *evidenza* → *costo* → *stato*.

## C.1 La filiera non è collegata (P0)

**Cosa succedeva.** `search_http_history` e `get_http_artifact` esistevano ma nessuno iniettava
le funzioni dietro di loro: rispondevano `http_history_unavailable`. Stessa cosa per il replay
del pod — `arun_pod` non aveva alcun percorso di replay, il `request_ref` era risolto solo dal
pod deterministico `HuntingHttpPod`. L'unico posto dove la catena funzionava era il test E2E.

**Decisione.** "Portare in produzione ciò che il test già fa": un client MCP app-side
condiviso, **sincrono** (i tool lo invocano sincronamente), con i tre callable
`default_http_search_fn` / `default_http_get_fn` / `default_replay_fn`; binding dei primi due
nel builder di produzione dell'hunter e del terzo nel pod di produzione come tool `replay`.

**Attuazione.**

| Pezzo | Dove | Commit |
|---|---|---|
| client app-side sync + `structured_payload` | `src/polymerhus/app/clients/kali_http_history.py` (nuovo) | `b252bde` |
| binding search/get nel builder dell'hunter (catena `runtime` → `llm.build_actor_hunting_agent` → `hunting_agent.build_hunting_agent` → `build_hunter_tools`) | `runtime.py`, `llm.py`, `hunting_agent.py` | `b252bde` |
| tool `replay` nel runner di produzione + threading di `replay_fn` via harness context | `pod/agents.py`, `pod/graph.py`, `pod/llm.py`, `pod/pod.py`, `runtime.py` | `9552cf2` |
| una riga nel prompt P0 del runner: con `request_ref` si chiama `replay`, non si scrive un curl | `pod/prompts.py` | `9552cf2` |

**Evidenza.** `tests/attack/test_http_history_wiring.py`,
`tests/attack/test_kali_http_history_client.py` (5 test), `tests/attack/pod/test_replay_tool.py`
(3 test); prova di binding con `_default_hunter_builder` instrumentato; check live su
`http://localhost:8000/mcp` → artifact reale (`http_01M2B9WVZ7G2QS4A71AMFTNK7B`).

**Costo.** Basso. **Stato: Attuato.**

## C.2 Replay con body mancante, in silenzio (P0)

**Cosa succedeva.** Se il body era troppo grande e non era stato salvato
(`capture_state="omitted"`), il replay partiva **senza corpo** ma con l'header
`Content-Length` originale, dichiarandosi `baseline`. Il server aspettava byte che non
arrivavano. Non un errore: un esperimento falsificato che sembrava valido.

**Decisione.** Fail-closed nel servizio, non nel chiamante: se la richiesta dichiara un body
(`body_size > 0`) ma i byte non sono nello store, il replay **rifiuta** con un errore
esplicito che nomina il `capture_state` e indica la via per chi vuole davvero una variante
senza corpo (`body: ""` esplicito). Al confine MCP l'errore ha codice `body_unavailable`, così
il fallimento è classificabile e non indistinguibile da un `invalid_request`.

**Attuazione.** `BodyUnavailableError` + guard in `HttpHistoryService.replay`
(`kali/http_history/service.py`), mappatura in `_error_payload` (`kali/mcp_server.py`).
Commit `335eb3f`.

**Evidenza.** `tests/kali/test_http_history_service.py`:
`test_replay_refuses_a_baseline_whose_body_is_missing` (con `max_body_bytes=1` →
`capture_state="omitted"`) e `test_replay_still_accepts_a_bodyless_baseline` (nessuna
regressione sul caso legittimo).

**Costo.** ~6 righe + 2 test. **Bonus:** elimina anche una firma da bot (V7/R6). **Stato: Attuato.**

## C.3 WAF e rate limit letti come esito applicativo

Vedi **B.3/R2** e **B.4 punto 1** per l'analisi completa e per ciò che resta aperto.
**Stato: Parziale** (`a6b5d50`).

## C.4 Impossibile costruire il gruppo di controllo (P2)

**Cosa succedeva.** Nessuna negazione: né nei filtri (AND senza "ne") né negli override (un
header si imposta, non si rimuove). Quindi *"la stessa richiesta senza quell'header"* — l'unico
modo per validare un'ipotesi sugli header — non era producibile.

**Decisione.** Due aggiunte precise, **non** un `ne` generico: su un EAV un "ne" avrebbe
semantica ambigua ("esiste una riga con valore diverso" ≠ "non esiste la riga").

1. **`absent` nei filtri**, come `NOT EXISTS (... side, namespace, key)` — semantica non
   ambigua, ed è esattamente il gruppo di controllo. Non richiede un `value`;
2. **`remove_header` / `remove_headers`** nel vocabolario degli override, applicati
   case-insensitive **dopo** gli override di header e cookie (così un header appena impostato
   si può anche togliere nella stessa chiamata).

**Attuazione.** `kali/http_history/store.py` (branch `absent` in `_filter_sql` + `ALLOWED_OPS`),
`kali/http_history/replay.py` (`ALLOWED_OVERRIDES` + filtro). Commit `0104eb9`, `11a8113`.

**Evidenza.** `tests/kali/test_http_history_search.py::test_absent_operator_matches_transactions_without_the_attribute`,
`...::test_absent_does_not_require_a_value`,
`tests/kali/test_http_history_replay.py::test_remove_header_drops_the_named_headers`,
`...::test_remove_header_runs_after_setting_headers`.

**Costo.** Basso-medio. **Stato: Attuato.**

## C.5 Indici e planner (P1)

**Cosa succedeva.** Gli indici `attributes_text` / `attributes_numeric` non avevano
`artifact_id` in coda, quindi la sottoquery correlata non risolveva il legame dentro l'indice;
`ANALYZE` non girava mai. Query larghe 1.800-3.900× più lente.

**Decisione.** Indici **covering** con `artifact_id` in coda + rimozione dei due vecchi
(`DROP INDEX IF EXISTS` dentro `_migrate`: no-op sui file nuovi, bonifica sui file esistenti —
nessuna migrazione distruttiva) + `ANALYZE` esposto come `optimize()`.

**Attuazione.** `_SCHEMA`/`_migrate`/`optimize()` in `kali/http_history/store.py`. Commit
`0418011`.

**Evidenza.** `EXPLAIN QUERY PLAN` della sottoquery `status=200` →
`SEARCH a USING COVERING INDEX attributes_numeric_cov (side=? AND namespace=? AND key=? AND numeric_value=? AND artifact_id=?)`;
`tests/kali/test_http_history_store.py::test_attribute_indexes_are_covering`,
`...::test_optimize_runs_analyze`. La verifica è **deterministica sul piano di query**, non
un'asserzione temporale.

**Costo.** Minimo. **Stato: Attuato.** (Vedi anche A.7: è la condizione 1 che rende sana la
scelta pacchetto+indice.)

## C.6 Sanitizzazione default-allow (P3)

**Cosa succedeva.** Due lati scoperti: (a) la redazione dipendeva da una **regex sui nomi**,
quindi un header sensibile che non matcha passava; (b) `sanitize_artifact` restituiva
`capture_context.model_dump()` **in blocco**, quindi `source_ip` attraversava il confine senza
che nessuno lo avesse deciso.

**Decisione.**

1. **proiezione esplicita** dei campi di capture context che vogliamo esporre — `source_ip`
   esce, e la whitelist rende sicuro il default per i campi futuri;
2. **inversione della politica sui valori**: nome sempre visibile, valore visibile solo per
   allowlist — *decisione presa nel design, non attuata* (vedi E.1).

**Attuazione.** `_EXPOSED_CONTEXT_FIELDS` + `_context_view` in `kali/http_history/sanitize.py`
(7 campi: `session_id`, `run_id`, `spec_id`, `variant_ref`, `exec_id`, `derived_from`,
`replay_kind`). Commit `21c5d70`.

**Evidenza.** `tests/kali/test_http_history_sanitize.py::test_capture_context_is_projected_explicitly`
(asserisce l'insieme esatto delle chiavi e che l'IP interno non compaia).

**Costo.** Basso-medio. **Stato: Parziale** — proiezione attuata, allowlist dei valori aperta.

**Trade-off da decidere consapevolmente.** La allowlist rende **meno** valori visibili di oggi:
migliora la sicurezza e **peggiora la decidibilità** dell'agente. La mediazione sensata
(proposta, non attuata): allowlist per i valori **+** query di **presenza** consentite sui nomi
sensibili — l'agente può chiedere *"portava un token?"*, non *"che token era"*.

## C.7 La lineage si perde se l'agente aggira il pod (P3)

**Cosa succedeva.** Se l'agente rifaceva il curl con `exec`, l'artifact nasceva con
`derived_from: null` e `replay_kind: null`: indistinguibile da traffico originale, e quindi
candidato **baseline** per le ricerche successive. Il dataset si contaminava in silenzio.

**Decisione.** Rendere il percorso manuale **etichettabile** invece di proibito: due parametri
opzionali che finiscono nel `CaptureContext` del lease. Il bypass smette di essere invisibile;
il replay del pod resta la via normale.

**Attuazione.** `derived_from` / `replay_kind` in `HttpHistoryService.execute` e in
`execute_command` (`kali/mcp_server.py`), mappati su `None` quando vuoti. Commit `7d856f3`.

**Evidenza.** `tests/kali/test_http_history_service.py::test_execute_can_label_a_manual_replay`.

**Costo.** Molto basso. **Stato: Attuato.**

## C.8 Il contratto non è dove il modello lo legge (P5)

**Cosa succedeva.** La forma del ritorno non era nello schema inviato al modello
(`convert_to_openai_tool` manda solo argomenti + `description`): `derived_from` si scopriva
dopo la prima chiamata. La catena era insegnata a metà. E `request_ref` vinceva su
`method`/`path` **in silenzio**.

**Decisione.** Tre frasi nelle description + una nota di precedenza:

- su `search_http_history`: il risultato è una **lista di candidati**, non una verifica; elenca
  anche `absent` come operatore del gruppo di controllo;
- su `get_http_artifact`: **quando** usarlo, che i nomi header sono visibili (i valori
  sensibili redatti) e che va verificato `request.body.capture_state` prima di impegnare un id;
- su `exec`: **non** replicare a mano una richiesta registrata (si perde la lineage);
- precedenza: il pod riporta in `interpretations` la nota *"request_ref presente, method/path
  inline ignorati"* — zero cambi di API, un conflitto silenzioso diventa visibile.

**Attuazione.** `src/polymerhus/attack/hunting/hunter_tools.py` (tre description — quella di
`exec` **estesa**, non sostituita, per non cancellare il PARTITION GUARD già presente),
`hunting_pod.py` (`_inline_ignored`, assegnato **a ogni chiamata** perché una stessa istanza del
pod può servire più spec). Commit `4a48654`, più il fix finale `05e4a22`.

**Evidenza.** `tests/attack/test_http_history_tools.py::test_descriptions_teach_the_chain`,
`...::test_request_ref_precedence_is_reported`,
`tests/attack/test_hunting_pod.py::test_the_precedence_note_does_not_leak_across_calls_on_one_pod`.

**Costo.** Quasi zero — il miglior rapporto beneficio/sforzo di tutta la lista.
**Stato: Attuato.**

## C.9 Igiene operativa

| Voce | Stato | Dove |
|---|---|---|
| Indici covering + `ANALYZE` | **Attuato** `0418011` | `kali/http_history/store.py` |
| `busy_timeout` (due writer: addon + MCP) | **Attuato** `0418011` | `HttpHistoryStore.__init__` |
| Cache degli handle store a LRU (`_STORE_CACHE_MAX=32`, `close()` dell'evitto) | **Attuato** `7595fee` | `kali/http_history/service.py` |
| `stream_large_bodies` o cap esplicito sul buffering di mitmproxy | **Rinviato** | piano separato |
| health-check che verifica anche il **listener** del proxy, non solo la regola REDIRECT | **Rinviato** | `proxy_status` / `healthcheck.py` |
| retention e purge agganciate a uno **scheduler** | **Parziale** — `enforce_limits` è ora invocato dall'`execute` (throttled per progetto, best-effort); `retention_s` resta 0 per scelta, il byte cap è attivo (C.11) | `kali/http_history/service.py` |

## C.10 Ordine di intervento, con effetto e stato

| # | Intervento | Effetto misurabile | Sforzo | Stato |
|---|---|---|---|---|
| 1 | collegare i seam | la filiera esiste in produzione | basso | **Attuato** `b252bde`, `9552cf2` |
| 2 | guard fail-closed sul body | sparisce l'unico risultato falso silenzioso | minimo | **Attuato** `335eb3f` |
| 3 | 429/challenge ≠ negato | spariscono i falsi positivi su target protetti | basso | **Parziale** `a6b5d50` (429/5xx sì, challenge no) |
| 4 | indici covering + `ANALYZE` | query larghe non più 1.800-3.900× più lente | minimo | **Attuato** `0418011` |
| 5 | `absent` + `remove_header` | il gruppo di controllo diventa producibile | basso-medio | **Attuato** `0104eb9`, `11a8113` |
| 6 | tre frasi nelle description | l'agente usa la filiera correttamente | minimo | **Attuato** `4a48654`, `05e4a22` |
| 7 | proiezione esplicita + allowlist | il confine smette di essere default-allow | medio | **Parziale** `21c5d70` (proiezione sì, allowlist aperta) |
| 8 | `derived_from` in `execute_command` | il bypass non cancella più la lineage | minimo | **Attuato** `7d856f3` |

I primi sei, presi insieme, trasformano un sistema *"funziona nei test"* in un sistema
*"funziona in una caccia"*. Il settimo richiede una decisione dell'operatore sul trade-off
sicurezza/decidibilità (E.1). Il terzo — se il bersaglio è protetto — decide se i risultati
sono **veri** o solo **plausibili**, e resta a metà: è il candidato naturale per il prossimo
incremento.

---

# C.11 Il percorso recon non era collegato al capture plane (P0) — chiuso

**Cosa succedeva.** Un run di recon completo, verde e con il delta `unexplained == 0`, non
registrava **nulla** del traffico che aveva chiesto ai target:

| Sintomo osservato | Valore |
|---|---|
| `tool-log.jsonl`, invocazioni `httpx` e `katana` | `http_artifact_refs: []`, `capture_warning: null` |
| store del progetto, filtro `context/run_id = <run>` | **0** artifact |
| unica riga presente nello store | il **preflight**, `capture_context.run_id = ""`, `spec_id = ""` |
| `GET /projects/{id}/recon/{run_id}` → `per_job[].stats` | **nessuna** chiave `capture` |

Due cause distinte, entrambe silenziose.

1. **Il seam di esecuzione del test non dichiarava `capture_context`.** `build_pod_graph`
   inoltra il contesto solo a un seam la cui firma lo dichiara
   (`_accepts_capture_context`, ispezione di `inspect.signature`); il `ToolLog.exec_fn`
   dell'E2E aveva tre parametri, quindi il pod eseguiva `exec_fn(command, session_id,
   timeout)` senza contesto → kali riceveva `project_id` vuoto → nessun lease (il lease
   scatta solo con `config.enabled and project_id and lease_manager`) → nessun `REDIRECT`
   sulla veth del namespace → mitmdump non vedeva nulla. Nessun errore: solo un run che
   *sembrava* completamente riuscito.
2. **Le statistiche di copertura non sopravvivevano all'aggregazione.** `job_stats` in
   `pipeline.py` era costruito con una lista esplicita di campi e il sotto-dizionario
   `capture` del pod export non veniva mai foldato, quindi `recon_jobs.stats` non poteva
   rispondere a *"il traffico di questo job è stato registrato?"*.

**Decisione.**

- Il seam del test **dichiara** `capture_context` e lo inoltra a
  `pod_module.default_exec_fn`; il caso legacy a 3 argomenti resta supportato e dichiara
  `sent=false` (mai un falso "catturato").
- La copertura viaggia fino a `recon_jobs.stats[].capture` con un fold **additivo**:
  `refs` somma, `sent` è vero se **almeno un** pod ha chiesto la cattura, i `warning`
  distinti si conservano (uniti con `"; "`, la stessa regola di `_merge_scan_stats`) così
  che un pod "pulito" non cancelli il warning di un pod andato in pool esaurito.
  `sent=false, refs=0` ("non ha mai chiesto") e `sent=true, refs=0` ("ha chiesto e non è
  stato registrato") sono fatti **diversi** e restano distinti.
- `spec_id` = **discriminatore dell'asset del pod** (`url`, altrimenti hash dell'asset):
  risponde a *"cosa ha chiesto il pod incaricato di X"*, ed è l'unica delle chiavi di
  correlazione che nessun altro punto dello store riempie.
- Cattura **accesa di default** (`POD_HTTP_CAPTURE`, letto all'import), con kill-switch
  `POD_HTTP_CAPTURE=0`: il fallimento che chiude è la perdita silenziosa di evidenza
  riproducibile, e il costo operativo (fingerprint TLS del proxy, latenza) è dichiarato.
- Il **tetto di storage** diventa effettivo: `enforce_limits` era testato ma **nessuno lo
  invocava**. Ora l'`execute` di kali lo chiama, throttled per progetto
  (`KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S`, default 60 s) e completamente best-effort (un
  errore di housekeeping non tocca il risultato del comando). Default di compose:
  **1 GiB per progetto**; con un body-cap di 5 MiB per transazione significa centinaia di
  body pieni prima che i più vecchi vengano evacuati.
- **Retention resta 0** (deviazione consapevole dalla coppia "cap + retention"): cancellare
  per età elimina evidenza anche quando il disco non ha alcuna pressione. Il byte cap
  copre il caso "lo store cresce senza limite"; l'età non è un rischio da mitigare qui.

**Attuazione.**

| Pezzo | Dove |
|---|---|
| seam E2E capture-aware + contesto nel tool log | `tests/e2e/test_recon_crawl_katana_depth.py` |
| `capture_job_stats` + fold in `job_stats` | `src/polymerhus/recon/control/pipeline.py` |
| throttled best-effort di `enforce_limits` | `kali/http_history/service.py` |
| knob `enforce_interval_s` + cap di default | `kali/http_history/config.py`, `docker-compose.yml` |
| asserzioni di cattura/artifact/replay | `tests/e2e/test_recon_crawl_katana_depth.py` |

**Evidenza (2026-09-17).**

- **Accettazione sui commit congelati** (`afdd2a1`) - E2E live crawl-only, `katana -d 3`,
  progetto `81aa8c04-1849-4255-a6b3-b9dc8d92cc33`, run
  `ef27ec78-dca0-4f17-95bb-749d5e76e53a`, wall 13.9 s: `httpx` success (637 ms, 1 ref),
  `katana` success (10.613 s, 2 ref), `stats.capture = {sent: true, refs: 1|2,
  warning: null}` per entrambi i job; 3 artifact per `context/run_id`
  (`http_01M2QEQ7DC6JM96BB3JFSFR20W` GET `/` 200 per httpx,
  `http_01M2QEQ9P44GT9DYC8MQC95A7C` GET `/robots.txt` 200 e
  `http_01M2QEQ9PB94M5JFA1A54PZRM2` GET `/` 200 per katana), replay
  `http_01M2QEQMSDA7EMRQ6GEZMVEJPG` dalla baseline httpx con mutazione dichiarata
  (`X-Polymerhus-Replay-ef27ec78`) → **200** dal target. Delta invariato: `total=8 kept=8
  dropped=0 collected=1 unexplained=0`, gate control positivo. Orchestratore: 1 attore, 0
  turni.
- Prima esecuzione live dopo il fix (progetto `d1cc4864-0ab0-433a-af57-253db7288e68`, run
  `eb31545c-a103-420d-a516-d8a5339ff06d`): `httpx` 318 ms / 1 ref, `katana` 10.262 s / 2 ref,
  stessi esiti di cattura e replay → 200.
- Corroborazione **black-box** (stesso subset via API, container agent): run
  `235a15dd-8498-46d5-a79e-e19199fdde52` → `httpx` success (1.033 s, `refs=1`), `katana`
  success (10.62 s, `refs=2`), entrambi `sent=true, warning=null`; 3 artifact nello store
  per quel run. **La produzione cattura già**, una volta che esegue il codice del branch: il
  difetto era nel seam del test e nell'aggregazione delle stats.
- Costo sotto proxy vs baseline registrata: `httpx` 318 ms contro ~0.6 s, `katana -d 3`
  10.262 s contro ~10.5 s — dentro il rumore; il passaggio da mitmproxy non sposta la
  durata di questi job.

**Criteri di accettazione di #196, stato puntuale.**

| Criterio dell'issue | Stato | Cosa manca, se manca |
|---|---|---|
| ogni request/response in uscita dal container kali è registrata con ampiezza HAR-like | **Parziale** | vale per il traffico **in lease** (`project_id` presente) e sulle sole porte **80/443** (`REDIRECT`): un `execute_command` senza `project_id`, o un job su porta non standard, non è registrato. È una condizione dichiarata, non un silenzio |
| gli artifact sono interrogabili per qualunque attributo registrato | **Attuato** | indice EAV; verificato in produzione con filtri su `context/run_id` e `context/spec_id` |
| gli artifact sono durevoli e indirizzabili con un id stabile | **Attuato, con un tetto** | SQLite su volume + ULID; da C.11 il byte cap per progetto (1 GiB) può evacuare i più vecchi sotto pressione reale di byte |
| una spec dell'hunter (o il pod) può riferire una richiesta sicura per identificatore | **Attuato** | filiera C.1 (`request_ref` + tool `replay`) e ora anche il percorso recon; nessun layer di validazione (#191) |

**Limiti residui (dichiarati, non mitigati qui).**

| Limite | Effetto | Perché resta |
|---|---|---|
| `KALI_HTTP_NAMESPACE_POOL=8` vs `MAX_PODS=8` | oltre il pool l'esecuzione degrada **fail-open**: nessun lease, nessuna cattura, comando comunque eseguito | il numero di pod concorrenti per job è già il tetto; il degrado ora è **visibile** in `stats.capture` (`sent=true, refs=0, warning="capture unavailable: PoolExhaustedError…"`) invece che silenzioso |
| `REDIRECT` solo su tcp/80 e tcp/443 | il traffico dei job su porte non standard non viene registrato | richiede una decisione di topologia (Parte D) |
| fingerprint TLS del proxy + latenza | il target vede il proxy, non il client del pod | accettato: la riproducibilità vale il costo, e il costo non è misurabile come latenza su questo target |
| tetto di storage per progetto (1 GiB) | a saturazione i **più vecchi** artifact vengono evacuati | con retention 0 il taglio avviene solo sotto pressione reale di byte |

**Nota di deploy.** L'immagine agent **non** monta `src/` (il `COPY src/ /srv/src/` è del
build), quindi `--force-recreate` da solo serve il codice dell'immagine, non quello del
worktree: per la prova black-box il branch è stato reso visibile con un mount temporaneo di
`src/` (file di override fuori dal repo, nessun rebuild e nessuna modifica all'immagine).

**Stato: Attuato.**

Walkthrough didattico (prima/dopo sugli stessi job, cosa contiene un artifact rispetto al tool
log, limiti): `docs/design/http-proxy-history-walkthrough.md`.

---

# Parte D — Fuori scope, con il motivo e il trigger

Il piano dichiara fuori scope questi interventi; il motivo non è "non importanti", è che
**richiedono prerequisiti infrastrutturali** o una decisione operativa, e infilarli in questo
piano avrebbe mescolato una correzione di correttezza con un cambio di topologia di rete.

| Voce | Perché serve un piano separato | Trigger per riaprirlo |
|---|---|---|
| Pool di IP per lease (`SNAT` al posto del `MASQUERADE`) | serve una pool **instradabile** e una policy di allocazione | il rate limiting per-IP del target diventa il freno misurato |
| Rate limiter nel capture plane | il proxy è il punto naturale (vede tutti i namespace) ma va progettato con backoff per host | più namespace concorrenti sullo stesso target |
| Policy per-host di splice TLS | cambia la promessa di visibilità dei contenuti: è una scelta di prodotto | host ad alta sensibilità, o fingerprint-checking dimostrato |
| Separazione dell'egress scanning/hunting | richiede topologia di rete dedicata | un WAF che correla la campagna di scanning con l'hunting |
| `stream_large_bodies` | decisione sui limiti di memoria del proxy | body grandi ricorrenti nei target reali |
| Packaging (JSON+EAV vs proiezione pigra) | è una **ADR**, non un piano (Parte A.8) | il costo di A.6 diventa il collo di bottiglia |

---

# Parte E — Decisioni aperte per l'operatore

## E.1 Allowlist dei valori header: sicurezza ↔ decidibilità

**La scelta.** Oggi la redazione è **default-allow**: il valore passa a meno che il *nome* non
matchi la regex `_SENSITIVE_KEY_RE` o l'insieme `_SENSITIVE_HEADERS`
(`kali/http_history/sanitize.py`). L'alternativa è **default-deny sui valori**: visibili solo
per allowlist (`content-type`, `accept`, `host`, `user-agent`, `server`, `location`,
`x-request-id`, …), tutto il resto `[redacted]`.

| | Default-allow (oggi) | Default-deny (allowlist) |
|---|---|---|
| un header sensibile non previsto | **passa** | redatto |
| decidibilità dell'agente | maggiore | minore (meno valori visibili) |
| rischio di fuga | cresce con ogni header nuovo del bersaglio | bounded by design |

**Mediazione proposta** (se si adotta la allowlist): allowlist per i **valori** + query di
**presenza** consentite sui nomi sensibili. L'agente può chiedere *"portava un token?"*, mai
*"che token era"*. Serve una scelta esplicita perché cambia ciò che l'agente può dedurre.

## E.2 Challenge detection nel percorso deterministico

Va aggiunto il rilevatore di challenge (header `cf-ray` / `x-akamai-*`, corpi di interstitial,
`Server` noti) e mappato sull'esito terminale che **esiste già**
(`specific-defence-prevention`), esponendolo al percorso deterministico e non solo al triager?

- **a favore:** chiude la seconda metà di R2/R5, che è la classe di falso positivo con il danno
  maggiore (evidenza che *sembra* pulita);
- **contro:** i marker sono euristici e cambiano per vendor; un interstitial legittimo con
  `200` potrebbe essere classificato come difesa e trasformare un vero sintomo in
  "inconclusivo" (falso negativo).

Default prudente proposto: rilevare **e etichettare** (mai `symptom-confirmed` su una risposta
riconosciuta come challenge) mantenendo l'esito terminale **inconclusivo**, non
`specific-defence-prevention`, finché la verifica B.5 non dice che il rilevatore è affidabile
su almeno due vendor diversi.

## E.3 Proiezione pigra

Parte A.8. Decisione di timing, non di merito: va aperta solo se il costo misurato di A.6
diventa il vincolo. Da decidere **adesso** una sola cosa: il trigger contrattuale (una soglia
di spazio per progetto, o un tempo di scrittura p95).

---

# Parte F — Tracciabilità

| Decisione | File | Test | Commit |
|---|---|---|---|
| fail-closed sul body | `kali/http_history/service.py`, `kali/mcp_server.py` | `tests/kali/test_http_history_service.py` | `335eb3f` |
| indici covering + `ANALYZE` + `busy_timeout` | `kali/http_history/store.py` | `tests/kali/test_http_history_store.py` | `0418011` |
| `absent` (gruppo di controllo) | `kali/http_history/store.py` | `tests/kali/test_http_history_search.py` | `0104eb9` |
| `remove_header` negli override | `kali/http_history/replay.py` | `tests/kali/test_http_history_replay.py` | `11a8113` |
| difese ≠ esito applicativo | `src/polymerhus/attack/hunting/hunting_pod.py` | `tests/attack/test_hunting_pod.py` | `a6b5d50` |
| contratto nelle description + precedenza | `hunter_tools.py`, `hunting_pod.py` | `tests/attack/test_http_history_tools.py` | `4a48654`, `05e4a22` |
| proiezione capture context (`source_ip` fuori) | `kali/http_history/sanitize.py` | `tests/kali/test_http_history_sanitize.py` | `21c5d70` |
| lineage su `execute_command` | `kali/http_history/service.py`, `kali/mcp_server.py` | `tests/kali/test_http_history_service.py` | `7d856f3` |
| client app-side + binding search/get | `app/clients/kali_http_history.py`, `runtime.py`, `llm.py`, `hunting_agent.py` | `tests/attack/test_kali_http_history_client.py`, `test_http_history_wiring.py` | `b252bde` |
| tool `replay` nel pod di produzione | `pod/agents.py`, `pod/graph.py`, `pod/llm.py`, `pod/pod.py`, `runtime.py`, `pod/prompts.py` | `tests/attack/pod/test_replay_tool.py` | `9552cf2` |
| cache LRU degli handle store | `kali/http_history/service.py` | `tests/kali/test_http_history_service.py` | `7595fee` |
| pacchetto come verità + forma sparsa come indice | `kali/http_history/models.py`, `store.py` | `tests/kali/test_http_history_models.py`, `test_http_history_store.py` | decisione preesistente (A) |
| cattura recon nel pod (contesto + stats) | `recon/config.py`, `recon/domain/pod.py` | `tests/recon/test_pod_capture_context.py` | `12b55cb` |
| copertura di cattura nelle stats del job | `recon/control/pipeline.py` | `tests/recon/test_pipeline.py` | `c797ce5` |
| tetto di storage invocato dall'exec | `kali/http_history/service.py`, `kali/http_history/config.py`, `docker-compose.yml` | `tests/kali/test_http_history_service.py`, `test_http_history_config.py`, `test_http_history_deployment.py` | `f2e2ea1` |
| seam E2E capture-aware + asserzioni artifact/replay | `tests/e2e/test_recon_crawl_katana_depth.py` | stesso file (2 test veloci + run live) | questo commit |

---

# Parte G — Evidenza di verifica

| Gate | Comando | Esito |
|---|---|---|
| unit tier Kali | `pytest tests/kali -q -p no:cacheprovider` | **112 passed**, zero skip |
| gate E2E live (zero skip) | `KALI_MCP_URL=http://localhost:8000/mcp KALI_HTTP_E2E_TARGET=http://172.28.0.20/ pytest tests/e2e/test_http_proxy_history.py -vv -rs` | **1 passed**, nessuno skip |
| check live del client app-side | `default_http_search_fn('e2e-…', [], None, 1, None)` | artifact reale |
| cablaggio in produzione | `_default_hunter_builder` instrumentato | `default_http_search_fn` / `default_http_get_fn` bindati |
| cattura recon nel pod (unit) | `pytest tests/recon/test_pod_capture_context.py tests/recon/test_jobs.py -q` | **51 passed** |
| copertura di cattura nelle job stats (unit) | `pytest tests/recon/test_pipeline.py -q -p ambient_ticker` | **25 passed** |
| recon crawl-only live + cattura + replay | `pytest tests/e2e/test_recon_crawl_katana_depth.py -q -s` | **3 passed** (2 seam + 1 run live) |
| cattura black-box in produzione | `POST /projects/{id}/recon` sul container agent, subset `["httpx","katana"]` | `stats.capture = {sent: true, refs: 1\|2, warning: null}` |

**Workaround di sandbox dichiarato.** In questo ambiente la sveglia cross-thread del loop
asyncio non viene servita: `asyncio.run(...)` + `asyncio.to_thread(...)` completa il lavoro ma
non torna mai da `loop.shutdown_default_executor()`. I tier che usano quella coppia
(`tests/recon/test_pipeline.py`) sono stati eseguiti **per file** con un plugin di test
(`-p ambient_ticker`, fuori dal repo) che neutralizza quella attesa e tiene vivo il tick.
Non è una modifica di prodotto: senza il plugin il file resta appeso a fine test, con i test
già passati.

**Limite noto dell'ambiente** (non un difetto di questo branch, verificato al commit di fork):
il tier `tests/attack` non è eseguibile come albero intero in questo ambiente — diversi file
si bloccano (`test_hunting_runtime.py`, `pod/test_react_seams.py`, `pod/test_harness.py`,
`pod/test_tools.py`, due test di `pod/test_compaction_seam.py`) e
`test_hunting_surfer_tick.py` ha una failure preesistente. Il gate è stato quindi eseguito
**per file**; l'elenco completo e le evidenze sono nel ledger SDD del piano.

---

# Sintesi in una riga per decisione

1. **Pacchetto vs esploso** → pacchetto come verità, attributi come indice; resta così, con
   indici covering e igiene degli handle a renderlo sostenibile; proiezione pigra come unica
   via d'uscita se il costo cresce.
2. **WAF** → 429/5xx e difese non sono più esiti applicativi (attivo); challenge detection,
   identità di rete per lease, rate limiter e splice per-host restano fuori, con verifiche
   sperimentali da eseguire prima di dichiarare chiuso il rischio.
3. **Filiera, body, controllo, contratto, lineage** → chiusi e testati.
4. **Confine di sicurezza** → proiezione attuata; la politica sui valori resta una decisione
   dell'operatore, con un trade-off dichiarato fra sicurezza e decidibilità.
5. **Percorso recon** → collegato al capture plane: ogni invocazione porta
   `project_id`/`run_id`/`spec_id`, il traffico è ricercabile e riproducibile, la copertura
   (`sent`/`refs`/`warning`) è nelle stats del job; restano fuori pool oltre il tetto,
   porte ≠ 80/443 e il costo di fingerprint/latenza del proxy (C.11).
