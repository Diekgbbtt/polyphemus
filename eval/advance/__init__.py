"""The eval advance library: idle proxy, sync daemon, stack manifest, decision input.

Import the submodules directly - `advance.app_state` (the idle proxy over
`GET /app-state` with a postgres fallback), `advance.daemon` (the mechanical
advance daemon and its operator CLI), `advance.images` (running image digests),
`advance.manifest` (path groups and their SHAs), `advance.fingerprint` (the
compressed hash), and `advance.decision` (the structured diff the orchestrator
consumes). Importing any of them performs no I/O (CODING_STANDARD section 6);
every collaborator (git, HTTP, postgres, clock, alert sink) is injected at call
time.
"""
