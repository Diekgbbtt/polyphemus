# Prompt — Cattura HTTP-history (#196) anche per i pod di recon, con prova live di riproducibilità

## 0. Ruolo, dove lavorare, come si esegue

Sei l'implementatore. Lavora **solo** nel worktree `/home/alelxsalc03/Desktop/polyphemus/.worktrees/http-history-hardening`, branch `feat/http-history-hardening`. Tutto ciò che tocchi va **committato lì** (non nel checkout principale, che è su `feat/browser-evidence-spa-debugging`).

Nel sandbox di questo ambiente **docker, localhost e `git add`/`commit` richiedono escalation**. Il progetto compose è `polymerhus` con `-f docker-compose.yml -f docker-compose.e2e.yml`. Porte: agent 8080, kali 8000, postgres 5432, neo4j 7687/7474. Target di laboratorio: **`172.28.0.20`** (IP nudo, mai URL).

## 1. Obiettivo

Il percorso dei pod di recon deve mandare al terminale kali il proprio **capture context** #196, così che **ogni richiesta HTTP chiesta dai tool di recon** finisca nello store del progetto, sia correlabile (run/sessione/asset) e sia **riproducibile** (`search_http_history` → `get_http_artifact` → `replay_http_request`). Oggi non lo fa: nessun chiamante recon costruisce un `CaptureContext`, quindi `project_id` è vuoto, il lease non viene preso, il traffico non passa dal proxy e `http_artifact_refs` resta vuoto. La capture plane esiste e funziona (è provata dal percorso hunting e dal preflight MCP), è **il chiamante recon che non è mai stato collegato**.

Catena causale già verificata (non riscoprirla):

| # | Punto | File |
|---|---|---|
| 1 | il nodo `execute` chiamava `exec_fn(command, session_id, timeout)` senza contesto | `src/polymerhus/recon/domain/pod.py` (nodo `execute` in `build_pod_graph`) |
| 2 | `default_exec_fn` accetta `capture_context` e fa `args.update(capture_context.as_mcp_args())` solo se glielo passano | stesso file |
| 3 | il lease si prende solo `if config.enabled and project_id and lease_manager` | `kali/http_history/service.py:240` (`execute`) — con `project_id=""` niente lease **e nemmeno un `capture_warning`** |
| 4 | la REDIRECT verso mitmdump è installata **per lease**, sulla veth del namespace | `kali/http_history/namespaces.py:75-80` |
| 5 | l'attribuzione è per IP sorgente → registry del lease | `kali/http_history/namespaces.py:178` |

Confronto: il percorso hunting invece lo fa — `src/polymerhus/attack/hunting/pod/graph.py:259` costruisce il `CaptureContext` e `attack/hunting/pod/tools.py:97-114` lo inoltra al terminal solo se la firma lo dichiara.

## 2. Stato reale di partenza (verificato — non rifarlo)

**Committato sul branch (3 commit nuovi, oltre alla storia precedente):**

- `cab5af7` fix(kali): il runner del lease usa **shell non-login** (`bash -c`) + guard del MOTD in `kali/postrun.sh`. Verificato live: senza `export PATH` nel comando, il preflight risolve `/root/go/bin/httpx` e `/root/go/bin/katana`, chiamata reale al target con `status_code: 200`, `rc=0`, `http_artifact_refs` non vuoto, nessun banner. `tests/kali` → 107 passed.
- `a429d9d` feat(recon): knob `KATANA_DEPTH` (default `"1"`), template katana costruito per concatenazione; 3 test in `tests/recon/test_jobs.py`.
- `ca23cca` test(e2e): `tests/e2e/test_recon_crawl_katana_depth.py` — crawl-only reale, progetto+settings+guardie via API, pipeline **in-process** con tee sul seam exec, confronto tool-log ↔ grafo/PG, controllo positivo del gate, orchestratore reale (attore costruito 1 volta, **0 turni**, nessun segnale WAF → "started, no steering signal to act on"). Passa con `-d 3` e `-d 4`. Artefatti in `.e2e-artifacts/recon-crawl-katana-depth/<stamp>-<id>/` (git-ignored).

**Già live e sano:** kali è stato ricreato dal worktree (`-p polymerhus ... up -d --force-recreate kali`) e serve il codice del branch; `/health` verde; il preflight del lease passa.

**Nell'albero di lavoro, NON committato (è il lavoro da proseguire):**

```
 M src/polymerhus/recon/config.py     (+20)   POD_HTTP_CAPTURE, default ON, kill-switch env
 M src/polymerhus/recon/domain/pod.py (+131)  helper + forwarding + stats di copertura
?? tests/recon/test_pod_capture_context.py   6 test, tutti verdi
```

Contenuto preciso:

- `config.py`: `POD_HTTP_CAPTURE` (env omonima, default acceso, valori off: `0/false/no/off`), letto all'import come gli altri knob.
- `pod.py`: `_accepts_capture_context(fn)` (ispezione firma, così i fake a 3 argomenti restano validi), `pod_capture_context(state)` che costruisce `CaptureContext(project_id, run_id, spec_id=_pod_asset_discriminator(input_asset), session_id)`, le closure `capture_context_for`/`capture_was_sent` dentro `build_pod_graph`, il nodo `execute` che inoltra `capture_context=` **solo se il seam lo dichiara**, e `_capture_stats(state, exec_result, sent=...)` scritto nelle stats del pod sia nel nodo curator sia nel nodo fail come `{"sent", "refs", "warning"}` → arriva in `recon_jobs.stats[].capture`.
- `tests/recon/test_pod_capture_context.py`: contesto inoltrato; seam legacy intatto; nessun progetto → nessun contesto; kill-switch; stats `sent/refs/warning`; 6/6 verdi.

**Decisioni approvate dall'operatore (vincolanti):**

1. Cattura **accesa di default** con kill-switch `POD_HTTP_CAPTURE=0`, **accompagnata da un tetto di storage** (vedi §5.C).
2. `spec_id` = **discriminatore dell'asset del pod** (l'unità di lavoro), così si può rispondere a "cosa ha chiesto il pod incaricato di X". È interrogabile come `side="context", namespace="core", key="spec_id"` (`kali/http_history/index.py:110`).
3. Nessun flag per-job, nessun uso di `variant_ref`, nessuna duplicazione dei **contenuti** raw: quelli restano dell'evidence archive. Qui l'obiettivo è **replay/audit delle transazioni**.

## 3. Trappola ambientale CRITICA (costa ore se non la conosci)

In questo sandbox **la sveglia cross-thread di asyncio non viene servita**: il loop si risveglia solo sui timer.

Prova minima, tre righe, nessun codice del progetto:

```bash
python -c "
import asyncio
async def main():
    print(await asyncio.to_thread(lambda: 42), flush=True)
asyncio.run(main())
"
# stampa 42 (0.001s) e poi NON esce mai: rc=124 → il blocco è nello shutdown dell'executor del loop
```

Conseguenze operative:

- I test che usano `asyncio.run(...)` + `asyncio.to_thread(...)` possono sembrare appesi: il **lavoro è completato** (i pod girano, gli `upsert_job` entrano ed escono), ma il loop riprende solo al tick successivo. Con un ticker da 1s il pipeline completa; senza, avanza a scatti da 10s (il tick dell'heartbeat) e appare bloccato.
- Con il wiring di cattura, `tests/recon/test_pipeline_e2e.py::test_pipeline_e2e_subfinder_dnsx_httpx` ora cade in questa classe (prima passava in 0.44s perché l'intera corsa stava dentro il primo burst). **Non è un bug del prodotto: non toccare il codice di produzione per questo.** Il prompt originale già documenta che in questo ambiente "diversi file si bloccano" (`test_hunting_runtime.py`, `pod/test_react_seams.py`, `pod/test_harness.py`, `pod/test_tools.py`, due di `pod/test_compaction_seam.py`).
- Mitigazioni per la nuova sessione: nel driver in-process dell'E2E, se la corsa resta ferma, aggiungi un ticker `asyncio.create_task(...)` che dorme 1s in loop per la durata del run (workaround di sandbox, da dichiarare nel commento); in alternativa guida la corsa **black-box** via container agent. Per i tier unit, verifica **per file** con `timeout` e dichiara lo scostamento.
- Scratch riutilizzabile: `/tmp/wdplug.py` (plugin pytest con submit-trace/enter-exit timestampati, ticker e dump dei task) e `/tmp/repro.py` (riproduce il pipeline fuori da pytest, dove **completa in 7s**). Sono usa-e-getta: non committarli.

## 4. Cosa NON rifare

- Il fix del lease (shell non-login + guard del MOTD): già committato e verificato live.
- Il knob `KATANA_DEPTH` e i suoi test.
- Il test crawl-only nella sua parte già verde (progetto/seed/guardie 400, subset `["httpx","katana"]`, nessuna analisi, comando byte-identico al template tranne la depth, delta report con `unexplained == 0`, controllo positivo del gate, durata katana ~10.5s a `-d 3`).
- Non riaprire le tre trappole di boot (chiavi LLM, `LLM_MODEL_ANALYSER`, network ID stantio) e non ricreare l'immagine kali (basta `--force-recreate`, altrimenti si perde la patch runtime di katana con `-pcs/-pcsm/-pcsd/-aff`).

## 5. Lavoro da fare

**A. Estendere il test E2E live con la prova della cattura** — `tests/e2e/test_recon_crawl_katana_depth.py`:

1. per **ogni** invocazione HTTP nel tool log (`httpx`, `katana`): `http_artifact_refs` **non vuoto** e `capture_warning is None`;
2. da `GET /projects/{id}/recon/{run_id}`: `stats["capture"] == {"sent": True, "refs": >0, "warning": None}` per entrambi i job;
3. trovare gli artifact con `search_http_history` (client app-side `src/polymerhus/app/clients/kali_http_history.py`, o MCP diretto): filtro `context/run_id` = run del test, filtro `context/spec_id` = asset del pod, e un filtro sull'url della richiesta; asserire method/url/status attesi;
4. `get_http_artifact` + **`replay_http_request`** con una mutazione dichiarata → 200 dal target: è la dimostrazione di "riprodurre ciò che il recon ha chiesto";
5. mantenere tutte le asserzioni esistenti e scrivere i nuovi esiti negli artefatti del run.

**B. Misurare il costo**: durata di httpx/katana sotto proxy vs baseline registrata (httpx 0.6s, katana 10.5s a `-d 3`, 10.6s a `-d 4`, un solo endpoint `/`, 8 delta, grafo 12 nodi con `source=katana` su 1 `Endpoint`). Riporta anche il comportamento del pool (`KALI_HTTP_NAMESPACE_POOL=8` in `docker-compose.yml:121` contro `MAX_PODS` 8 in `.env`, 20 nel default di codice): oltre il pool l'esecuzione degrada **fail-open non catturata**, e ora lo dichiara in `stats.capture`.

**C. Tetto di storage (approvato, manca)** — `HttpHistoryService.enforce_limits` esiste ed è testato ma **nessuno lo chiama in produzione** (verificato: solo `tests/kali/test_http_history_service.py`). Con la cattura accesa di default lo store cresce senza limiti (`KALI_HTTP_PROJECT_MAX_BYTES=0`, `KALI_HTTP_RETENTION_S=0`). Implementa un chiamante **throttled e best-effort** (es. da `execute`, al massimo una volta per progetto ogni N secondi, no-op quando entrambi i limiti sono 0) + test; e decidi il default del byte-cap in compose. Motiva il valore della retention (a 0 = nessuna cancellazione per età, perché cancella evidenza anche senza pressione su disco) — è una deviazione consapevole dalla raccomandazione "cap + retention", da dichiarare.

**D. Corroborazione black-box**: lancia lo stesso subset via API sul container agent e verifica che anche lì `stats.capture.refs > 0`. Attenzione: il container agent esegue il codice della directory da cui è stato avviato il compose → per servire questo branch va ricreato dal worktree (`docker compose -p polymerhus -f docker-compose.yml -f docker-compose.e2e.yml up -d --force-recreate agent`), e `env_file` è letto **alla creazione**.

**E. Documentazione**: nuova voce nel decision record `docs/design/http-proxy-history-hardening-decisions.md` (Parte C) con: cosa succedeva (percorso recon mai collegato), decisione (spec_id = asset, default ON + kill-switch), attuazione, evidenza, e i limiti residui: pool ≥ MAX_PODS, REDIRECT solo tcp/80 e tcp/443 (i job su porte non standard restano fuori), costo di fingerprint/latenza del passaggio da mitmproxy, tetto di storage.

**F. Commit** sul branch (es. `feat(recon): capture recon pod HTTP traffic in the #196 plane` + un secondo per il cap dello store), con il report finale che include: comando katana completo con la depth, run_id, per-job status, esito orchestratore (attore costruito / turni / su quali segnali), artifact trovati e replay, durate, e ogni punto in cui si è tollerato qualcosa.

## 6. Comandi

```bash
cd /home/alelxsalc03/Desktop/polyphemus/.worktrees/http-history-hardening
set -a; . /home/alelxsalc03/Desktop/polyphemus/.env; set +a
.venv/bin/python -m pytest tests/recon/test_pod_capture_context.py -q -p no:cacheprovider
.venv/bin/python -m pytest tests/kali -q -p no:cacheprovider
.venv/bin/python -m pytest tests/e2e/test_recon_crawl_katana_depth.py -q -s -p no:cacheprovider   # con escalation
```

Il test E2E richiede l'env reale (chiavi LLM) e riscrive da sé gli endpoint compose/`.invalid` verso `localhost` con override `E2E_*`. Artefatti in `.e2e-artifacts/recon-crawl-katana-depth/`.

## 7. Vincoli

- Target **solo** `172.28.0.20`; nessun nuovo segreto in repo/log/artefatti; nessuna modifica distruttiva a compose/volumi; progetti e run nuovi a ogni esecuzione.
- Non alterare gli altri flag di katana né gli altri job; non toccare `-ct 240s`.
- Zero-skip nell'E2E: stack giù ⇒ **fail** (opt-out solo con `E2E_CRAWL_ALLOW_SKIP=1`).
- Se un job torna `degraded`/`skipped`, è il sintomo del difetto: **fail** e mostra il motivo.
- Commit solo nel worktree/branch di hardening.

## 8. Criteri di accettazione (hard)

1. E2E live verde con le nuove asserzioni: `http_artifact_refs` non vuoto per httpx e katana, `stats.capture.sent == True` e `refs > 0` per entrambi.
2. Artifact trovabile per `context/run_id` e per `context/spec_id`, e **replay** riuscito con una mutazione dichiarata.
3. Delta report invariato: `unexplained == 0` in entrambe le direzioni, nessun drop non attribuito.
4. Nessuna regressione: `tests/kali` verde, `tests/recon/test_pod_capture_context.py` verde, e i tier per-file eseguiti con `timeout` (dichiarando la classe di hang ambientale di §3).
5. Report finale con i numeri (durate, refs, pool) e con l'elenco esplicito di ciò che non è verificabile dall'esterno — in particolare: con Langfuse spento il reasoning dell'orchestratore **non è tracciato**, quindi si riporta il conteggio dei turni, mai una deduzione.
