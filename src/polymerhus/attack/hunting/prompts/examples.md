# Hunting-agent worked examples: the off-path shapes

Read this section when the run leaves the straight path - a well-formedness
re-entry, a falsifying probe, or a degraded run. Example 1 (the straight path)
is above in the main body; these three cover the branches. Imitate the
REASONING SHAPE, never the domain.

### Example 2 - well-formedness re-entry, then a merge

```
GROUNDING: the same report loop; the target surfaces now show a second route,
GET /reports/{id}/export, that also carries the report id. Class skill idor
loaded; the methodology KB answers the object-store configuration only.
Failure modes: the download ownership check, the export ownership check, the
signed-URL tenant scope. phase:grounding.
SLICE: report-id authorisation across the download and export routes; boundary
on the effective request item (the report id) and the delivery behaviour
(direct file versus signed-URL redirect). phase:slice.
COLLECT: direct download, signed-URL redirect, and a share-route mint as an
advanced technique. phase:collect.
DISCRIMINATE: authorisation source x delivery route; narrow on the report id,
broad on the routes. phase:discriminate.
GENERATE: three specs - direct download, signed-URL redirect, share-route
mint. One hunts_store write per spec, all hypothesised.
WELL-FORMEDNESS: the export route is a new instance the collection missed;
[D2] re-enters the reasoning at COLLECT.
Update phase:collect with action=update (the export route and its own
authorisation branch). Re-generate: one hunts_store write per spec, all
hypothesised; the three identities upsert in place and the export spec is
added. The tracked state stays WELL-FORMEDNESS throughout.
Then merge: the direct-download spec and the export spec differ only by route
while the authorisation variable is the same, so the direct-download identity
widens to name both routes and the export identity is absorbed. Record the
merge and its reason in phase:well_formedness; the VERIFY-CLAIMS status
write carries the absorbed identity as dropped.
Coverage basis: both routes are named in the merged spec, the signed-URL
region keeps its own spec, and the share-route mint keeps its own spec. No
proof of exhaustiveness is claimed. Exit note.
VERIFY-CLAIMS: probe the assumption "a viewer can mint a signed URL from the
share route" - exec the share route; 403. The share-route spec is unfeasible.
Probe the object-store configuration evidence: an unsigned request for the
prefix returns 403, so the download route's signed URL is the only delivery.
The widened direct-route and signed-URL specs survive.
Terminal statuses: one hunts_store write per spec; the widened direct-route
and signed-URL specs ratified, the share-route spec and the absorbed export
identity dropped. Then finalize.
COMPLETE.
```

### Example 3 - a falsifying probe that runs out of insight

```
GROUNDING/SLICE/COLLECT/DISCRIMINATE/GENERATE: the four specs stand
hypothesised after one write per spec; the advanced technique depends on an
administrative overlay route that the target surfaces do not list.
WELL-FORMEDNESS: the four sub-slices are disjoint and the slice's regions are
each owned; the overlay spec is flagged as conditional on the probe. Exit note.
VERIFY-CLAIMS: the assumption is "the overlay route exists and accepts an
authenticated request". Probe it with exec - the response is a generic error
page carrying neither the route nor a default-route absence marker.
No meaningful insight: the probe cannot contradict the requirement, and the
meaningful-insight guard ends the evaluation. Do not retry with a different
path. The probe iterations move no tracked state.
This was an assumption probe, not a payload probe: it tested the feasibility
of the technique, never whether a payload fires.
Terminal statuses: one hunts_store write per spec; all four specs ratified,
with the unresolved overlay assumption recorded as visible uncertainty in
phase:well_formedness. Nothing is dropped, because no technical infeasibility
was shown. Then finalize.
COMPLETE.
```

### Example 4 - worst case, graceful degradation

```
GROUNDING: loop-2 names a class whose skill is absent from the suite; the
methodology KB returns empty and the target front answers 504 for every probe.
The 504 family means the target's upstream is down or restarting, not that the
routes are absent: stop probing, record the unavailability, and do not loop.
Gaps recorded in phase:grounding: class skill absent, KB empty, target
temporarily unavailable. Grounding is weaker; it still proceeds. phase:grounding.
SLICE: the region the trust agreement opens on the item lookup, bounded by the
two routes the target surfaces already show. phase:slice.
COLLECT: instances from the target surfaces and the notes only - the KB
contributes none. phase:collect.
DISCRIMINATE: the collected routes separate the specs; the narrow/broad
trade-off is stated. phase:discriminate.
GENERATE: two specs, all hypothesised, each rationale stays vulnerability-level;
the absent class skill was recorded as a gap in phase:grounding, and the
skill_procedure excerpt is empty per field - also a recorded gap, not a
failure.
WELL-FORMEDNESS: coverage is partial over the technology-specific region the
KB would have named. Record the residual gap and the coverage basis; the set
stays hypothesised. phase:well_formedness.
VERIFY-CLAIMS: the probes cannot run while the target is unavailable, so the
assumptions stay visibly unchecked. Fail-open and loose: no falsification is
invented, and no retry is made against a 5xx.
Terminal statuses: one hunts_store write per spec; both specs ratified with
their uncertainty, none dropped - no technical infeasibility was proved. Then
finalize.
COMPLETE: the hunt lands with a usable, honestly degraded set.
```
