# Prompt — Chiudere il fix del lease, poi test funzionale E2E: recon crawl-only, katana depth 3/4, orchestratore agente, confronto tool-log ↔ collezionato

## 0. Ruolo, dove lavorare, come si esegue

Sei l'implementatore di questo lavoro. Lavora **solo** nel worktree
`/home/alelxsalc03/Desktop/polyphemus/.worktrees/http-history-hardening`, branch
`feat/http-history-hardening`. Tutto ciò che tocchi va **committato lì**, non nel checkout
principale (`/home/alelxsalc03/Desktop/polyphemus`, branch `feat/browser-evidence-spa-debugging`).

Nel sandbox di questo ambiente **docker e le chiamate a `localhost` richiedono escalation**; i
comandi git di scrittura (`git add`, `git commit`) pure (l'indice è read-only senza escalation).
Le porte pubbliche sono: agent `8080`, kali `8000`, postgres `5432`, neo4j `7687`/`7474`.

Il progetto compose si chiama **`polymerhus`** ed è composto da
`-f docker-compose.yml -f docker-compose.e2e.yml`.

Nota di processo già osservata in questo ambiente: il **dispatch ai subagent non consegnava i
payload** (nessun task arrivava ai figli). Non perdere tempo a diagnosticarlo: se ti serve
delega, verificalo con un probe minimo e altrimenti procedi in-session.

## 1. Stato reale di partenza (verificato, non ricostruirlo)

**Stack: su e healthy.**
`postgres 172.28.0.3`, `neo4j 172.28.0.4`, `agent 172.28.0.5`, `kali 172.28.0.2`,
`http-e2e-target 172.28.0.20`, tutti su `polymerhus_polymerhus-net`.
Verifica: `curl -s localhost:8080/health` → `{"status":"ok","checks":{"postgres":true,"neo4j":true,"kali_mcp":true}}`.

**`.env` (git-ignored) è già stato modificato** — non rifarlo, verifica soltanto:
- `API_KEY_OPENROUTER` era **vuota**; la chiave vera stava sotto `OPENAI_API_KEY`, un nome che il
  catalogo dei provider **non legge** (`app/llm/providers.py` legge `API_KEY_<PROVIDER>`). Ora è
  valorizzata copiando quel valore.
- `LLM_MODEL_ANALYSER` **mancava**: 8 ruoli mappano su quella chiave e `validate_llm_config()`
  valida **tutti** i ruoli al boot, quindi l'agent moriva con `LLMConfigError` anche per un run di
  solo recon. Ora è `openrouter:deepseek/deepseek-v4-pro`.
- Ruoli già configurati: `LLM_MODEL_JOB_ORCHESTRATOR`, `LLM_MODEL_CONFIGURATOR`,
  `LLM_MODEL_TRIAGER`, `LLM_MODEL_CRAWLER` (tutti `openrouter:*`).
- `LANGFUSE_*` **mancano**: il tracing è **spento**, quindi il ragionamento dell'orchestratore
  **non è tracciato**. Va dichiarato, non dedotto.
- `env_file` è letto **alla creazione** del container: ogni modifica a `.env` richiede
  `up -d --force-recreate agent`, non un restart.

**Albero di lavoro attualmente SPORCO — questo è il punto più importante.** È in corso un fix
lasciato a metà:

```bash
cd /home/alelxsalc03/Desktop/polyphemus/.worktrees/http-history-hardening
git status --porcelain     # → " M kali/http_history/service.py"
git diff                   # → default_runner: da ["bash","-lc",command] a ["bash","-c",command]
```

Quel diff è **corretto e va mantenuto**: è la correzione del difetto descritto in §2.1. Manca però
tutto il resto (test, guard del banner, commit, verifica live) — vedi §3.

**Materiale già prodotto che NON va rifatto, solo letto:**
- Piano del lavoro precedente: `docs/superpowers/plans/2026-09-16-http-history-hardening.md`
  (11 task, tutti implementati — non rieseguirli).
- Decision record di design (pacchetto-vs-esploso, risk assessment WAF, registro problemi,
  decisioni aperte): `docs/design/http-proxy-history-hardening-decisions.md`.
- Ledger del run precedente con ruling, brief, report e review package:
  `.superpowers/sdd/2026-09-16-http-history-hardening/` (in particolare `progress.md`).

**Scratch utili, se ancora presenti in `/tmp`** (li ho scritti io, puoi riusarli):
`/tmp/probe_netns_exec.py` (probe del lease via MCP — è quasi il §3.3), `/tmp/first_crawl_run.py`
(primo run live: crea progetto, setta il seed, lancia recon, polla, legge il grafo),
`/tmp/katana_probe.sh` (probe katana a `-d 1/3/4` dentro kali).

**Artefatti della prova live già eseguita** (lasciati per ispezione): progetto
`66922e75-bbbc-4eb2-bad9-ae7b2d9885b7`, run `e62c8388-36e4-413b-aa65-bf68456a9072` — esito:
`httpx: degraded` (1 pod, 1 failed, 0 asset, 0.69s) e `katana: skipped`. È il sintomo di §2.1.

## 2. Cosa NON rifare (già verificato, rifarlo brucia budget)

### 2.1 Il difetto bloccante del lease (già diagnosticato, NON riscoprirlo)

Il runner del lease eseguiva `bash -lc`. Il **profilo di login ricostruisce il `PATH`** e butta via
quello esportato da `kali/entrypoint.sh`
(`/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:…`). Nel namespace in lease — dove
girano **tutti** i pod — la risoluzione reale è:

| tool | risolto nel lease | dove vive |
|---|---|---|
| `httpx` | `/usr/bin/httpx` — CLI **Python** (`Error: No such option: -u`) | `/root/go/bin/httpx` |
| `katana`, `naabu`, `subfinder`, `dnsx`, `puredns`, `ffuf`, `jsluice`, `arjun`, `kr`, `subzy` | **MISSING** | `/root/go/bin/…` |
| `whois`, `graphql-cop` | ok | — |

Inoltre `/etc/profile.d/zz-redamon-motd.sh` (base image `redamon-kali-sandbox`) stampa un banner
(`⚡ redagraph — tenant-scoped graph CLI`) su **stdout a ogni login shell non interattiva**, in testa
all'output di ogni comando: inquina l'input dei parser.

**Prova del rimedio** (già eseguita live, con il `PATH` assegnato *dentro* il comando, cioè dopo il
profilo): `httpx` → `/root/go/bin/httpx`, `katana` → `/root/go/bin/katana`, una chiamata reale al
target `172.28.0.20` → `status_code: 200`, `rc=0`, e **`http_artifact_refs` non vuoto** (la capture
plane di #196 registra l'artifact). Quindi: il blocco era solo il `PATH`.

**Attenzione al deploy del fix**: `kali/` è montato `./kali:/opt/kali:ro` con `PYTHONPATH=/opt`, quindi
il container esegue il codice della **directory da cui è stato avviato il compose**. Per servire il
codice del branch devi ricreare kali **dal worktree** con il progetto pinnato:

```bash
cd /home/alelxsalc03/Desktop/polyphemus/.worktrees/http-history-hardening
docker compose -p polymerhus -f docker-compose.yml -f docker-compose.e2e.yml up -d --force-recreate kali
```

`-p polymerhus` mantiene rete e nomi, così l'agent continua a raggiungerlo come `kali`.

### 2.2 Le tre trappole di boot (già risolte)

Non riaprirle; verifica solo `/health`:
- `API_KEY_OPENROUTER` vuota vs chiave sotto `OPENAI_API_KEY` (§1);
- `LLM_MODEL_ANALYSER` mancante → `LLMConfigError` all'avvio (§1);
- `neo4j` non partiva per un **riferimento a un network ID stantio** (la rete era stata ricreata):
  `failed to set up container networking: network … not found` → risolto con `--force-recreate`.
  In generale: dopo un drift di rete, `up -d` fallisce sui servizi già creati.

### 2.3 Il gate E2E di #196 è già verde

`tests/e2e/test_http_proxy_history.py` → `1 passed`, zero skip. Non rieseguirlo come se fosse la cosa
da provare.

### 2.4 La forma reale dei nodi del grafo

`GET /projects/{id}/graph` restituisce nodi nella forma

```json
{"id": "…", "name": "172.28.0.20", "type": "IP", "properties": {"address": "…", "project_id": "…"}}
```

La **label è in `type`**, le props in `properties`. Non esistono `labels`/`props`. Gli asset timbrati
da un tool portano `properties.source == "<tool>"` (katana timbra `source="katana"`). Una proiezione
sbagliata fa sembrare "0 asset" un run riuscito: è l'errore che ho già commesso io.

### 2.5 `tests/attack` non è eseguibile come albero intero

In questo ambiente diversi file si bloccano (`test_hunting_runtime.py`, `pod/test_react_seams.py`,
`pod/test_harness.py`, `pod/test_tools.py`, due test di `pod/test_compaction_seam.py`) e
`test_hunting_surfer_tick.py` ha una failure preesistente. Esegui **per file**. Il tier affidabile è
`tests/kali` (103 passed).

## 3. Primo lavoro (in quest'ordine): chiudere il fix del lease

È il prerequisito di tutto il resto: finché i pod non risolvono i tool, `-d 3` e `-d 1` danno lo
stesso esito e il test non misura nulla.

1. **Mantieni** il diff già presente in `kali/http_history/service.py` (`bash -c` non-login, con il
   suo commento che spiega perché).
2. **Test unitario** (TDD-style) in `tests/kali/test_http_history_runner.py`: asserisci che
   `default_runner` (a) non usi una login shell, (b) mantenga il prefisso `ip netns exec <ns>` quando
   c'è un namespace, (c) restituisca l'`ExecOutcome` con returncode/stdout e il path di timeout
   (`returncode=124`, stderr `timeout after …`). Usa `monkeypatch` su `subprocess.run` e ispeziona
   `argv`: non serve un processo reale.
3. **Guard del banner** in `kali/postrun.sh` (gira a ogni avvio del container: niente rebuild da
   17 GB). Inseriscilo prima dei due `echo "[postrun] …"` finali, idempotente e best-effort come il
   resto dello script (che per contratto **non deve mai abortire**):

   ```sh
   MOTD=/etc/profile.d/zz-redamon-motd.sh
   if [ -f "$MOTD" ] && ! grep -q POLYPHEMUS_NONINTERACTIVE_GUARD "$MOTD" 2>/dev/null; then
     sed -i '1i [ -z "$PS1" ] && return 0  # POLYPHEMUS_NONINTERACTIVE_GUARD' "$MOTD" 2>/dev/null || true
   fi
   ```

   (Il runner non userà più una login shell, quindi questo è **difesa in profondità** per ogni altro
   percorso login — un `bash -lc` manuale di un operatore, un runner futuro.)
4. `pytest tests/kali -q -p no:cacheprovider` → deve restare verde (103 + i nuovi test).
5. **Commit** sul branch (uno o due, messaggi `fix(kali): …`).
6. **Verifica live** (§3.7): ricrea kali dal worktree (§2.1) e riprova il percorso del lease.
7. **Preflight del lease** — proprio questo comando, attraverso il server MCP di kali, con un client
   come in `tests/e2e/test_http_proxy_history.py` (`fastmcp.Client`), `project_id` = un progetto
   nuovo del run:

   ```python
   command = ("export PATH=/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:$PATH; "
              "command -v httpx; command -v katana; "
              "httpx -u 172.28.0.20 -sc -title -td -server -silent -json; echo rc=$?")
   ```

   Atteso: `/root/go/bin/httpx`, `/root/go/bin/katana`, una riga JSON con `status_code: 200`,
   `rc=0`, `http_artifact_refs` non vuoto. Se vedi `/usr/bin/httpx` o `MISSING`, **fermati**: il fix
   non è in vigore e nessun test di crawl può passare.
   Nota: dopo il fix (shell non-login) quel `export PATH` non dovrebbe nemmeno servire — provalo
   **prima senza** l'export, e usa l'export solo come controprova/diagnostica.

## 4. Obiettivo del test E2E (il lavoro principale)

Costruisci ed esegui un test funzionale end-to-end che:

1. verifica lo stack healthy e che kali serva il codice del branch;
2. crea un progetto reale e gli assegna **il target di sempre: `172.28.0.20`** (IP nudo, mai URL);
3. esegue **solo la fase di crawling** del recon (nessuna analisi, nessuna fase JS/API) con katana
   configurato esattamente come nella fase di crawl ma a **`-d 3`** (o `-d 4`);
4. fa girare il recon con l'**orchestratore agente** di produzione (`decide_routing=None`), non con il
   seam iniettato;
5. cattura il **tool log** (comando katana realmente eseguito + stdout JSONL) e lo confronta con il
   **collezionato** (asset nel grafo + registri PG), con un verdetto esplicito su ogni delta.

Zero-skip: se lo stack è giù il test **fallisce**, non skippa (opt-out solo con `E2E_CRAWL_ALLOW_SKIP=1`).

## 5. Fatti verificati nel repo — usali, non ri-derivarli

**Katana e la fase di crawling**
- Catalogo: `src/polymerhus/recon/control/jobs.py`. `JOBS["katana"]` a **riga 156**;
  `command_template` alle **righe 243-248**, con **`-d 1` statico**:

```text
katana -u {target} -d 1 -jc -kf robotstxt -fx -td -c 10 -rl 50 -ct 240s -pcs -pcsm simhash -pcsd 3 -iqp -fsu -fst 10 -aff -ef css,scss,less,woff,woff2,ttf,eot,otf,map,png,jpg,jpeg,gif,svg,webp,ico,bmp,mp3,wav,mp4,webm,mov,pdf,zip -cos 'node_modules/|bower_components/|\.(bak|old|swp|orig|tmp)($|\?)' -silent -jsonl {auth_header}
```

  Il commento sopra la riga 173 documenta perché il default è 1 (a `-d 3` su cataloghi grandi il crawl
  sfonda `EXEC_TIMEOUT_S` e il pod torna senza output). **Il depth non ha alcun knob**: nessuna env,
  nessun campo di settings, nessun argomento per-run.
- `katana` è `configurator_mode="deterministic"`: il configuratore LLM del pod decide **solo**
  `rate_profile` (`PodConfig`, `recon/domain/pod.py:928`), non il comando.
- Fasi: `PHASES` (**riga 401**); la fase di crawl è `["katana","ffuf","steel_crawl"]`.
- Subset: `validate_job_subset` (**jobs.py:466**), `build_phase_plan` (**jobs.py:483**). Il `consumes`
  deve essere `Domain`, `Subdomain` (seed iniettato da `pipeline._inject_seed_host`) o prodotto da un
  job selezionato prima. → **Il subset minimo valido è `["httpx","katana"]`**; `["katana"]` da solo è
  rifiutato con `ValueError` (consuma `BaseURL`).
- Il binario katana installato supporta tutti i flag del template (`-pcs`, `-pcsm`, `-pcsd`,
  `-kb-endpoints`, `-aff`) — verificato. **Ma la patch è runtime-only e non sopravvive a un rebuild
  dell'immagine**: se ricostruisci kali, riverifica i flag prima di dare per buono un run.
- Il comando contiene **`-aff`**: sottommette davvero i form (mutazione, non discovery passiva). Con
  `172.28.0.20` è innocuo; su qualunque altro target serve autorizzazione esplicita.
- Punto di aggancio per il tee: `default_pod_invoke` fa `from polymerhus.recon.domain.pod import
  pod_graph` **a ogni chiamata** (`control/job_agent.py:293`), quindi
  `monkeypatch.setattr(polymerhus.recon.domain.pod, "pod_graph", build_pod_graph(exec_fn=<tee>))`
  funziona (stesso pattern di `tests/recon/test_pipeline_e2e.py`).

**Orchestratore agente**
- Default di produzione: `ReconOrchestratorActor` (ruolo sessione `job_orchestrator`), costruito da
  `run_pipeline` quando `decide_routing=None` (`control/pipeline.py:388-398`); il seam iniettabile
  esiste solo per i test.
- Ruoli/chiavi: `src/polymerhus/app/llm/providers.py:327-331`.
- **Limite reale**: emette solo **esclusioni per URL** (`RoutingDecision.exclusions`,
  `orchestrator_agent.py:63`) e viene consultato **solo se esistono segnali WAF**
  (`read_steering_signals` → Observation con `macro_kind` WAF su BaseURL, `control/pipeline.py:292`;
  gate `if signals:` a `pipeline.py:778`). Su `172.28.0.20` **non ci sono segnali**: l'attore viene
  costruito ma **non riceve turni**. Riportalo così com'è — vietato dichiarare che l'agente ha
  pilotato il crawl.

**API (agent su 8080)**
- `POST /projects` `{"name":"…"}` → `{"project_id":"…"}`
- `PUT /projects/{id}/settings` `{"recon":{"target_seed":"<host-o-ip>"}}` → `{"ok":true}`
- `POST /projects/{id}/recon` `{"jobs":["httpx","katana"],"with_analysis":false}` → `{"run_id":"…"}`
- `GET /projects/{id}/recon/{run_id}` → `{status,current_phase,stats,per_job}`; `…/stop`;
  `GET /projects/{id}/graph`; `GET /health`
- Errori da asserire: seed mancante → **400** ("no target_seed configured"); seed IPv6 → **400**;
  job sconosciuto/subset incoerente → **400**.

**Target**
- `target_seed` è **host o IP nudo, mai un URL** (`control/scope.py:47,80`): `http://172.28.0.20/`
  verrebbe classificato come dominio e produrrebbe uno scope spazzatura. `172.28.0.20` → modalità
  **host** (discovery soppressa) — ed è quello che vogliamo.
- L'IPv6 è progettato-ma-non-costruito e viene respinto al launch.

**Cosa è "collezionato"**
- Grafo: nodi `{id,name,type,properties}` (§2.4); `properties.source` per gli asset timbrati.
- PG: `recon_runs`, `recon_jobs` (`phase`, `job`, `status`, `stats`, `error`), `recon_js_resources`,
  `recon_evidence`. **Attenzione**: nel run di prova `recon_evidence` era **vuota** e lo **stdout del
  tool non è persistito**: il tool log va catturato col tee (in-process) o rieseguito (black-box), non
  letto da PG.
- Il gate del curatore è l'unica perdita ammessa: `noise_filter.filter_deltas(assets,
  scope_domain=<apex>)` (`recon/domain/noise_filter.py:452`), invocato in `curator.curate`
  (`recon/domain/curator.py:288-298`). Katana filtra già alla sorgente con `-ef`/`-cos`, quindi alcune
  cose non compaiono nemmeno nel tool log.

**Aspettativa sul target (non è un difetto)**: `172.28.0.20` è un servizio Python statico (poche righe
di testo, **nessun link, nessun form**). A `-d 1` e a `-d 4` rende **lo stesso insieme**. Quindi la
prova del depth è **il comando eseguito e la sua terminazione**, non la resa: un delta report quasi
vuoto è **il risultato corretto** su questo target. Asserisci la struttura, non la ricchezza, e
scrivilo nel report.

## 6. Il test da costruire

**A. Preflight** — `/health` con `postgres/neo4j/kali_mcp` a `true` (timeout esplicito, errore chiaro);
conferma che kali serva il codice del branch (§2.1) e che il lease risolva i tool (§3.7).

**B. Progetto e target** — `POST /projects` con suffisso univoco (es. `e2e-crawl-<uuid8>`);
`PUT /settings` con `target_seed=172.28.0.20` dopo aver validato che non sia URL né IPv6; asserisci il
**400** sul launch senza seed (progetto usa-e-getta separato) — prova che il guard è vivo.

**C. Run: solo crawling, katana `-d 3`** — launch con `jobs=["httpx","katana"]`,
`with_analysis=false`; asserisci `run_id` leggibile subito da `GET /recon/{run_id}`; asserisci che
**nessuna analisi** sia partita per quel run (nessun `analysis_runs` correlato / nessun drain);
asserisci dal `per_job` che i job sono esattamente `httpx` e `katana` e che
`jsluice`/`httpx_reprofile`/`arjun`/`kiterunner`/`graphql-cop` **non compaiono** — è la prova che "solo
la fase di crawling" è stata eseguita. Asserisci in modo duro che il **comando realmente eseguito**
contenga `-d 3` e che ogni altro flag sia **byte-identico** al template di produzione (diff carattere
per carattere, esclusi `{target}` e `{auth_header}`).

**D. Cattura del tool log** — aggancia l'exec seam sostituendo `polymerhus.recon.domain.pod.pod_graph`
con `build_pod_graph(exec_fn=<tee>)`; il tee inoltra a `default_exec_fn` e scrive una riga per
invocazione su `tool-log.jsonl`: `{phase, job, asset, command, returncode, duration_ms, stdout_path}`;
stdout in file separato per invocazione, con `capture_state` (`captured`/`omitted`+motivo) e cap
esplicito — **mai** troncare in silenzio. Il log deve contenere il **comando katana completo**.

**E. Confronto tool-log ↔ collezionato** — sul tool log reale, con i componenti di produzione (non
reimplementare la logica): `katana_parser.parse(stdout)` → delta;
`gate_kept = noise_filter.filter_deltas(delta, scope_domain=<apex>)`;
`dropped_by_gate = delta − gate_kept` (spiega ogni drop con la regola che l'ha colpito);
`collected` = nodi del grafo con `properties.source == "katana"` (§2.4). Report con `collected`,
`dropped_by_gate` (con esempi), `out_of_scope`, `unexplained`. Asserzioni: `unexplained == 0`; nessun
nodo `source=katana` che non provenga dal tool log; il report **elenca** i drop attesi ("0 drop" non è
un risultato valido di per sé). Confronta anche `recon_jobs.stats` del job katana con i conteggi del
parse: divergenza ⇒ fail con dettaglio.

**F. Cleanup e artefatti** — `tool-log.jsonl`, `stdout/*`, `collected.json`, `delta-report.md` in una
dir di run dedicata e git-ignored (o `tmp_path` per i test pytest). Se il run è ancora vivo allo
scadere: `POST /recon/{run_id}/stop`, poi fail con la causa.

## 7. Criteri di accettazione (hard)

1. `/health` verde, progetto creato via API, seed = `172.28.0.20` (mai URL).
2. Run con esattamente `["httpx","katana"]`, `with_analysis=false`, nessuna fase successiva eseguita.
3. Il comando katana eseguito contiene `-d 3` (o `-d 4`) e per il resto è identico al template di
   produzione.
4. Orchestratore: attore costruito per il run; report esplicito di **se e quante volte** ha ricevuto
   turni di steering. Su questo target: `started, no steering signal to act on`.
5. Tool log catturato con comando + stdout + `capture_state` esplicito.
6. `unexplained == 0` e tutti i drop del gate spiegati ed elencati.
7. Zero skip: stack giù ⇒ fail. Bounded: timeout wall-clock del run, `-ct 240s` **non** alterato.
8. I job `httpx` e `katana` **non** sono `degraded`/`skipped`: se lo sono, **fail** e mostra il motivo
   (è il sintomo del difetto §2.1, non un esito accettabile).

## 8. Decisioni (2 con default già scelto)

**D1 — come si imposta `-d 3/4`.** *Raccomandata*: `KATANA_DEPTH` in `src/polymerhus/recon/config.py`
(default `"1"`, come gli altri knob) e template costruito per **concatenazione**, non con f-string:

```python
command_template=(
    "katana -u {target} -d " + KATANA_DEPTH + " -jc -kf robotstxt -fx -td …
)
```

Una f-string richiederebbe di raddoppiare `{target}`/`{auth_header}` per sopravvivere al fill. Test
unitario: default `-d 1`; con `KATANA_DEPTH=4` il comando contiene `-d 4` e ogni altro flag è
byte-identico. *Gotcha operativo*: `JOBS` è costruito **all'import** → l'env va impostata **prima**
che l'agent parta (`docker compose … up -d --force-recreate agent`); impostarla su un container già
avviato non ha effetto. *Alternativa a costo zero di sorgente*: in un test in-process,
`monkeypatch.setitem(jobs.JOBS, "katana", job.model_copy(update={"command_template":
tmpl.replace("-d 1", "-d 3")}))` — il template di produzione resta `-d 1`.

**D2 — chi guida il run.** *Raccomandata*: **driver in-process** (progetto e settings via API,
`run_pipeline(project_id, run_id=repository.open_run(...), job_subset=["httpx","katana"],
with_analysis=False)` con il tee di D) → tool log **deterministico, stesso run, zero drift**,
orchestratore reale (`decide_routing=None`). Richiede che il processo di test raggiunga
PG/neo4j/kali su localhost (porte pubblicate) e abbia le chiavi LLM in env.
*Alternativa black-box*: guida tutto via API (nessun import del pipeline) — più fedele al "tira tutto
su", ma il tool log diventa una **seconda esecuzione** dello stesso comando: applica allora un budget
di drift esplicito (es. ≤5%, ogni item elencato) e dichiara che le due esecuzioni sono indipendenti.
In quel caso D1 **deve** essere la variante con knob d'ambiente.

**D3 — katana davvero da solo?** No: `["httpx","katana"]` è il minimo valido del validatore statico.
Se servisse *strettamente* la sola fase di crawl, bisognerebbe seminare BaseURL nel grafo prima e
aggirare il piano (`PHASES`/`JOBS` patchati o subset `None` + piano ristretto): non farlo, e documenta
la scelta.

## 9. Vincoli

- Target **solo** `172.28.0.20` (laboratorio, nostro). Nessun target di terze parti.
- Nessun nuovo segreto in repo, log, report o artefatti; le chiavi restano in `.env`/env, che è
  git-ignored.
- Nessuna modifica distruttiva a compose, volumi o dati esistenti; progetti e run nuovi a ogni
  esecuzione.
- Non alterare gli altri flag di katana né gli altri job: "come è configurato nella fase di crawling,
  solo depth 3/4".
- Non allargare il budget oltre il necessario; se il depth 3/4 sfonda il timeout, **fail con la causa**
  e proponi un target più piccolo — mai un silent downgrade a `-d 1`.
- Commit **solo** sul worktree/branch di hardening.

## 10. Deliverable e report

1. Il fix del lease chiuso: test unitario + guard del banner + commit.
2. Il codice del test E2E (+ eventuale knob/test unitario di D1) in `tests/e2e/…` o `tests/recon/…` con
   marker live.
3. Il comando esatto per eseguirlo e il suo output.
4. Un report finale con: target e scope mode; **il comando katana completo con `-d N` evidenziato**;
   `run_id` e per-job status; esito dell'orchestratore (costruito? turni? su quali segnali?); conteggi
   del delta report con i drop spiegati; **la resa attesa e perché** (il target è povero: dillo);
   eventuali deviazioni dalle decisioni, con motivazione; e ogni punto in cui il test ha dovuto
   tollerare qualcosa.

Se una parte non è verificabile dall'esterno (per esempio i turni dell'orchestratore, con Langfuse
spento e il ragionamento non tracciato), **dillo esplicitamente** invece di dedurla: un test che passa
senza poter mostrare l'evidenza è un falso verde.
