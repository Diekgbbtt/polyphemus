# LLM Rate-Aware Recon Configurator — Design

**Data:** 2026-09-28
**Stato:** implementato e verificato nel worktree `feat/rate-limit-job-admission-e2e`
**Ambito:** recon rate-limit posture e creazione dei pod

## 1. Obiettivo

Prima della recon, Polymerhus misura con Vegeta il comportamento di rate limit
del target e salva la postura corrente in un file YAML per target. Un unico
Configurator LLM usa quella postura per decidere quali pod di recon creare e
come configurare i tool che eseguiranno.

Non esistono Configurator diversi per fase. Lo stesso ruolo stateful segue
l'intera run ed è richiamato a ogni confine di fase.

## 2. Decisione di affidabilità

La scelta dei pod e dei parametri è affidata al modello. Il comportamento
prudente è una regola del system prompt, non un controllo semantico successivo.

In particolare, il runtime:

- non confronta i valori scelti dal modello con la postura;
- non applica soglie deterministiche di admission;
- non corregge rate, concorrenza, delay o durata;
- non usa il governor per correggere o rifiutare un piano valido a livello di
  schema.

Questa è una scelta trust-based. Il documento usa il termine
**prompt-guided safe default**, non "fail-closed garantito": se il modello non
rispetta il system prompt, il codice non garantisce che il traffico resti entro
la postura.

Restano meccanici soltanto i confini tecnici: schema dell'output, appartenenza
del job al catalogo canonico, riferimenti a input realmente offerti, timeout e
isolamento del processo. Questi controlli stabiliscono se un piano è
eseguibile; non decidono se sia sufficientemente prudente.

## 3. Flusso

```text
auth gateway
  -> GatewayVerdict + account identifier
  -> pipeline risolve il contesto HTTP autorizzato
  -> RateLimitMapper misura con Vegeta in Kali
  -> RateProfile
  -> recon_runs.stats["rate_limit"]
  -> data/<project_id>/rate-limit/<target_key>.yaml
  -> per ogni fase:
       catalogo JOBS + input disponibili + rate_limit_posture
       -> Configurator LLM
       -> ConfiguratorDecision
       -> materializzazione dei pod proposti
       -> esecuzione
       -> parsing, Triager e Curator
```

La misura avviene prima di qualsiasi pod target-facing. Il budget che limita
gli esperimenti Vegeta resta controller-owned: serve a rendere sicura la
misurazione e non prende decisioni sui successivi job di recon.

## 4. Postura persistente

La postura corrente rimane un file per target:

```text
data/<project_id>/rate-limit/<target_key>.yaml
```

Contratto:

```yaml
version: rate-limit-posture/v1
source_run_id: <run che ha prodotto la misura>
advisory: true
profile: <RateProfile validato>
```

Regole:

- il controller della pipeline è l'unico writer;
- `recon_runs.stats["rate_limit"]` resta il record immutabile per-run;
- la scrittura usa lo stesso `RateProfile` già persistito negli stats;
- una scrittura fallita interrompe la run prima delle fasi;
- una misura più vecchia non sovrascrive una più recente;
- un file corrotto è `unreadable`, mai equivalente a postura assente;
- gli agenti leggono soltanto tramite `rate_limit_posture`.

## 5. Confine dell'Auth Gateway

L'Auth Gateway possiede esclusivamente l'accesso iniziale alla superficie:

- stabilisce se la run è anonima o autenticata;
- seleziona l'identificatore dell'account;
- distingue replay HTTP e percorso browser-only;
- termina emettendo il `GatewayVerdict`.

Non misura il rate limit, non esegue Vegeta, non costruisce il `RateProfile` e
non configura i pod. Il rate mapping dipende dal risultato dell'Auth Gateway,
ma non gli appartiene.

Il `ReconOrchestratorActor` viene quindi riportato a un solo turno di auth. Dal
suo system prompt e dalla sua tool surface vengono rimossi il rate-limit
gateway, `map_rate_limit`, `test_rate_limit_variant` e l'unione
`GatewayVerdict | RateLoopVerdict`.

La pipeline consuma il `GatewayVerdict`, risolve lazily l'account selezionato e
passa al mapper soltanto il materiale HTTP necessario. Un risultato
`browser_only` produce direttamente una postura conservativa e inconcludente,
con zero esperimenti Vegeta.

## 6. Vegeta in Kali

Il mapping riusa il percorso già costruito:

1. la pipeline riceve il `GatewayVerdict`;
2. risolve il contesto HTTP dell'account selezionato;
3. costruisce il `RateLimitMapper` con target, contesto e budget operatore;
4. il mapper usa `RateLimitHarness.map()` per guidare direttamente gli
   esperimenti bounded;
5. Kali esegue Vegeta e conserva gli artifact grezzi;
6. il mapper deriva il `RateProfile` dalle evidenze;
7. il profilo validato viene scritto in Postgres e nello YAML.

`RateLimitMapper` è un servizio controller-owned, non un agente e non un ruolo
in `providers.py`. L'attuale costruzione del profilo viene separata dal
`RateLoopVerdict`: il profilo di base nasce direttamente dal `MappedControl`,
dal budget consumato e dalle evidenze. Il mapping di postura non esegue il
turno LLM di bypass; `bypass_outcome` resta `inconclusive` e
`bypass_findings` resta vuoto.

La separazione tra misura e configurazione è intenzionale: Vegeta produce il
fatto osservato; il Configurator decide come usare quel fatto nella recon.

## 7. Un solo Configurator

`providers.py` conserva un solo ruolo generico:

```python
Role("configurator", "LLM_CONFIGURATOR", "session", ...)
```

Il ruolo `job_orchestrator` resta l'Auth Gateway e non porta più responsabilità
o prompt di rate mapping.

Non vengono dichiarati ruoli come `phase_1_configurator`,
`crawl_configurator` o `ffuf_configurator`.

Il Configurator segue il pattern **sync leaf + stateful_turn** della
statefulness matrix. Ha una sessione per run, condivisa tra le fasi, e viene
invocato sequenzialmente dalla pipeline. Non è un actor con mailbox perché non
gestisce direttamente il ciclo di vita dei pod: restituisce un piano tipizzato
e la pipeline lo materializza.

La sessione è indirizzata come `ConfiguratorSession(run_id)`, con thread
`run:<run_id>:configurator`. La fase non entra nell'identità: una nuova fase è
un nuovo turno dello stesso agente, non un nuovo agente.

Il Configurator deve essere collocato prima della materializzazione. Il vecchio
nodo `configurator` interno al pod è troppo tardi per decidere se quel pod debba
esistere.

## 8. Ruolo di `skills.py`

`skills.py` non costruisce il Configurator e non registra fasi. Dichiara solo
il bounded skill set del ruolo e produce il binding comune tramite
`skill_agent_binding("configurator")`.

Il Configurator riceve la skill dedicata
`rate-aware-recon-configuration`, contenente conoscenza riusabile sui flag dei
tool:

- Katana: concorrenza e rate;
- Arjun: rate limit e worker;
- ffuf: thread e rate;
- httpx: thread e rate limit;
- tool che non espongono un flag equivalente: strategia di pacing supportata.

La skill descrive la sintassi e le capacità dei tool. Il workflow, l'ordine
delle decisioni e il comportamento prudente restano nel system prompt del
ruolo.

La skill `performing-api-rate-limiting-bypass` non è più legata al
`job_orchestrator` per la recon ordinaria: il mapper baseline non esegue un
turno di bypass. La skill resta nel catalogo per eventuali workflow espliciti
futuri, fuori da questo design.

## 9. Input e output del Configurator

Per ogni fase la pipeline presenta:

- `project_id`, `run_id`, fase e target;
- risultato di `rate_limit_posture.resolve(host)`;
- candidati della fase provenienti dal catalogo canonico `JOBS`;
- input già derivati e identificati dalla pipeline;
- template, parser, prodotti e capacità configurabili di ogni job;
- risultati sintetici delle fasi precedenti disponibili nella sessione.

Il modello restituisce un contratto chiuso:

```python
class ReconPodProposal(BaseModel):
    job_name: str
    input_id: str
    command: str | None
    rationale: str

class ConfiguratorDecision(BaseModel):
    phase: int
    target_key: str
    posture_status: Literal[
        "known_target",
        "no_posture_for_host",
        "no_postures",
        "unreadable",
        "store_unavailable",
    ]
    pods: list[ReconPodProposal]
    rationale: str
```

Ogni `input_id` identifica un singolo input già preparato dalla pipeline; un
bundle o batch conta come un singolo input. `pods=[]` è una decisione valida e
significa che il Configurator non ritiene sicuro o utile creare pod nella fase.

`command` è obbligatorio e non vuoto per i job che eseguono un comando shell.
Per un job agentico (`configurator_mode="agent"`, oggi `steel_crawl`) deve invece
essere `None`: quel pod viene materializzato dalla pipeline, ma il suo loop usa
i propri tool e non possiede un comando shell da configurare.

Il codice rifiuta soltanto forme ineseguibili: job estranei a `JOBS`, input non
offerti, comando mancante/vuoto per un job shell, comando presente per un job
agentico, fase o target discordanti, oppure output non validabile. Il rifiuto è
atomico per la decisione e ferma la run prima di creare i pod della fase; non
viene eseguito un sottoinsieme ambiguo del piano. Il codice non ricalcola né
confronta i parametri rate-aware.

## 10. Workflow del system prompt

Il system prompt del Configurator impone questa sequenza:

1. risolvere la postura del target prima di proporre traffico;
2. distinguere postura nota, assente, scaduta e illeggibile;
3. leggere soltanto i job e gli input offerti per la fase corrente;
4. scegliere i pod utili, senza obbligo di materializzare ogni candidato;
5. configurare rate, concorrenza, thread e delay entro la postura letta;
6. considerare l'aggregato dei pod concorrenti, non ogni comando isolatamente;
7. usare il fallback conservativo dichiarato dal tool quando la postura è
   assente;
8. omettere tutti i pod target-facing quando la postura è illeggibile,
   contraddittoria o non consente una configurazione ritenuta sicura; i job
   non-target possono restare nel piano;
9. riesaminare il piano e spiegare nella `rationale` come rispetta la postura;
10. emettere esclusivamente il contratto `ConfiguratorDecision`.

Queste regole sono istruzioni al modello. Non esiste un checker numerico dopo
la decisione.

## 11. Runner e Triager

Il tool read-only `rate_limit_posture` resta disponibile anche al Runner e al
Triager del test-executor pod:

- il Runner può consultare la postura prima di eseguire traffico;
- il Triager può confrontare l'esecuzione descritta con la postura e segnalarne
  eventuali incoerenze;
- nessuno dei due può scrivere o modificare la postura;
- la loro lettura è informativa e non blocca tecnicamente l'esecuzione.

## 12. Modifiche architetturali previste

- conservare Vegeta, `RateProfile`, posture store e tool read-only;
- conservare il writer nel controller della pipeline;
- terminare l'Auth Gateway al `GatewayVerdict`;
- rimuovere il turno rate-limit, i relativi tool e il relativo prompt dal
  `ReconOrchestratorActor`;
- invocare direttamente il `RateLimitMapper` dalla pipeline dopo l'auth;
- costruire il profilo baseline senza `RateLoopVerdict`;
- trasformare il Configurator da riempimento deterministico interno al pod a
  decisione stateful al confine della fase;
- aggiungere il system prompt del Configurator;
- aggiungere il suo bounded skill set in `ROLE_SKILLS`;
- legare `rate_limit_posture` al Configurator, Runner e Triager;
- introdurre `ConfiguratorDecision` e `ReconPodProposal`;
- materializzare soltanto i pod proposti dal Configurator;
- rimuovere dal percorso attivo l'admission deterministica basata su
  `JobTrafficCost`, soglie e durata proiettata;
- non passare una `TrafficPolicy` come enforcement semantico dei pod configurati;
- aggiornare la statefulness matrix e il glossario Recon.

Quando implementato, questo design supera le parti della precedente #238 che
assegnano l'admission dei job e l'enforcement della `TrafficPolicy` al
controller deterministico, oltre alla parte che assegna il rate mapping al
secondo turno del recon orchestrator. Restano validi il mapping Vegeta bounded,
il `RateProfile`, la persistenza per-run, il posture store e il tool read-only.

## 13. Failure semantics

| Evento | Comportamento |
|---|---|
| Auth Gateway degradato | Pipeline anonima secondo la semantica auth corrente; il mapper riceve il contesto effettivamente disponibile |
| Target browser-only | Profilo conservativo e inconcludente; zero esperimenti Vegeta |
| Misura Vegeta fallita | Profilo conservativo, reso visibile al Configurator |
| Scrittura YAML fallita | Run `failed` prima delle fasi |
| YAML assente | Il prompt impone il fallback conservativo |
| YAML illeggibile | Il prompt impone `pods=[]` per il traffico target-facing |
| Risposta LLM non validabile | Run `failed` prima dei pod della fase |
| Job o input sconosciuto | Intera decisione rifiutata; run `failed` prima dei pod della fase |
| Parametri superiori alla postura | Nessun rifiuto automatico; violazione del contratto del modello |
| Tool fallito | Semantica corrente di retry/degrado del pod |

## 14. Verifica prevista

La futura implementazione deve dimostrare almeno:

- Vegeta produce e persiste una postura per target;
- l'Auth Gateway emette soltanto `GatewayVerdict` e non possiede tool o prompt
  di rate mapping;
- la pipeline invoca il mapper dopo l'auth usando il contesto selezionato;
- il mapper costruisce il profilo senza un turno LLM o un `RateLoopVerdict`;
- un target browser-only produce zero chiamate Vegeta;
- la stessa run scrive stats e YAML dallo stesso `RateProfile`;
- un solo Configurator mantiene la sessione attraverso più fasi;
- nessun ruolo Configurator per-fase compare in `providers.py` o `skills.py`;
- il Configurator vede postura, catalogo e input prima della materializzazione;
- l'output del Configurator determina realmente quali pod esistono;
- Katana, Arjun, ffuf e httpx possono ricevere parametri scelti dal modello;
- Runner e Triager leggono lo stesso YAML in sola lettura;
- una postura illeggibile è presentata come errore, non come assenza;
- non esiste un confronto deterministico tra i parametri proposti e la postura;
- un E2E con modello controllato prova l'intero percorso Vegeta -> YAML ->
  Configurator -> pod -> Triager.

## 15. Fuori scope

- agenti specializzati per fase o per tool;
- bypass probing durante il mapping baseline;
- modifica della postura da parte di un agente;
- storico delle posture nello YAML;
- admission basata su soglie controller-owned;
- correzione automatica dei parametri scelti dal modello;
- garanzia tecnica che un modello non conforme rispetti il limite.
