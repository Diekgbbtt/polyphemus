# Trial consultabili prima della materializzazione

## Obiettivo approvato

La SPA deve elencare i Trial autorevoli anche quando non sono stati materializzati.
Un timeout non deve nascondere grafi e artifact prodotti. I dati mancanti restano
esplicitamente non disponibili; non si inventano verdict, diagnosi o consumo.

## Situazione osservata sul server, 7 ottobre 2026

- Due record nella runs root primaria: ComfyUI e JetLinks, entrambi `terminal: timeout`.
- Ogni directory Trial contiene soltanto `trial.yaml`; nessun verdict o diagnosis.
- Il progetto JetLinks ha 51 artifact riconosciuti dal collector, inclusi sette
  ExperimentLog e sette PodExport; il progetto ComfyUI ha dodici HuntConfig.
- Grafi correnti disponibili attraverso l'agent; consumo registrato assente.
- Nessuno dei due Trial è nello store materializzato. Il catalogo attuale parte
  dallo store, quindi non li elenca e i resolved endpoint non ne risolvono l'identità.
- Due ulteriori HuntConfig annidati non sono raccolti: fix separato, fuori scope.

## Scelta architetturale

Estendere il catalogo read-only già esistente unendo store e runs root. Non creare
una materializzazione artificiale e non costruire un catalogo alternativo nel browser.
Lo stesso catalogo deve alimentare `/snapshot` e la risoluzione dei Trial negli
endpoint `resolved-graph`, inventory, detail e content.

### Sorgenti e identità

- Store materializzato configurato tramite `EVAL_ARTIFACT_STORE`.
- Record autorevoli nelle root `EVAL_RUNS_ROOT` e, se configurata,
  `EVAL_RUNS_LEGACY_ROOT`. Conservare dedup fisica dei bind tramite device/inode.
- Identità del catalogo: `(target_id, target_run_id, trial_id)`; non il solo project_id.
- Per usare raw e grafo corrente servono anche project_id e instance_id validi;
  mantenere il gate dell'istanza già implementato.
- Un record viene riconosciuto dal contenuto validato, non dal nome del file:
  conservare il supporto a nomi YAML arbitrari del resolver esistente.
- Non associare directory raw orfane a Trial per somiglianza di nomi o date.

### Dedup e precedenza

- Un Trial presente nello store e nelle runs root compare una sola volta.
- La voce materializzata mantiene precedenza, inclusi risultati e catture storiche.
  Non sovrascriverla con file correnti e non mescolare verdict di due sorgenti.
- Il consumo registrato conserva il resolver attuale e le sue regole di ambiguità.
- Due record in root fisicamente distinte con la stessa identità non vengono
  arbitrati: per il Trial non materializzato non scegliere un project_id o risultati
  a caso. Escludere l'associazione ambigua e segnalare un codice path-free
  `run_record_ambiguous`, senza bloccare i Trial validi.
- Se l'identità materializzata esiste già, mantenerla anche davanti a record ambigui:
  nessuna ambiguità delle runs root può cancellare la cattura storica.

## Contratto di lettura

Preservare le route canoniche e la struttura di EvalTrial. Aggiungere metadati
espliciti per distinguere disponibilità e origine; adattare i client con compatibilità
per payload e fixture precedenti che non li contengono.

- `storage_source`: `materialized` oppure `run_record`.
- `results_availability.verdicts` e `.diagnoses`: ciascuno con `status` (`available`
  oppure `unavailable`) e `reason` nullo se disponibile, altrimenti codice stabile
  di file mancante, invalido o non leggibile. Riutilizzare codici esistenti quando possibile.
- Questi stati vanno calcolati anche per i Trial materializzati: disponibilità delle
  diagnoses non si deduce dalla presenza di verdict o dall'array vuoto.
- Un array valido ma vuoto indica file disponibile senza righe; un file assente
  non è un risultato con zero vulnerabilità.
- Riutilizzare le regole di proiezione esistenti: conservare righe valide quando
  altre sono invalide e mantenere le segnalazioni di degrado.
- Gli issue di catalogo, come `run_record_ambiguous`, sono restituiti separatamente
  dai Trial validi in una lista additiva di codici path-free, mai come percorsi host.

Per `run_record`, leggere verdicts e diagnoses soltanto dalla directory del record
autorevole selezionato, con controlli di contenimento e senza symlink. L'assenza
di un file non impedisce l'accesso alle altre sezioni. Non usare un timeout come
prova che verdict o diagnoses non esistano: verificarli ogni volta.

L'identità, terminal e fasi provengono dal record; il record originale non cambia.
`copied_at` resta null se non c'è stata una copia: non usare mtime o una data
inventata. Non esporre link ai quattro artifact materializzati se quei file o i
relativi endpoint non sono disponibili per il Trial.

## Grafi e artifact

Per un Trial non materializzato, riutilizzare i resolver del progetto associato:
inventory raw allowlisted, digest, detail e download con `expected_sha256`;
grafo corrente tramite l'agent con il gate dell'istanza.

Non rendere una cattura assente un errore fatale che interrompe il fallback.
Mantenere per le catture presenti la precedenza storica e le attuali verifiche.
Etichette esplicite: artifact correnti del progetto e grafo corrente, non catturati
con il Trial. Un progetto riutilizzato non diventa una cattura per più Trial.

## Presentazione SPA

- Target -> indice Trial -> workspace canonico: nessuna nuova navigazione parallela.
- Trial non materializzato indicato come tale; terminal `timeout` visibile.
- Con timeout e file mancanti: «Trial terminato per timeout», «Verdicts non
  disponibili», «Diagnoses non disponibili». Non scrivere «mancanti a causa del
  timeout»: la relazione causale non è provata.
- Se i file arrivano dopo, mostrare le righe prodotte al successivo refresh.
- Nell'indice, se verdicts non disponibili, mostrare «Risultati non disponibili»,
  non `0 identified / 0 partial / 0 missed` come se fosse un assessment completo.
- Summary e coverage si calcolano soltanto dai verdict effettivamente letti;
  nessuna vulnerabilità viene aggiunta ai missed perché manca un assessment.
- Spend mancante -> «Dato non disponibile»; zero registrato -> 0. Non ricostruire
  i token storici dal ledger corrente dell'agent.
- Conservare Results comprimibili, link Evidence, raggruppamenti Hunting/Skills,
  manual refresh, polling 15 secondi e isolamento fra identità.

## Sicurezza, compatibilità e limiti

Nessuna scrittura a record, store, raw, Neo4j o harness. Niente monitor, assessor,
materialize o nuovi Trial. Letture limitate alle root configurate, file regolari,
con limiti di scansione/dimensione e errori senza percorsi host. Una root mancante
o un record malformato non deve nascondere i Trial validi dell'altra sorgente.

La proiezione e i resolved endpoint devono funzionare anche con store vuoto:
la consultazione non dipende dalla presenza di un manifest. La salute distingue
Trial catalogati e materializzati: non rinominare il contatore materialized_trials
per farlo includere record non copiati.

Fuori scope: HuntConfig nelle sottocartelle, producer/storage durability,
nuove regole ground truth, live usage, deploy e recupero di dati eliminati.

## Accettazione e verifica richiesta al worker

1. Fixture non materializzata: record timeout, risultati assenti, raw e grafo presenti;
   catalogata e navigabile, inventory/detail/content funzionanti.
2. Verdict disponibile senza diagnoses e viceversa: stati indipendenti; file vuoto
   distinto da mancante; file invalido distinto da assente, righe valide conservate.
3. Arrivo successivo dei risultati e poi materializzazione: una sola identità,
   nessun restart e precedenza storica corretta.
4. Identità duplicate/conflicting project o instance, alias bind della stessa root,
   record ambigui in root distinte: niente associazioni arbitrarie.
5. Symlink, traversal, YAML invalido e root mancante: fail-closed locale, non globale;
   nessun percorso host nel payload o nell'errore.
6. Frontend: avvisi corretti, niente conteggi inventati, toggle preservati su refresh
   e reset su cambio Trial; catture storiche non sostituite da grafi correnti.
7. Demo isolata con un Trial realmente non materializzato: HTTP reale e browser,
   aggiornamenti progressivi e layout mobile. Nessun server reale necessario.

Prima dell'implementazione: approvazione umana di questa specifica, quindi piano
worker dettagliato. Pubblicazione e deploy richiedono un'ulteriore conferma.
