---
name: lightrag-query
description: Guida operativa compatta al tool `query_lightrag` dell'hunting agent: quando usarlo, come costruire uno `QuerySpecV1` derivando i campi dall'HuntConfig, e come trattare l'`AnswerBundle` validato (metodologia e provenance, mai conferma di vulnerabilità). Caricata lazy da src/polymerhus/attack/hunting/hunting_agent.py::_load_lightrag_query_skill.
---

# query_lightrag

## Quando usarlo

Usa `query_lightrag` solo quando il grounding della KB non basta a formulare una metodologia riutilizzabile. Se la KB copre il caso, non chiamare il tool.

## Come costruire `QuerySpecV1`

Deriva i campi dall'HuntConfig. Non introdurre testo recuperato né campi inventati.

- `scenario_id`: identifica la caccia o l'ipotesi corrente.
- `attack_goal`: obiettivo dell'attacco dichiarato dall'HuntConfig.
- `concern`: la preoccupazione di sicurezza da indagare.
- `technology_stack`: lo stack tecnologico dell'unità testabile.
- `target_refs`: riferimenti al target (componenti/superfici).
- `input_vectors`: vettori di input presunti, da `supposed_payload_vectors`.
- `known_facts`: fatti noti e verificati (es. L0).
- `acceptable_technique_families`: famiglie di tecniche accettabili per la metodologia.
- `unsupported_claims`: affermazioni che il tool non deve dare per confermate.
- `evidence`: riferimenti L0/L1 con sintesi, vincolo di provenance.
- `expected_no_hypothesis`: true quando è attesa l'assenza di ipotesi.

## Risposta

Il tool restituisce un `AnswerBundle` validato. Usalo come metodologia e come vincolo di provenance, mai come conferma di vulnerabilità.

## Fallimento

Se il tool fallisce, prosegui con il grounding disponibile e segnala il gap nel feedback.

