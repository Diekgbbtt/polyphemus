# LLM Rate-Aware Recon Configurator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** misurare con Vegeta una postura per target e affidare a un unico Configurator LLM stateful la scelta e la configurazione dei pod di recon, senza admission numerica o enforcement controller-owned sui pod proposti.

**Architecture:** l'Auth Gateway termina al solo `GatewayVerdict`; subito dopo, la pipeline invoca direttamente il mapper Vegeta e persiste lo stesso `RateProfile` negli stats e nello YAML. A ogni confine di fase un sync leaf stateful, indirizzato da `ConfiguratorSession(run_id)`, legge la postura tramite il tool read-only, vede esclusivamente i job canonici e gli input preparati della fase, e restituisce un piano chiuso che la pipeline valida solo per eseguibilita e materializza.

**Tech Stack:** Python 3.12, asyncio, Pydantic v2, LangChain `create_agent`/`stateful_turn`, LangGraph, PyYAML, Vegeta/Kali MCP, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-28-llm-rate-aware-recon-configurator-design.md`

**Execution status:** implemented in eight reviewable commits, from
`76e4894d` (baseline profile without an LLM verdict) through `de918a81`
(two-run functional E2E). The post-implementation QA record and pull-request
gate are documented in
`docs/superpowers/notes/2026-09-29-llm-rate-aware-configurator-qa.md`.

## Global Constraints

- Un solo ruolo `configurator` in `providers.py` e `skills.py`; nessun ruolo per fase, job o tool.
- L'Auth Gateway possiede soltanto autenticazione, account e replayability e termina al `GatewayVerdict`.
- Il mapping Vegeta e il suo hard safety budget restano deterministici e controller-owned; il mapping baseline non esegue bypass probing.
- Il `RateProfile` viene persistito prima in `recon_runs.stats["rate_limit"]`, poi nello YAML per target; una scrittura YAML fallita rende la run `failed` prima delle fasi.
- La scelta dei pod e dei loro parametri rate-aware e affidata al modello. Il runtime non confronta rate, thread, concorrenza, delay o durata con la postura e non inoltra una `TrafficPolicy` per correggerli.
- Il runtime valida soltanto forma ed eseguibilita: fase/target, job presente nei candidati canonici, `input_id` offerto, comando shell non vuoto oppure `None` per un job agentico.
- Una decisione tecnicamente invalida viene rifiutata atomicamente e rende la run `failed` prima dei pod della fase; `pods=[]` e invece una decisione valida.
- I template inviati al modello non contengono segreti. `{auth_flags}` e `{session}` restano placeholder controller-owned e vengono risolti soltanto nel pod.
- Runner, Triager e Configurator leggono la postura tramite l'unico tool read-only `rate_limit_posture`; nessun agente scrive la postura.
- Un file corrotto produce `unreadable`, mai una postura assente. Il prompt impone al modello di omettere traffico target-facing, ma non esiste un secondo checker semantico.
- Ogni slice segue RED -> GREEN, include una mutazione avversariale esplicita e termina in un commit separato dopo il checkpoint dell'operatore.
- I test si eseguono dalla radice del worktree con `.venv/bin/python -m pytest ...`; `artifacts/issue-238-concurrency/` resta fuori da staging e commit.

## Review Focus

- Un `browser_only` deve causare zero invocazioni Vegeta e produrre una postura conservativa `inconclusive`; Task 2 lo pinna.
- Un output LLM che mescola una proposta valida e una con `input_id` inventato non deve eseguire il sottoinsieme valido; Task 6 prova il rifiuto atomico.
- Lo stesso `input_id` ripetuto o riferito al job sbagliato non deve duplicare/spostare un pod; Tasks 4 e 6 lo provano.
- Il Configurator non deve mai vedere cookie, token o header autenticati nel prompt, ma il pod deve ancora ricevere gli `auth_flags` al momento dell'esecuzione; Tasks 4 e 5 lo provano.
- Due fasi della stessa run devono usare `run:<run_id>:configurator`, mentre due run non devono condividere memoria; Task 4 lo prova.

## File Structure

| File | Responsabilita |
|---|---|
| `src/polymerhus/recon/control/rate_limit_runner.py` | esegue il mapping bounded e costruisce il profilo baseline senza verdict LLM |
| `src/polymerhus/recon/control/orchestrator_agent.py` | Auth Gateway soltanto |
| `src/polymerhus/recon/control/configurator.py` | contratti, offerte di fase, validazione tecnica e sync stateful turn |
| `src/polymerhus/recon/control/prompts/rate-aware-configurator.md` | workflow prudente e trust-based del Configurator |
| `src/polymerhus/app/llm/session_address.py` | `ConfiguratorSession(run_id)` |
| `skills/rate-aware-recon-configuration/SKILL.md` | conoscenza riusabile dei flag dei tool |
| `src/polymerhus/recon/domain/pod.py` | espansione runtime del comando proposto e placeholders segreti/sessione |
| `src/polymerhus/recon/control/pipeline.py` | mapping diretto, invocazione per fase e materializzazione del solo piano LLM |

---

### Task 1: Profilo baseline senza verdetto LLM

**Files:**
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py`
- Test: `tests/recon/test_rate_limit_runner.py`

**Interfaces:**
- Consumes: `RateLimitHarness.map() -> MappedControl`, `BudgetLedger.usage`, evidenze raccolte.
- Produces: `RateLimitHarness.build_baseline_profile() -> RateProfile`, con `bypass_outcome="inconclusive"` e `bypass_findings=[]`.
- Preserves temporarily: `build_profile(RateLoopVerdict)` fino alla rimozione del secondo turno in Task 3.

- [x] **Step 1: Write the failing tests**

Aggiungere `test_baseline_profile_is_built_only_from_mapper_evidence` e `test_baseline_profile_never_imports_bypass_claims`. Usare evidenze letterali e verificare rate, policy, usage, artifact refs e campi bypass; la mutazione da uccidere e copiare `_findings` nel profilo baseline.

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_runner.py -q`

Expected: FAIL perche `build_baseline_profile` non esiste.

- [x] **Step 3: Implement the minimal builder**

Estrarre la costruzione comune del `RateProfile` in un helper privato che riceve esplicitamente bypass outcome/findings. `build_baseline_profile()` usa sempre `inconclusive`/`[]`; il metodo legacy conserva temporaneamente il comportamento corrente.

- [x] **Step 4: Run GREEN and mutation check**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_runner.py tests/recon/test_rate_limit_types.py -q`

Expected: PASS. Mutare localmente il baseline per usare `self._findings`: il nuovo test deve fallire.

- [x] **Step 5: Commit**

Commit: `refactor(recon): build baseline rate profile without llm verdict`

**Acceptance:** un mapping completato puo produrre il profilo persistibile senza `RateLoopVerdict` e senza bypass LLM.

### Task 2: Mapping Vegeta diretto nella pipeline

**Files:**
- Modify: `src/polymerhus/recon/control/pipeline.py`
- Modify: `tests/recon/test_rate_limit_pipeline.py`
- Modify: `tests/recon/test_rate_limit_posture_write.py`

**Interfaces:**
- Produces: `_default_map_rate_profile(project_id, run_id, target_key, url, headers, host_patterns) -> Awaitable[RateProfile]`.
- Produces: injectable `map_rate_profile` keyword on `run_pipeline` with la stessa firma.
- Changes: `_rate_profile_for_run` consumes `GatewayVerdict` context and mapper seam, never an orchestrator rate method.

- [x] **Step 1: Write the failing pipeline tests**

Pin: auth precede mapper; mapper riceve host e header dell'account risolto; stats precedono YAML; `browser_only` restituisce conservative/inconclusive senza chiamare il mapper; mapper raising restituisce conservative/failed. La mutazione da uccidere e richiamare `orchestrator.run_rate_limit` quando il mapper e disponibile.

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py tests/recon/test_rate_limit_posture_write.py -q`

Expected: FAIL per keyword/sequenza `map_rate_profile` assente.

- [x] **Step 3: Implement direct mapping**

La default costruisce `RateLimitHarness` con `build_kali_execute`, esegue `map()`, poi `build_baseline_profile()`. `_rate_profile_for_run` risolve l'auth material, gestisce target assente/browser-only/failure e non dipende piu da `run_rate_limit`.

- [x] **Step 4: Run GREEN and mutation check**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py tests/recon/test_rate_limit_posture_write.py tests/recon/test_pipeline_gateway.py -q`

Expected: PASS. Reintrodurre temporaneamente la chiamata actor: il test di ownership deve fallire.

- [x] **Step 5: Commit**

Commit: `refactor(recon): map rate posture directly from pipeline`

**Acceptance:** il percorso produttivo e `GatewayVerdict -> pipeline -> Vegeta mapper -> stats -> YAML`; browser-only non misura.

### Task 3: Ridurre il ReconOrchestratorActor al solo Auth Gateway

**Files:**
- Modify: `src/polymerhus/recon/control/orchestrator_agent.py`
- Delete: `src/polymerhus/recon/control/prompts/rate-limit-gateway.md`
- Modify: `src/polymerhus/app/llm/skills.py`
- Modify: `tests/recon/test_orchestrator_actor.py`
- Modify: `tests/recon/test_skill_seam.py`
- Modify: `tests/app/test_auth_seams.py`

**Interfaces:**
- Preserves: `ReconOrchestratorActor.run_gateway(...) -> GatewayVerdict | None` and auth skill evolution.
- Removes dall'actor: `run_rate_limit`, `_RateHarnessSlot`, rate message/prompt/tools e actor union response schema.
- Preserves fuori dal percorso baseline: le primitive e i contratti di bypass, catalogati per eventuali workflow espliciti futuri; la pipeline usa soltanto `build_baseline_profile()`.
- Changes: `ROLE_SKILLS["job_orchestrator"] = ()`; `auth_capable_binding(..., with_write_skill=True)` continua a fornire la sola skill project `authn` e i tool auth/write.

- [x] **Step 1: Rewrite tests to the desired boundary and run RED**

Assert che l'actor abbia esattamente la superficie auth, che il response schema sia `GatewayVerdict`, che il system prompt sia il solo auth prompt e che `job_orchestrator` non carichi la skill bypass. La mutazione da uccidere e riaggiungere anche uno solo tra i due rate tool.

Run: `.venv/bin/python -m pytest tests/recon/test_orchestrator_actor.py tests/recon/test_skill_seam.py tests/app/test_auth_seams.py -q`

Expected: FAIL sulla superficie rate ancora presente.

- [x] **Step 2: Remove the second turn**

Eliminare il codice actor-specific del mapping. Conservare `build_baseline_profile()` come API usata dalla pipeline; `RateLoopVerdict`, le primitive pure di mutation/bypass e il loro tool builder restano dormienti e non legati a nessun ruolo, disponibili soltanto per un eventuale workflow esplicito futuro.

- [x] **Step 3: Run GREEN and mutation check**

Run: `.venv/bin/python -m pytest tests/recon/test_orchestrator_actor.py tests/recon/test_skill_seam.py tests/app/test_auth_seams.py tests/recon/test_rate_limit_runner.py -q`

Expected: PASS; una tool surface contenente `map_rate_limit` deve rompere il test.

- [x] **Step 4: Commit**

Commit: `refactor(recon): confine orchestrator to auth gateway`

**Acceptance:** l'actor espone un solo turno e un solo tipo di risposta; nessuna conoscenza o tool di rate mapping vive nell'Auth Gateway.

### Task 4: Configurator stateful, contratti, prompt e skill

**Files:**
- Create: `src/polymerhus/recon/control/configurator.py`
- Create: `src/polymerhus/recon/control/prompts/rate-aware-configurator.md`
- Modify: `src/polymerhus/app/llm/session_address.py`
- Modify: `src/polymerhus/app/llm/skills.py`
- Modify: `src/polymerhus/app/llm/providers.py` (solo commento/statefulness; nessun nuovo ruolo)
- Create: `skills/rate-aware-recon-configuration/SKILL.md`
- Modify: `skills/README.md`
- Create: `tests/recon/test_rate_aware_configurator.py`
- Modify: `tests/test_session_address.py`
- Modify: `tests/recon/test_skill_seam.py`
- Modify: `tests/recon/test_skill_data_section.py`

**Interfaces:**
- Produces: `ConfiguratorSession(run_id, role_id="configurator")`, thread `run:<run_id>:configurator`.
- Produces closed models: `ReconPodProposal`, `ConfiguratorDecision`, `ConfiguratorOffer`.
- Produces: `offer_phase_inputs(phase, target_key, prepared_by_job, jobs=JOBS) -> PhaseOffers` con `input_id="<job_name>:<zero-based-index>"`.
- Produces: `configure_phase(project_id, run_id, phase, target_key, offers, *, checkpointer=None, model_factory=None, posture_store=None) -> ConfiguratorDecision | None`.

- [x] **Step 1: Write contract/address tests and run RED**

Pin contratti chiusi, IDs stabili e univoci, `command=None` solo per offerte agentiche, due fasi sulla stessa sessione e isolamento tra run. Pin la tool surface esatta `load_skill + rate_limit_posture`, la middleware di skill/compaction e la skill roster `("rate-aware-recon-configuration",)`.

Run: `.venv/bin/python -m pytest tests/recon/test_rate_aware_configurator.py tests/test_session_address.py tests/recon/test_skill_seam.py tests/recon/test_skill_data_section.py -q`

Expected: FAIL per modulo/sessione/skill assenti.

- [x] **Step 2: Implement contracts and phase offers**

Le offerte includono job, tool, consumes/produces, cost class/estimate, configurator mode, template non autenticato e preview dell'input. Non includono `extra.auth_context`, cookie, token o header. Duplicati `(job_name, input_id)` sono impossibili per costruzione.

- [x] **Step 3: Author prompt and product skill**

Usare `superpowers:writing-skills`. La skill descrive soltanto la sintassi/capacita di Katana, Arjun, ffuf e httpx; il prompt possiede il workflow: resolve postura, valuta aggregato dei pod, prudenza su assente/scaduta, zero target traffic su unreadable, revisione e rationale. Nessun valore numerico hardcoded nel prompt.

- [x] **Step 4: Implement the stateful turn**

Chiamare `skill_agent_binding("configurator")`, aggiungere `build_rate_limit_posture_tool(project_id, store=posture_store)`, usare `stateful_turn` con `ConfiguratorSession`, schema `ConfiguratorDecision` e compaction cached del ruolo.

- [x] **Step 5: Run GREEN and mutation checks**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_aware_configurator.py tests/test_session_address.py tests/recon/test_skill_seam.py tests/recon/test_skill_data_section.py -q`

Expected: PASS. Mutazioni: aggiungere `phase` al thread id o rimuovere il posture tool; almeno un test deve fallire per ciascuna.

- [x] **Step 6: Commit**

Commit: `feat(recon): add stateful rate-aware configurator`

**Acceptance:** il Configurator esiste e ragiona statefully con skill e postura, ma non controlla ancora la pipeline.

### Task 5: Comando proposto come input del pod

**Files:**
- Modify: `src/polymerhus/recon/domain/pod.py`
- Modify: `src/polymerhus/recon/domain/types.py`
- Modify: `src/polymerhus/recon/control/job_agent.py`
- Modify: `tests/recon/test_pod.py`
- Modify: `tests/recon/test_job_agent.py`

**Interfaces:**
- Produces: `build_pod_command(job, input_asset, extra, session_id, command_template=None) -> str` estratto dal nodo configurator corrente.
- Consumes: optional `pod_input["configured_command"]`; se presente sostituisce `job.command_template` per i job shell.
- Preserves: espansione tardiva di `{target}`, `{domain}`, `{baseurl}`, `{endpoints}`, `{session}`, `{auth_flags}` e retry dello stesso comando.

- [x] **Step 1: Write failing tests and run RED**

Prove separate per job semplice, batch e one-pod reprofile: il comando proposto arriva all'exec; `{session}` e `{auth_flags}` sono espansi solo nel pod; il prompt-side command non contiene il valore segreto. Pin che `steel_crawl` continua sul proprio graph senza comando.

Run: `.venv/bin/python -m pytest tests/recon/test_pod.py tests/recon/test_job_agent.py -q`

Expected: FAIL perche il pod ignora `configured_command`.

- [x] **Step 2: Extract and wire the pure command builder**

Il nodo configurator del pod diventa un assembler tecnico. Nessuna chiamata LLM entra nel pod graph; il Configurator globale ha gia scelto il comando. Il fallback al template statico resta per chiamanti diretti/test legacy finche Task 6 non rende il piano obbligatorio nella pipeline.

- [x] **Step 3: Run GREEN and mutation check**

Run: `.venv/bin/python -m pytest tests/recon/test_pod.py tests/recon/test_job_agent.py tests/integration/test_httpx_reprofile_one_pod.py -q`

Expected: PASS. Ignorare l'override e usare il template statico deve far fallire i nuovi test.

- [x] **Step 4: Commit**

Commit: `feat(recon): execute configurator-proposed pod commands`

**Acceptance:** il pod puo eseguire un comando deciso a monte senza esporre segreti al modello.

### Task 6: Materializzazione LLM al confine di fase

**Files:**
- Modify: `src/polymerhus/recon/control/configurator.py`
- Modify: `src/polymerhus/recon/control/pipeline.py`
- Create: `tests/recon/test_configurator_materialization.py`
- Modify: `tests/recon/test_pipeline.py`
- Modify: `tests/recon/test_pipeline_e2e.py`
- Remove/replace active-path assertions in: `tests/recon/test_rate_limit_pipeline.py`

**Interfaces:**
- Produces: `materialize_configurator_decision(decision, offers) -> dict[str, list[dict]]`, grouping selected prepared inputs by canonical job and attaching `configured_command`.
- Changes: `run_pipeline(..., configure_phase=None)`; production calls the Task 4 seam once per phase through `asyncio.to_thread`.
- Removes from active path: `materialize_admitted_phase`, `TrafficAdmissionEnvelope`, thresholds, projected duration and `traffic_admission` persistence.

- [x] **Step 1: Write validation/materialization tests and run RED**

Cover: subset selection, `pods=[]`, duplicate ID, wrong job for ID, unknown ID/job, mismatched phase/target, empty command for shell job, command on agentic job, malformed/None response. Per spec, ogni errore rifiuta l'intera decisione e la pipeline segna `failed` prima di `run_job`. La mutazione principale e materializzare la proposta valida accanto a una invalida.

Run: `.venv/bin/python -m pytest tests/recon/test_configurator_materialization.py tests/recon/test_pipeline.py tests/recon/test_pipeline_e2e.py -q`

Expected: FAIL perche la pipeline usa ancora l'admission deterministica.

- [x] **Step 2: Implement pure atomic validation**

Validare contro la mappa delle offerte, senza leggere `RateProfile` e senza analizzare i flag del comando. Restituire nuove copie dei pod input; non mutare gli input preparati.

- [x] **Step 3: Replace the phase admission boundary**

Dopo la preparazione dei candidati, costruire le offerte, invocare il Configurator e materializzare soltanto le proposte. Raggruppare per job e conservare l'esecuzione sequenziale dei job e il fan-out `MAX_PODS` esistente. Nessun output del modello puo aggiungere un job fuori dalla fase.

- [x] **Step 4: Run GREEN and mutation checks**

Run: `.venv/bin/python -m pytest tests/recon/test_configurator_materialization.py tests/recon/test_pipeline.py tests/recon/test_pipeline_e2e.py tests/recon/test_rate_limit_pipeline.py -q`

Expected: PASS. Mutazioni: unione con tutti i candidati, accettazione parziale o salto del Configurator devono essere uccise.

- [x] **Step 5: Commit**

Commit: `feat(recon): let configurator materialize phase pods`

**Acceptance:** i pod realmente creati sono esattamente quelli del piano LLM tecnicamente valido; nessuna soglia controller decide la fase.

### Task 7: Ritirare TrafficPolicy dal percorso dei pod

**Files:**
- Modify: `src/polymerhus/recon/control/pipeline.py`
- Modify: `src/polymerhus/recon/domain/pod.py`
- Modify: `src/polymerhus/recon/domain/types.py`
- Modify: `src/polymerhus/recon/control/job_agent.py`
- Modify: `src/polymerhus/recon/crawl/crawl_pod.py`
- Modify: `src/polymerhus/recon/crawl/crawl_agent.py`
- Modify: `tests/recon/test_pod_capture_context.py`
- Modify: `tests/recon/test_rate_limit_pipeline.py`
- Modify: relevant `tests/recon/crawl/` pacing tests

**Interfaces:**
- Preserves: HTTP capture context, exec timeout, parser/triager/curator behavior, `RateProfile.traffic_policy` as measured/advisory posture data.
- Removes from recon execution: `extra["traffic_policy"]`, `exec_fn(..., traffic_policy=...)`, crawl pacing derived from policy, traffic refusal/admission accounting.
- Leaves out of scope: removing the generic Kali governor implementation, which may serve a future explicit workflow but is not armed by recon.

- [x] **Step 1: Write failing absence tests and run RED**

Assert that request jobs and Steel crawl receive no traffic policy while capture metadata still arrives, and that commands selected by the Configurator are not rewritten/refused after materialization.

Run: `.venv/bin/python -m pytest tests/recon/test_pod_capture_context.py tests/recon/test_rate_limit_pipeline.py tests/recon/crawl -q`

Expected: FAIL perche il percorso corrente inoltra la policy.

- [x] **Step 2: Remove only the active enforcement plumbing**

Eliminare forwarding, stats/refusal specifici e adapter di crawl. Non toccare il budget Vegeta, lo store YAML o i campi advisory del profilo/tool.

- [x] **Step 3: Run GREEN and mutation check**

Run: `.venv/bin/python -m pytest tests/recon/test_pod_capture_context.py tests/recon/test_rate_limit_pipeline.py tests/recon/crawl -q`

Expected: PASS. Riaggiungere `traffic_policy` a una chiamata exec/crawl deve fallire.

- [x] **Step 4: Commit**

Commit: `refactor(recon): retire deterministic traffic enforcement`

**Acceptance:** dopo il piano LLM non esiste checker numerico ne governor armato dalla recon.

### Task 8: Documentazione, provider deterministico ed E2E reale

**Files:**
- Modify: `docs/design/statefulness-pattern-matrix.md`
- Modify: `docs/design/rate-limit-job-admission-operations.md`
- Modify: `src/polymerhus/recon/CONTEXT.md`
- Modify: `src/polymerhus/app/CONTEXT.md`
- Modify: `tests/e2e/deterministic_llm_provider.py`
- Create: `tests/e2e/test_llm_rate_aware_recon_configurator_e2e.py`
- Modify: `tests/e2e/test_rate_limit_mapping_e2e.py`
- Retire/supersede deterministic-admission assertions in: `tests/e2e/test_rate_limit_admission_e2e.py`, `tests/e2e/test_rate_limit_enforcement_properties_e2e.py`
- Modify: `scripts/issue_238_e2e_stack.sh` only if a new explicit gate selector is required

**Interfaces:**
- Deterministic provider emits a real `ConfiguratorDecision` after calling `rate_limit_posture`; it is a controlled LLM fixture, non production logic.
- E2E proves: auth -> Vegeta -> stats/YAML -> Configurator -> selected command -> pod -> Triager.

- [x] **Step 1: Update docs as executable truth**

Statefulness matrix: Configurator e `sync leaf + stateful_turn`, thread run-scoped e chiamato al phase boundary; ReconOrchestratorActor ha un solo turno. Operations: rimuovere soglie/admission/governor dalla traiettoria, dichiarare trust-based prompt guidance e mantenere writer/store failure semantics.

- [x] **Step 2: Add deterministic-provider behavior and E2E assertions**

Il provider controllato deve leggere davvero il tool postura e produrre flag differenti per postura alta/bassa; l'E2E verifica i comandi persistiti/eseguiti, l'omissione prudente su unreadable e l'identita della postura tra stats e YAML. Non implementare nel fixture un checker che la produzione non possiede.

- [x] **Step 3: Run focused functional tests**

Run: `.venv/bin/python -m pytest tests/app/test_rate_limit_posture_store.py tests/app/test_rate_limit_posture_tool.py tests/recon/test_rate_limit_runner.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_rate_aware_configurator.py tests/recon/test_configurator_materialization.py tests/attack/test_hunting_posture_tool_binding.py -q`

Expected: PASS.

- [x] **Step 4: Run repository tiers**

Run: `.venv/bin/python -m pytest tests/app tests/recon tests/attack -q`

Expected: PASS oppure soltanto failure pre-esistenti riprodotte sul base commit e nominate nel report; nessun nuovo failure.

- [x] **Step 5: Run isolated E2E stack**

Run in foreground, with polling:

```sh
sh scripts/issue_238_e2e_stack.sh config
sh scripts/issue_238_e2e_stack.sh build
sh scripts/issue_238_e2e_stack.sh up
sh scripts/issue_238_e2e_stack.sh health
sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-llm-configurator
sh scripts/issue_238_e2e_stack.sh down
```

Expected: entrambe le run provano il percorso completo e il secondo run non riusa accidentalmente sessione o output del primo.

- [x] **Step 6: Commit**

Commit: `test(e2e): certify llm rate-aware recon configuration`

**Acceptance:** documenti, unit/contract tier ed E2E descrivono e provano lo stesso percorso produttivo.

## Execution Checkpoints

L'esecuzione e inline nel worktree esistente. Per rispettare la richiesta dell'operatore di restare a capo della situazione, ogni Task e un checkpoint: mostrare RED, diff minimo, GREEN e mutazione uccisa; attendere conferma prima del commit e prima di iniziare il Task successivo. Push, merge e modifica di `origin/dev` richiedono una decisione separata.
