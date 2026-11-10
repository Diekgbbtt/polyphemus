# Freeze JS analysis — non pronto per l’integrazione

Il codice è proposto come **Draft PR verso `dev`** per rendere revisionabile
lo stato raggiunto, non come feature pronta al merge. Il
[design corrente](../../../client-side-js-analysis.md) descrive architettura,
responsabilità, limiti e capacità osservate. Non sono state eseguite nuove eval
LLM, crawl, accessi ai target o modifiche funzionali durante questo freeze.

## Cosa abbiamo in mano

- Uno specialista nativo Exec-only che ha prodotto due comportamenti JS
  source-backed su ComfyUI. La revisione manuale mantiene anche un esempio
  insufficient_evidence e la precisazione sul default cache sovrascrivibile.
- Un writer/store che, dopo il fix dell’origine, pubblica gli stessi record
  attraverso il job senza reinvocare specialista o curator.
- Uno YAML reale con due comportamenti e tre evidenze receipt_only. Rimane
  partial: nessun blob storico viene dichiarato retained.
- Un consumo reale da mechanism typist: due behaviors e tre evidence letti,
  tre Systems e sei enrichment emessi. Qualità campionata: 7 claim supported,
  4 ambiguous e 1 incorrect. Il controllo HTTP 200-only dell’upload è stato
  esteso erroneamente al wrapper generico.
- Assigner ha letto solo metadata; hunting ha superato l’admission ma si è
  fermato prima di intake e turni modello. Nessun aumento di vulnerabilità
  trovate o consumo hunting utile è dimostrato.

## Artefatti selezionati

| File | Provenienza e significato |
| --- | --- |
| [published.yml](published.yml) | Output deterministico del replay, non YAML prodotto nella run live originaria fallita in pubblicazione. |
| [producer-result.json](producer-result.json) | Run nativa ComfyUI: 480 lead, due behaviors, pubblicazione allora pending; la storia non viene riscritta. |
| [producer-semantic-review.json](producer-semantic-review.json) | Confronto manuale dei record con i range letti; non ground truth esaustivo. |
| [publication-replay.json](publication-replay.json) | Due record e tre ricevute preservati, zero nuove chiamate LLM/curator/specialista/target. |
| [retention-probe.json](retention-probe.json) | Probe PostgreSQL isolato riuscito; non spiega l’errore retention storico. |
| [consumer-result.json](consumer-result.json) | Consumer con input preparato e L0 minimale: esiti per ruolo, tempi, costo e scope. |
| [consumer-semantic-review.json](consumer-semantic-review.json) | Revisione dei claim downstream, incluso l’errore e le ambiguità. |
| [consumer-transcript.json](consumer-transcript.json) | Transcript sanificato della prova consumer; non una nuova evaluation. |
| [provenance.json](provenance.json) | Percorsi di origine, dimensione e hash delle copie esatte. |
| [source-manifest.json](source-manifest.json) | Allowlist/hash del codice e dei test esportati sulla base dev. |

Le tre fasi sono separate: **producer live → fix/replay deterministico → consumer
con input preparato**. Non si sommano in una E2E completa verde. I consumi
misurati sono quelli dei candidati e delle immagini originali riportate nei JSON;
non vanno attribuiti automaticamente al branch della PR.

## Versione e perimetro Git

Base della PR: `origin/dev` a `a1cac1d96d734167e22f830139a497b6fd82af96`.
Branch di revisione: `feat/js-analysis-review`, worktree separato. Il branch
sperimentale `feat/js-analysis-mvp-eval` e il suo staging rimangono preservati.

Sei file hanno soltanto le righe vuote finali in eccesso rimosse per il diff
check; gli hash precedenti sono nel manifest. Nessuna modifica funzionale.

L’esportazione usa un elenco esplicito di file: sorgenti e seam JS, sei skill,
parser/lockfile, test e dodici piccole fixture controllate. La helper cortex
conserva l’idempotenza già presente nel codice della feature; i test cortex di
dev rimangono presenti. Non vengono copiati i cambiamenti estranei a identità
Neo4j, riconciliazione vincoli, compose o dipendenze che non aggiungevano package.

Sono esclusi dotenv, chiavi, node_modules, archivi dei candidati, log privati,
runtime dei progetti e centinaia di documenti di riallineamento. Le fixture
controllate sotto data/ sono elencate singolarmente; non viene importata quella
directory ricorsivamente. Non si ricostruisce la cronologia sperimentale come
centinaia di modifiche al dev corrente.

## Verifiche locali fresche sul branch di revisione

I gruppi seguenti sono comandi distinti; non sono una suite completa e i
conteggi non vanno sommati come garanzia globale.

| Verifica | Risultato |
| --- | --- |
| Baseline dev: tests/test_data_root.py + tests/recon/test_jobs.py prima dell’overlay | 66 passed. |
| Records/store/tool/writer/native publication/pipeline feed/Analysis integration/hunting admission | 131 passed. |
| Scaffold e registrazione job dopo l’overlay | 65 passed, 4 failed. |
| Parser struttura e sourcemap, redazione e retention blob/service | 52 passed, 1 failed. |
| Runner, binding, gate, entrypoint e test cortex upstream preservati | 89 passed, 6 failed. |
| Collection unit globale, senza integration/e2e | 8.171 test raccolti; interrotta da un import-file mismatch su test_service.py. Nessuna esecuzione globale dichiarata. |
| Controlli statici | Python AST, sintassi Node, integrità JSON/YAML/checksum, link locali del design e diff check. Dettaglio nel file validation.json. |

Un primo comando con --timeout non è partito perché pytest-timeout non è nella
venv effettiva. Le verifiche sopra usano timeout di processo, non quel plugin.
I test executor sono stati eseguiti fuori sandbox quando necessario; nessun
modello o servizio condiviso è stato chiamato. Restano warning di deprecazione
Neo4j/FastAPI. Non sono stati ricostruiti container o ritentate le eval.

## Blocchi di integrazione da mantenere visibili

1. Quattro test chiedono allo scaffold le directory js-intake, js_analysis,
   js-artifacts/blobs e js-client-side, ma il data_root attuale non le enumera.
   I servizi possono creare directory durante le operazioni: questo non rende
   verde il contratto scaffold. Nessun fix aggiunto durante il freeze.
2. `test_existing_corrupt_blob_is_not_replaced_silently` fallisce creando la
   fixture in una directory blob non predisposta: FileNotFoundError, non prova
   della gestione di un blob già corrotto.
3. `test_dispatch_uses_shared_session_exec_only_and_renews_finite_scope` fallisce
   sull’ordine del roster delle skill. Il roster è completo, ma l’assert storico
   usa un ordine diverso; non è stato rimosso per rendere verde il report.
4. Cinque test cortex upstream aspettano intestazioni/regole che il verbatim
   corrente di dev non contiene. Quel file e quei test rimangono quelli di dev;
   non sono stati riscritti. I cinque nomi sono nel riepilogo test-results.txt.
5. La collection globale collide fra tests/ingestion/test_service.py e
   tests/recon/js_retention/test_service.py. La suite completa non è verde.
6. `test_every_job_tool_has_a_parser` salta ora per qualunque job.executor,
   incluso il valore predefinito pod: copertura indebolita da revisionare.
7. Le criticità qualitative e operative restano quelle del design: errore
   semantico downstream, uptake assigner assente, hunting non esercitato,
   retention storica unknown e copertura multi-target non dimostrata.

Questi punti sono **blocchi per l’integrazione**, non una richiesta di considerarli
risolti perché la PR è aperta. La PR è intenzionalmente draft.

## Verificare le copie

Dalla directory di questo README:

```sh
sha256sum -c SHA256SUMS
```

Gli hash degli otto artefatti originali sono anche in provenance.json.
Il manifest sorgente copre i file runtime/test/fixture esportati, non i documenti
che lo descrivono. Le evidenze possono essere lette localmente senza accesso al
server, credenziali, target o provider.
