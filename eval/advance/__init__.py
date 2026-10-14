"""The eval stack-identity library: the running stack's manifest and fingerprint.

Import the submodules directly - `advance.images` (running image digests),
`advance.manifest` (path groups and their SHAs), and `advance.fingerprint` (the
compressed hash). These three are the components the operator drivers and the
orchestrator share to stamp a trial record's `stack_fingerprint` (ADR
`remove-advance-jumper-adr.md`): the version-jump daemon, its decision input,
and the alignment machinery were removed, but the identity computation stays.
Importing any of them performs no I/O (CODING_STANDARD section 6); every
collaborator (git, docker) is injected at call time, and the shared subprocess
seam is `orchestrator.effects`.
"""
