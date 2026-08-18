# Hunting #66 - the fold seams the hunt-orchestrator graph logic consumes

The folded recipes in the fault-KB are latent in the matching facet: `load_fault_entries` filters them out ("fold at curation, filter at read"), so a folded recipe only surfaces if the orchestration explicitly attaches it to its selection-tier parent.
That is a materialisation failure: without the seams below, a folded recipe is never materialised into a hunting-agent prompt and the taxonomy corrections are invisible to the hunt.

The graph logic consumes three seams from `polymerhus.attack.hunting.fault_kb` (no graph logic is implemented here - this illustration is the contract).

## Seam 1 - the fold-family map: `load_fold_families()`

- Returns `Mapping[selection_fault_id, tuple[folded_fault_id, ...]]` for every selection-tier fault (an empty tuple for a leaf parent).
- The graph logic builds **one node per selection-tier fault** (the parent / capture) and attaches each folded id listed under it as that unit's **reflection material**.
- An empty tuple is still a huntable unit: the parent is bound, there is just no folded corpus.

## Seam 2 - the reflection corpus: `load_materialisation()`

- Serves the rich NL of ANY entry by own id - including every folded recipe.
- The graph logic reads the folded ids of a parent (seam 1) and resolves their content here, attaching the corpus to the parent node for the prompt-builder.

## Seam 3 - the carried sub-faults: `HuntConfig.sub_fault_ids`

- `fault_class` names the **parent** fault (the one to bound).
- `sub_fault_ids` carries the **folded fault ids** captured under it (the sub-faults / reflection material to consider).
- The orchestrator may produce **up to one hunt config per parent-fault-unit pair**.

## The verbatim bound

The hunting-agent prompt grounds on the parent fault and treats the folded recipes as reflection material:
the **fault to bound is the parent one** (`fault_class`); the **child variants/bases are reflection material** (`sub_fault_ids`) - never separate bound faults.
