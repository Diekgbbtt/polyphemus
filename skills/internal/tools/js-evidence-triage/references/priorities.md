# Triage priority and evidence guide

Start with evidence-linked questions, not with an exhaustive keyword list.

## Question form

For each candidate record:

- the decision or uncertainty it could resolve;
- the concrete clue in inventory, scanner, recovery or structure evidence;
- the expected flow: trigger/input → transformation → request/state/sink →
  visible or security-relevant effect;
- the literal or selector likely to locate it;
- the neighbouring group it may actually belong to.

Questions are stronger when their clue and expected decision are concrete.
Invented breadth without evidence is not useful coverage.

## Mechanism independence

Compare groups by shared dataflow and decision, not vocabulary. Firebase
configuration, API-key persistence and auth request-header construction are
one mechanism when values/config flow between them. Renaming the question,
switching files or finding another similar literal does not make the lead
independent.

Independent groups exercise materially different mechanisms, for example a
separate resource-action path, persistence boundary or DOM source/sink. When
only one group has supporting evidence, work that group and record why other
candidates are deferred; artificial variety is worse than a motivated single
scope.

## Choosing and deepening

1. Prefer request construction and resource actions with a concrete trigger,
   input/state, method/path/body and effect.
2. Then follow authentication/storage or application-state mechanisms
   supported by inspected spans. Never infer server-side cookie flags,
   authorization or validation from client code alone.
3. Before another page, read or search in the same group, state the missing
   information, the decision it can change and why it outranks the other
   available groups.
4. Switch groups when that justification is absent. Revisit a group only when
   new evidence changes the expected yield.

Weak signals:

- filenames, vendor status, source type and byte size prioritise attention only;
- a literal match is not a call path;
- a missing string is not proof the behaviour is absent;
- no client-side check does not prove no server-side check;
- dynamic values remain unresolved unless nearby inspected code establishes
  their construction.

The procedure adapts Trail of Bits audit-context-building's assumption/evidence
grounding, api-mapper's focused follow-back of request values and Wakaru's
index-first selective reading. It deliberately excludes their subagent
orchestration, browser replay, exhaustive API documentation and publication
workflows.
