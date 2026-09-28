"""The eval advance library: stack manifest, fingerprint, and decision input.

Import the submodules directly - `advance.images` (running image digests),
`advance.manifest` (path groups and their SHAs), `advance.fingerprint` (the
compressed hash), and `advance.decision` (the structured diff the orchestrator
consumes). Importing any of them performs no I/O (CODING_STANDARD section 6);
every collaborator (git, docker) is injected at call time.
"""
