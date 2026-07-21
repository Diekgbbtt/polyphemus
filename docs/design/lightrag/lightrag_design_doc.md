LIGHT RAG - DESIGN IDEA

2 main artifacts:

2 - Knowledge query contract : formato strutturato con il quale il planner dovrà interrogare lightRAG.

1 Methodology Knowledge Ontology: typing system usato durante ingestion e retrieval del RAG.

- Lista siti ispezionabili a run time.
- Quali documenti introdurre nel database offline:
	- come formattarli nell'ontology?

---------------------------------------


PARTE 1

1- Cosa si chiede il planner?:
What can be attacked?
Under which conditions?
What may stop or detect the technique?
What can bypass the defense?
What can establish the prerequisite for another technique?

endpoint/parameters etc.. devono essere nel target model e passati a lightrag tramite query.

1.2 - Ontologia/tipi principali (estensibile,partiamo semplici)

+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+
| Entity type            | Definition                                                                                      | Key attributes                                                              |
+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+
| Vulnerability Class    | A reusable category of weakness or security failure that an attacker may exploit.              | canonical_name; taxonomy_refs (CWE, OWASP, CAPEC); security_impact          |
+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+
| Defensive Technology   | A control, mechanism, product family, or security capability that detects, blocks, or mitigates.| canonical_name; defense_family (WAF, MFA, CSP, EDR); coverage_scope         |
+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+
| Environmental Condition| A state of the target environment that dictates if a technique is possible, useful, or likely.  | canonical_name; condition_state; scope (application, service, identity, host|
+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+
| Attack Technique       | A reusable attacker method for testing, exploiting, bypassing, or building a new capability.    | canonical_name; attacker_objective; execution_context (auth, unauth, etc.)  |
+------------------------+-------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------+


Ogni entità deve poi prendere dei non-identity metadata ma che servono , del tipo:
aliases: []
description: "Short methodology-oriented summary"
source_refs: []
confidence: high | medium | low


1.3 RELAZIONI TRA I PRINCIPALI TIPI 

+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| Relation       | Direction                                                   | Meaning                                                                                 |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| exploits       | AttackTechnique -> VulnerabilityClass                       | The technique takes advantage of the weakness represented by the vulnerability class.   |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| detectedBy     | AttackTechnique -> DefensiveTechnology                      | The defense can observe, identify, or alert on the use of the technique.                |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| requires       | AttackTechnique -> EnvironmentalCondition                   | The technique is applicable only when the stated condition is present.                  |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| enables        | EnvCondition -> AttackTechnique / AttackTech -> AttackTech  | A condition makes a technique possible, or one technique establishes a new capability.   |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| mitigates      | DefensiveTech -> AttackTechnique / DefensiveTech -> VulnClass| The defense reduces the feasibility or impact of the technique or weakness.             |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+
| bypasses       | AttackTechnique -> DefensiveTechnology                      | The technique avoids, weakens, or routes around the defense under stated conditions.    |
+----------------+-------------------------------------------------------------+-----------------------------------------------------------------------------------------+

Core graph shape
flowchart LR
    C[Environmental Condition]
    T1[Attack Technique T1]
    T2[Attack Technique T2]
    V[Vulnerability Class]
    D[Defensive Technology]

    C -->|enables| T1
    T1 -->|requires| C
    T1 -->|exploits| V
    T1 -->|detectedBy| D
    D -->|mitigates| T1
    T2 -->|bypasses| D
    T1 -->|enables| T2



RELAZIONI DEVONO AVERE UN SMALL EVIDENCE ENVELOPE:
applicability:
  - "Conditions under which the relation is true"
limitations:
  - "Known cases where it does not apply"
evidence_refs:
  - "Source section or chunk"
confidence: high | medium | low

COME MODULARLO PER IL FUTURO: REGOLE
The MVP should follow four rules:

Do not introduce a new entity type unless the Planner needs to query it directly.
Use attributes for descriptive variation and nodes for independently retrievable concepts.
Use controlled relation names, but allow new entity aliases and taxonomy references.
Keep source hierarchy, document titles, authors, and URLs as provenance metadata rather than core offensive nodes.


PARTE 2

2,1DIVISONE RESPONSABILITA:

PLANNER: fornisce :
the current target state;
the active hypothesis or blocked action;
known defenses and conditions;
the decision it is trying to make.

LIGHTRAG DA:
relevant technique candidates;
graph paths explaining their relevance;
prerequisites and incompatibilities;
supporting source evidence.

LightRAG must not directly choose the final test or issue execution commands. The Planner uses the returned methodology packet to create or update the TestCandidate.

2.2 MINIMAL REQUEST SCHEMA ( Mix tra natural language e schematizzato (lo rende più simile a l1))

query_id: "q-123"

pattern: target_state | bypass | chaining

objective: "Natural-language decision the Planner is trying to make"

target_context:
  vulnerability_hypothesis: null
  observed_conditions: []
  defenses_present: []
  available_capabilities: []
  blocked_technique: null
  desired_condition: null

  QUesto è un proiezione di l1

constraints:
  scope: []
  authentication_state: unknown
  safety_level: non_destructive
  excluded_techniques: []

retrieval:
  mode: hybrid
  max_candidates: 5

2.3 MINMAL REPSONSE SCHEMA

query_id: "q-123"

summary: "Short evidence-grounded answer"

candidates:
  - technique:
      canonical_name: "Technique name"
      aliases: []

    relevance:
      relation_path:
        - "Condition A enables Technique"
        - "Technique bypasses Defense D"
        - "Technique exploits Vulnerability Class V"

      rationale: "Why this candidate matches the target state"

    applicability:
      satisfied_conditions: []
      missing_conditions: []
      conflicting_conditions: []

    expected_effect:
      produces_condition: null
      enables_next_action: null

    confidence: high | medium | low
    evidence_refs: []

knowledge_gaps:
  - "Target fact required before choosing safely"

source_chunks: []

2.4 TRE TIPI DI DOMADNE DELL'AGENT PLANNER (ISTANZIAZIONE DI 2.2)

1- TARGET STATE QUERY : Quali tecniche sono applicabili nel particolare environment e quali sono le difese?

ESEMPIO ISTANZIAZIONE:
pattern: target_state

objective: >
  Identify techniques applicable to the current fault hypothesis,
  environmental conditions, and defensive technologies.

target_context:
  vulnerability_hypothesis: "Injection weakness"
  observed_conditions:
    - "User-controlled input reaches a server-side query operation"
    - "Application returns differentiated errors"
  defenses_present:
    - "Web application firewall"
  available_capabilities:
    - "Unauthenticated HTTP access"

2- BYPASS QUERY : Technique T1 appears blocked by defense D; which alternative technique T2 can bypass it?

ESEMPIO ISTANZIAZIONE:

pattern: bypass

objective: >
  Find alternative techniques that bypass the observed blocking
  defense while preserving the original test objective.

target_context:
  vulnerability_hypothesis: "Injection weakness"
  blocked_technique: "Initial injection technique"
  defenses_present:
    - "Request-filtering defense"
  observed_conditions:
    - "Initial probes are rejected at the edge"
    - "Origin behavior has not yet been confirmed"
  available_capabilities:
    - "Control over one request parameter"

    3-CHAINING QUERY : Which technique establishes the missing prerequisite for the next planned action?

    ESEMPIO ISTANZIAZIONE:

   pattern: chaining

objective: >
  Find an intermediate technique that produces the environmental
  condition or capability required by the intended next action.

target_context:
  desired_condition: "Obtain an object identifier belonging to another account"
  observed_conditions:
    - "Authenticated low-privilege session"
    - "Object-oriented API"
  available_capabilities:
    - "Read access to the current user's objects"
  defenses_present:
    - "Object-level authorization checks are expected"

RUN TIME INGESTION AND ONTOLOGY MAPPING

flowchart LR
    OFF[Offline standards, books,<br/>curated methodology]
    BASE[Validated Base KB]

    WEB[Runtime writeups,<br/>blogs, aggregators]
    FILTER[Source and Content Filter]
    MAP[Ontology Mapper]
    OVER[Run Knowledge Overlay]

    BASE --> RET[Unified Retrieval]
    OFF --> BASE
    WEB --> FILTER --> MAP --> OVER
    OVER --> RET

    RET --> PACK[Methodology Packet]
    PACK --> PL[Planner]


Base KB

Contains relatively stable and curated knowledge:

testing standards;
methodology guides;
security books;
internally approved techniques;
reviewed mappings.
Run overlay

Contains knowledge collected for a specific run:

recent writeups;
technology-specific bypass discussions;
target-relevant blog posts;
aggregator results;
lower-confidence or newly extracted relations.

Every overlay entry carries a run_id. At the end of the run it can be:

discarded;
archived;
promoted to the base after review.

This avoids contaminating the stable methodology graph with duplicated, low-quality, or context-specific claims.

RUNTIME INGESTION FLOW 

flowchart TD
    URL[Candidate URL]
    SG[1. Source Gate]
    CE[2. Content Extraction]
    SF[3. Semantic Filtering]
    SS[4. Structure-Aware Segmentation]
    OE[5. Ontology Extraction]
    VA[6. Validation]
    DD[7. Merge and Deduplication]
    RO[Run Overlay]

    URL --> SG
    SG -->|accepted| CE
    SG -->|rejected| X[Discard]
    CE --> SF
    SF --> SS
    SS --> OE
    OE --> VA
    VA -->|valid| DD
    VA -->|uncertain| Q[Quarantine]
    DD --> RO

    3.3 Cleaning and filtering raw writeups
Source gate

Before processing the page, assign lightweight source metadata:

source_type: standard | vendor | research | practitioner_writeup | aggregator
authority: high | medium | low
original_or_mirror: original | mirror | unknown
published_at: "..."
retrieved_at: "..."
approved_for_ingestion: true

Aggregators should primarily be used to discover original sources. Prefer ingesting the original writeup rather than multiple mirrored copies.

Content extraction

Retain:

technical explanations;
prerequisites;
attack and defense observations;
success and failure conditions;
remediation or mitigation analysis;
diagrams and relevant tables;
code or request examples as indivisible blocks.

Remove:

navigation menus;
advertisements;
unrelated comments;
repeated headers and footers;
author biographies;
generic introductions with no methodology content;
duplicated exploit output;
SEO text.
Semantic filtering

A section should be retained only when it contributes at least one of:

Vulnerability Class
Environmental Condition
Attack Technique
Defensive Technology
Relation between them
Evidence explaining when a relation is valid

Pure storytelling can remain as source context but should not automatically create graph nodes.

3.4 Structure-aware writeup segmentation

A writeup should be divided by methodological episode, not by a fixed number of tokens.

Useful episode boundaries include:

Target or environment context
    ↓
Observed weakness
    ↓
Prerequisites
    ↓
Technique attempted
    ↓
Defense or failure encountered
    ↓
Bypass or alternative
    ↓
Result and limitations

Keep the following atomic:

a request and its corresponding response;
an exploit explanation and its prerequisites;
a defense and the bypass that specifically addresses it;
a code block and the paragraph that explains it;
a table row and its column meanings.

A fixed maximum token size may still exist as a safety limit, but it should not be the primary semantic boundary.

3.5 Ingestion LLM extraction instructions

The ingestion LLM should receive instructions conceptually equivalent to:

Read the supplied segment as offensive-security methodology. Extract only statements explicitly supported by the text or directly implied by a described result. Use only the approved entity types and relations. Normalize entity names to canonical security terminology while preserving aliases used by the source. Represent prerequisites as requires, environmental support as enables, defensive effects as mitigates or detectedBy, and explicit evasion methods as bypasses. Do not infer that a technique always works merely because it succeeded in one writeup. Attach the specific environmental conditions, limitations, evidence span, and source reference to every context-dependent relation. Omit unsupported relations rather than guessing.

The extraction result can conceptually resemble:

entities:
  - type: AttackTechnique
    canonical_name: "..."
    aliases: []
    description: "..."

relations:
  - source: "..."
    type: bypasses
    target: "..."
    applicability:
      - "..."
    limitations:
      - "..."
    evidence_excerpt: "..."
    confidence: medium
Important extraction rules

Facts versus interpretation

claim_status: explicit | strongly_supported | inferred

Only explicit and carefully bounded strongly_supported relations should enter the graph automatically. Inferred relations should be quarantined or retained only as non-authoritative annotations.

No context-free success claims

A writeup describing one successful bypass does not establish:

Technique always bypasses technology.

It establishes:

Technique bypassed the technology under conditions C
in source observation S.

Preserve negative evidence

Failures are useful:

Technique T is mitigated by defense D under condition C.
Technique T requires condition C, which was absent.

The runtime knowledge base should not contain only successful attack paths.

3.6 Simplest merge and deduplication logic

LightRAG already includes entity and relation deduplication as part of its graph indexing process, but the domain-specific ingestion layer should normalize identities before insertion.

Entity key

Use:

entity_key = normalized(entity_type + canonical_name)

Examples:

attack_technique::kerberoasting
defensive_technology::ldap_signing
environmental_condition::ldap_signing_disabled
vulnerability_class::weak_service_account_credentials
Merge sequence

flowchart LR
    N[New entity]
    E{Exact canonical key?}
    A{Known alias?}
    S{High semantic similarity<br/>and same type?}
    M[Merge]
    R[Create new node]
    Q[Manual/LLM review queue]

    N --> E
    E -->|yes| M
    E -->|no| A
    A -->|yes| M
    A -->|no| S
    S -->|clearly same| M
    S -->|uncertain| Q
    S -->|different| R

Never merge nodes merely because their embeddings are similar.

For example:

SQL injection and blind SQL injection are related but not automatically identical.
WAF and request filtering may overlap conceptually but differ in scope.
authentication bypass as a vulnerability class is not the same entity as an attack technique that produces authentication bypass.

Relation key

Use:

source_entity
+ relation_type
+ target_entity
+ applicability_fingerprint

Two identical relations from different sources should become one logical edge with multiple evidence records:

evidence:
  - source_ref: "source-A"
    confidence: high
  - source_ref: "source-B"
    confidence: medium

Descriptions and evidence should be appended, not overwritten.

4. Offline Document Ingestion
4.1 Hierarchical preprocessing

Offline documents need two linked levels of context:

flowchart TD
    DOC[Document]
    CH[Chapter / Major Section]
    SU[Methodology Unit]
    KG[Entities and Relations]

    DOC --> CH
    CH --> SU
    SU --> KG

Chapter-level representation

Create a compact chapter card containing:

document_title: "..."
heading_path:
  - "Part II"
  - "Active Directory"
  - "Delegation and Authentication"
chapter_summary: "..."
major_topics: []
source_ref: "..."

The chapter is primarily retrieval and provenance context. It does not need to become a core ontology node.

Methodology-unit representation

Split the chapter into units that express one coherent security statement:

one technique;
one prerequisite set;
one defensive mechanism;
one bypass;
one technique sequence;
one comparison between approaches;
one failure mode.

A methodology unit may contain several paragraphs when they describe the same relation.


4.2 Chunking rules

Prefer boundaries in this order:

Heading and subsection boundaries.
Technique or control boundaries.
Step-sequence boundaries.
Tables, figures, and code blocks.
Semantic-topic shifts.
Token-size limit only as a final constraint.

Each chunk should inherit:

document_id: "..."
heading_path: []
parent_summary: "One or two sentences"
page_or_section_ref: "..."
source_authority: high | medium | low

Avoid arbitrary overlap between chunks. Instead, prepend the heading path and a short parent summary so that each chunk remains understandable independently.

The LightRAG architecture already relies on document segmentation before extracting entities and relationships; preserving methodological continuity before this extraction reduces incomplete or misleading graph edges.

4.3 Mapping broad chapters into granular graph knowledge

A broad chapter such as Active Directory should not produce a single generic node connected to every technique.

Instead, the chapter is decomposed into concrete condition–technique–defense statements.

flowchart LR
    C1[Condition:<br/>AD domain is present]
    C2[Condition:<br/>SPN-bearing service account exists]
    C3[Condition:<br/>Service account credential is weak]
    C4[Condition:<br/>LDAP signing is disabled]

    T1[Technique:<br/>Kerberoasting]
    T2[Technique:<br/>NTLM relay to LDAP]

    V1[Vulnerability Class:<br/>Weak credential policy]
    V2[Vulnerability Class:<br/>Insufficient channel protection]

    D1[Defense:<br/>Managed service accounts / strong credentials]
    D2[Defense:<br/>LDAP signing]

    T1 -->|requires| C1
    T1 -->|requires| C2
    T1 -->|exploits| V1
    C3 -->|enables| T1
    D1 -->|mitigates| T1

    T2 -->|requires| C1
    T2 -->|requires| C4
    T2 -->|exploits| V2
    D2 -->|mitigates| T2

The chapter contributes:

global context through its summary and heading metadata;
specific graph knowledge through granular entities and relations.


Mapping procedure

For every broad section, ask:

What environmental states are described?
What attacker techniques become possible?
Which weakness does each technique exploit?
Which control detects or mitigates it?
Does the document describe an alternative or bypass?
Does one technique establish a condition required by another?

The result should be a set of small reusable claims such as:

Condition C enables Technique T.
Technique T requires Condition C.
Technique T exploits Vulnerability Class V.
Defense D mitigates Technique T.
Technique T2 bypasses Defense D under Condition C2.
Technique T1 enables Technique T2.

4.4 Handling broad conceptual material

Some material explains architecture rather than a specific attack:

Kerberos concepts;
trust boundaries;
domain and forest structure;
authentication flows;
certificate authority roles.

Do not force every paragraph into an attack relation.

Use broad material in three ways:

Parent summaries for high-level retrieval.
Definitions attached to already-existing conditions or defenses.
Source context returned alongside granular technique relations.

Create a graph relation only when the text supports a Planner-relevant dependency.

4.5 Final offline ingestion flow

flowchart TD
    PDF[PDF / Book / Standard]
    PARSE[Structural Parsing]
    HIER[Heading Hierarchy]
    CHUNK[Methodology-Aware Chunking]
    SUM[Parent Summaries]
    EX[Ontology Extraction]
    CHECK[Schema and Evidence Validation]
    MERGE[Canonical Merge]
    BASE[Validated Base KB]

    PDF --> PARSE
    PARSE --> HIER
    HIER --> CHUNK
    HIER --> SUM
    CHUNK --> EX
    SUM --> EX
    EX --> CHECK
    CHECK --> MERGE
    MERGE --> BASE


 RESULTING MVP ARCHITECTURE

 flowchart LR
    subgraph Target[Per-Run Target Knowledge]
        L0[Layer 0<br/>Assets and observations]
        L1[Layer 1<br/>Services, systems, conditions and data flows]
        MEM[Execution memory]
    end

    subgraph Methodology[Reusable Methodology Knowledge]
        BASE[Curated Offline Base]
        OVER[Runtime Run Overlay]
        LR[LightRAG Retrieval]
        BASE --> LR
        OVER --> LR
    end

    L0 --> ADAPTER[Planner Query Adapter]
    L1 --> ADAPTER
    MEM --> ADAPTER
    ADAPTER --> LR
    LR --> PACK[Evidence-Grounded<br/>Methodology Packet]
    PACK --> PLANNER[Planner]
    PLANNER --> TEST[TestCandidate /<br/>Specialized Agent Pod]

The resulting system stays lightweight because:

the target graph and methodology graph have separate identities and lifecycles;
the core ontology contains only four entity types and six relations;
runtime content is isolated in a per-run overlay;
LightRAG performs semantic and graph-enhanced retrieval;
the Planner receives evidence-grounded candidates rather than an uncontrolled execution plan;
new taxonomies, tools, topics, or source types can be added later without recutting the core model.
