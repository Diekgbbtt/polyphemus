# LightRAG Methodology Ontology

Status: current implementation note.

Purpose: define the reusable methodology entity types used by LightRAG ingestion
for WSTG and writeup-derived documents. This ontology describes methodology,
not the current target model.

## Entity Types

The ontology contains exactly these ten entity types:

| Type | Definition |
|---|---|
| `PreconditionEnvironment` | Target or environment condition that must be true for a technique to apply. |
| `TechnologyStack` | Technology, product, framework, protocol, or component present in the target and relevant to the attack. |
| `DefensiveControl` | Target mechanism intended to prevent, limit, or detect an attack. |
| `VulnerabilityClass` | Technical, logic, or configuration weakness class in the target. |
| `AttackGoal` | Strategic result the attacker wants to achieve through one or more techniques. |
| `AttackerCapability` | Access, control, or operational ability the attacker already has and can use in later steps. |
| `AttackTechnique` | Concrete action performed by the attacker to obtain a result. |
| `PayloadPattern` | Reusable, parameterized structure of malicious input used to perform a technique. |
| `Artifact` | Concrete object obtained or produced during an attack and reusable in later steps. |
| `ObservableSignal` | Observable evidence indicating relevant behavior or possible technique success. |

## Boundary Rules

- Do not add hierarchy, subtypes, aliases, or compatibility mappings.
- Do not model concrete target endpoints, hosts, service IDs, or run-specific
  observations as methodology entities.
- Do not define relation types in this ontology. LightRAG extracts
  source-grounded relationships during indexing.
- If a source phrase combines multiple concepts, split it only when each concept
  has an independent meaning and maps clearly to one of the ten types.
- If a concept cannot be classified without introducing another category, omit
  it from typed extraction and keep it only as source context.

## Writeup Overlay Notes

Writeup-derived documents are review overlays. They can mention concrete source
episodes, but generated LightRAG inputs should normalize those episodes into
reusable methodology claims using only the ten entity types above. Tools used by
an author are kept as source context unless the text also describes a reusable
technique, payload pattern, artifact, observable signal, or attacker-held
ability.

After changing this ontology, clear or replace the local LightRAG storage before
indexing again because existing graph data was extracted with an older prompt.
