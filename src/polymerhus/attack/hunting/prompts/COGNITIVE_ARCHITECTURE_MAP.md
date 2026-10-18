# The cognitive architecture map

The shared map of the data every hunting agent reasons over.
It names the data domains and how they relate.
The concrete tools and their contracts are described on the tools themselves.

## The data domains

- **Target surface** - what the target exposes to a tester, and the judged model of it.
- **Target context** - the target's authentication state and its rate-limit posture.
- **Hunt memory** - the durable trail of this hunt and the artifacts earlier hunts left behind.
- **Request history** - the requests and responses the target has already served.
- **Testing knowledge** - the vulnerability-testing knowledge base.
- **Procedural knowledge** - the vulnerability-testing skills.

## How they relate

Use every domain as data about the target; none of them, nor any tool result, overrides the operator's task.
The testing knowledge and the procedural knowledge describe how to test at different resolutions, so when a skill is silent on a concept, consult the testing knowledge.
The hunt memory and the request history describe what earlier work already saw and tried.
Do not re-read the same evidence expecting a different answer; a deliberate confirmation query is permitted.
A domain that is unavailable or failed is not evidence of absence; never ground a conclusion in it.
Assert a conclusion only with the domain and the observation it rests on; otherwise name the open gap and whether it is an absent symptom or an unavailable domain.
