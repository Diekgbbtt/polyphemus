# Hunting #66 - Critical review of the spine-systems enum (SYSTEM_KINDS)

Status: reported artifact (operator-requested follow-up, part of the
curation-decisions review). Not a runtime gate.
Date: 2026-08-05.

The `SYSTEM_KINDS` enumeration (`src/polymerhus/analysis/l1_curator.py:83`,
12 kinds) doubles as the technical axis of the fault-KB `enum_kinds` tag
(`src/polymerhus/attack/hunting/fault_kb.py:43-47`), gating which fault
entries can be asserted for which system surface. This review stress-tests
the enum against the scraped PortSwigger ground truth
(`tools/hunting/portswigger-scrape/faults-extracted.md`, 30 topics,
347 fault classes) plus the operator's HTB-derived addendum (DNS rebinding,
CWE-350).

## 1. Surface coverage - every scraped fault class maps onto the 12 kinds

The 30 scraped topics were mapped to the system surface each fault class
manifests on; no scraped fault class was left without a natural kind:

| Surface | Kind(s) | Topics fed |
| --- | --- | --- |
| Edge / front layer | WAF, CDN, ReverseProxy, APIGateway | request smuggling (15 classes), cache poisoning (10), cache deception (9), host-header (11), SSRF-routing |
| API layer | RESTApi, GraphQLApi | SQLi, NoSQLi, command injection, path traversal, XXE, SSRF, deserialization, mass assignment, GraphQL, file upload |
| Identity layer | IdentificationSystem, AuthenticationMechanism | authentication / MFA / password reset (CWE-287), JWT (CWE-345), OAuth (CWE-352) |
| Authorization | AuthorizationSystem | access control / IDOR / privilege escalation (CWE-284) |
| Browser surface | WebPresentation | XSS / DOM (CWE-79), CSRF (CWE-352), clickjacking (CWE-1021), CSTI, dangling markup, DOM clobbering |
| Cross-origin | IntegrationSystem | CORS (CWE-942), CSP |
| Site structure | Sitemap | (none of the fault classes; see section 3) |

## 2. Findings

1. **No missing kind.** The complete scraped syllabus plus the
   DNS-rebinding addendum is expressible with the current 12 kinds.
   In particular: WebSocket-surface faults (CSWSH, CWE-1385) and
   prototype pollution (CWE-1321) are already multi-tagged
   `{RESTApi, WebPresentation}` / `{RESTApi, GraphQLApi, WebPresentation}` -
   the surfaces the code runs on - so no `WebSocketApi` / `SSRApi` kind is
   needed; the transport does not define a new service surface.
2. **CWE-350 (DNS rebinding, the operator's HTB addendum) is untagged.**
   It rides the fail-open NL-only path (`enum_kinds` empty). The fault
   manifests on the API/service surface performing the outbound request,
   so `RESTApi` (and `APIGateway` where the fetch is gateway-side) is the
   natural tag. Recommended as a follow-up tagging decision - or kept
   NL-only deliberately, per the R-c retirement path (spec section 5.4).
   Either way the matching still reaches it.
3. **Edge-layer kinds are under-utilised (2 entries each) but correct.**
   Only CWE-444 (request smuggling) and CWE-551 (incorrect behavior order)
   carry `{WAF, CDN, ReverseProxy, APIGateway}`. The cache-poisoning /
   cache-deception families (CWE-644, 10 + 9 scraped classes) sit on CDN /
   ReverseProxy surfaces yet carry `{RESTApi, WebPresentation}` or no tag.
   This is a tagging-accuracy gap, not an enum gap: the kinds exist, the
   entries are conservatively tagged. Follow-up re-tagging candidate.
4. **Business-logic faults (CWE-841, 10 scraped classes) are
   kind-orthogonal.** Logic flaws (excessive trust in client-side
   controls, flawed transaction workflows) span every surface. Keeping
   them NL-only / surface-agnostic is the correct design; no
   `BusinessLogicSystem` kind should be minted.
5. **LLM-attacks (10 scraped classes) map to CWE-77's concrete children**
   (CWE-78/88/624/917/1427 - command/code-injection family). The prompt-
   injection family is not a distinct system surface either; it is a
   content-injection class riding the WebPresentation/RESTApi surfaces.
   The provisional phase-3 fault-hypothesis vocabulary owns this framing;
   the fault-KB mapping stands.
6. **Sitemap is dead in the fault axis (0 entries) but alive in L1.**
   `Sitemap` is never used as an `enum_kinds` tag, and correctly so - a
   site-map system is not a fault surface. It stays in the enum because
   the L1 curator classifies sitemap systems (cross-context use, not a
   catalogue tag). Do not remove.

## 3. Verdict

The 12-kind enum is complete and well-shaped for the scraped ground truth:
zero required additions, zero harmful members. Three follow-up tagging
candidates (CWE-350 `RESTApi`/`APIGateway`, CWE-644 edge-layer kinds,
and the conservative edge-layer utilisation) are enrichment items, not
enum defects.
