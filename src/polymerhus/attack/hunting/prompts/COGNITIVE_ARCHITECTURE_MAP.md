# The cognitive architecture map

The shared map of the data every hunting agent reasons over.
It names the data domains and how they relate.
The concrete tools and their contracts are described on the tools themselves.

## The data domains

- **Target surface** - what the target exposes to a tester, and the judged model of it.
- **Target context** - the target's authentication state and its rate-limit posture.
- **Hunt memory** - the durable trail of this hunt and the artifacts earlier hunts left behind.
- **Request history** - the requests and responses the target has already served.
- **Testing knowledge** - the everything-vulnerability-testing knowledge base.
- **Procedural knowledge** - the vulnerability-testing skills.

## How they relate

The target surface and the target context describe what the target is and what access the target grants.
The testing knowledge and the procedural knowledge describe how to test.
The hunt memory and the request history describe what earlier work already saw and tried.
The procedural knowledge and the testing knowledge read together: a skill's notion sections correspond to the knowledge base's entity types, so a lack in one is a reason to consult the other.
When a domain is thin, the agent reads the other domains before asserting a conclusion.
