# Arm A baseline recomputed for iteration B

*Source: project `0c8cb6e6-7e91-4a01-880e-408896c0ce4a`, run `a5f487fb-8329-431c-b95d-207799a038f9`, target white-jotter, 2026-10-24.*
*The recomputation reads the stored `loop-*.yaml` files, the schema-1 vocabulary the arm used.*
*A historical loop is the artifact now called a threat.*

## Threat and class counts

| Metric | Value |
|---|---:|
| Stored threat files | 111 |
| Class-bound to a suite class | 68 (61.3%) |
| Bound class is a suite parent (broad) | 55 |
| Bound class is a suite leaf (narrow) | 11 |
| Breadth unknown (empty or non-suite name) | 45 |

The class-bound rate is the clearest "concern the hunt" measure.
It is 61.3%, not 39.8%.

## Downstream discrimination

| Metric | Value |
|---|---:|
| Spec files | 45 |
| Threats with at least 3 linked specs | 5 |
| Threats with a well-formed linked set | 0 |

Every linked set either had fewer than three specs or shared a primary discrimination axis.
The arm A hunter did not produce a substantial, well-formed set per threat.

## Token tax

| Agent | Capped tokens | Share |
|---|---:|---:|
| Pod runner | 2,302,408 | 32.9% |
| Threat modeller | 2,179,055 | 31.1% |
| Hunter | 1,254,212 | 17.9% |
| Pod triager | 806,339 | 11.5% |
| Analysis agents | 458,918 | 6.6% |
| **Total** | **7,000,932** | 100% |

The run stopped at the 7M cap.
Raw spend was 146,497,124 tokens; 95.2% was cache reads.

## The green-share definition gap

The ADR says the baseline green share was 45 of 113 (39.8%).
The baseline table reports 45 of 113 (39.8%) as the empty-and-suite-gap count.
Those two numbers are identical, and the stored loop files have 43 empty classes plus 2 non-suite names.
The historical green figure is therefore not reproducible from the artifacts.

The iteration B results will report two separate numbers:

- the **class-binding rate**, which is unambiguous and reproducible;
- the **green-threat share**, with the high-yield class set named in the report and applied to both arms.

Do not carry the 45/113 figure forward as a green share without that recomputation.

## Provenance

- Threat files: `<project>/hunting/threat_modeller/{produced,consumed}/<unit>/loop-*.yaml`
- Specs: `<project>/hunting/hunter/test-specs/**/*.yaml`
- Usage: the project `UsageStore` ledger, 1,532 calls, 7,000,932 capped tokens.
- The arm A report: `docs/experiments/white-jotter-batched-2026-10-24/TOKEN-USAGE-AND-CONTEXT-OCCUPANCY.md`
