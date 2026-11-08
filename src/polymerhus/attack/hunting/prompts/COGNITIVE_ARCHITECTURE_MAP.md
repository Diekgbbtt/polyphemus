# Cognitive architecture map

The domains, the relationships and the map to navigate optimally the vulnerability discovery system data.
Each domain has a respective tool to access it.

## Domains

- **Target surface** - the target attack surface exposed, and the adversarially orientation of the solution architecture reconstructed from it.
- **Target context** - the target's authentication state and its rate-limit posture.
- **Hunt memory** - the durable trail of artifacts that the hunt toward the target left behind.
- **Episodic memory** - Concise thoughts of distinct adversarial reasoning workflow steps.
- **Request history** - previous requests and responses exchanges that were already observed.
- **Web offensive security knowledge** - a knowledge base gathering countless information on web offensive security: vulnerabilities classes and variants, kill chains, testing techniques and strategies, payload patterns(encodings and content) and vectors, stack technologies misconfigurations, vulnerability sysmptoms, and defensive controls, attacker capability, precondition environment.
- **Procedural knowledge** - the vulnerability-testing skills.

## Relationships

The offensive security knowledge and the procedural knowledge describe how to test at different resolutions. When a skill is silent on a concept, consult the offensive security knowledge. Or query deeply the koffeive security knowledge when you need to fill a creativity gap in your thought process. 
The hunt memory and the request history describe what earlier work already saw and tried. Use the request history database primarily to prevent redundant hypothesis verification probes or vulnerability-testing payloads and vectors. Similarly, use the hunt and episodic memory to prevent testing for redundant vulnerabilities, and importantly for integraitng insights from different research directions.  
A domain that is unavailable or failed is not evidence of absence; never ground a conclusion in it.
