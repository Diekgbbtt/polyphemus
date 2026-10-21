# Anonymous model rendering - unit Service:model-download

## Interface agreements
- IA-1: A model install is requested by POSTing a full catalog record plus a caller-chosen ui_id; the receiving side admits the record to the global work queue after per-field membership checks against the served catalog.
- IA-2: Queue advancement and queue clearing are unauthenticated GET requests; start begins processing of the pending set and reset removes pending jobs while retaining the completed history.
- IA-3: Queue state is readable without authentication; the status endpoint returns global counts {total_count, done_count, in_progress_count, is_processing} and is mirrored under /api.
- IA-4: The external model catalog is served as one JSON document of 564 records; the mode parameter is accepted but does not change the served list.
- IA-5: The catalog channel selection is read and mutated through /manager/channel_url_list; mutation accepts only predefined channel names.
- IA-6: The outbound fetch worker downloads the catalog record's url and writes the bytes under the record's save_path and filename inside the model directories.
- IA-7: The manager shell renders catalog records; record fields are interpolated into the grid DOM by string concatenation.

## Trust agreements
- TA-1: The receiving side of IA-1 treats the posted record as a single catalog record: one legitimate artifact, one legitimate destination, submitted by an entitled caller.
- TA-2: The receiving side of IA-2 treats queue advancement as the operator's decision over the operator's own pending work.
- TA-3: The receiving side of IA-3/IA-4 treats queue counts and the catalog document as non-sensitive operational state of the deployment.
- TA-4: The receiving side of IA-6 treats the remote origin as the authoritative publisher of the artifact named by the catalog record, and the resolved path as confined to the intended model directory.
- TA-5: The receiving side of IA-5 treats the selected channel as the operator's intended catalog source.
- TA-6: The receiving side of IA-7 (the manager shell) treats catalog-derived strings as inert text when rendering the model grid.

## Dynamic-state transitions
- T-1: S0 -> S1: POST /manager/queue/install_model (+/api mirror) with a membership-passing record
    - enforced checks: per-field membership of url/filename/save_path in the served catalog sets; no validation present for name/description/reference/size/ui_id and no input-shape validation
    - relied-on requirements: the queued job's destination fields belong to the record's url (joint identity); the enqueued job is owned by the submitting client; the queue carries the state attributes (pending count, ui_id) that later steps rely on
    - side effects: pending count +1; job record in the global queue; status events
- T-2: S0 -> S0: POST install_model with a non-membership record or malformed body
    - enforced checks: rejection with 400 (filename/save_path), 403 (url) or 500 (shape/type faults)
    - relied-on requirements: rejected requests leave no partial queue state
    - side effects: none observed
- T-3: S1 -> S2: GET /manager/queue/start
    - enforced checks: no guard present: no identity, origin or entitlement check; the sole condition is a non-empty pending set
    - relied-on requirements: the caller advancing the queue is entitled to run those jobs; the pending set is the set the caller intends to run
    - side effects: worker loop started; per-job fetch/write; done_count increments; installed flips
- T-4: S2 -> S3: worker completes a job (fetch + write)
    - enforced checks: the origin answered with some bytes (no integrity assertion observed); the file is written under models/<save_path>/<filename>
    - relied-on requirements: the bytes are the artifact the catalog intended (integrity); the write stays inside the intended model directory; the destination directory state (existing files, installed flags) is consistent after the write
    - side effects: file persisted (S4); done_count +1; status event with target=ui_id
- T-5: S1 -> S0: GET /manager/queue/reset
    - enforced checks: no guard present: no identity or ownership check
    - relied-on requirements: the cleared jobs belong to the caller; cleared work is reported to its submitter
    - side effects: pending set cleared; done history retained; no filesystem rollback
- T-6: S0 -> S0: GET /manager/queue/start with an empty pending set
    - enforced checks: idempotent no-op returning 200 with an empty body
    - relied-on requirements: no side effects on installed state
    - side effects: none observed
- T-7: S2 -> S1: POST install_model while is_processing is true
    - enforced checks: server-side acceptance of an enqueue during processing
    - relied-on requirements: adding work mid-run does not invalidate the running job's state assumptions
    - side effects: unknown
- T-8: S2 -> S0: GET /manager/queue/reset while is_processing is true
    - enforced checks: whether in-progress work is cancelled, orphaned or allowed to finish
    - relied-on requirements: an in-flight write is not left half-committed by a concurrent reset
    - side effects: unknown

## Assumptions
- A-1: Developer assumption: a posted model record is validated as a unit, so the fields the worker uses (url, filename, save_path) describe one artifact and its destination.
    - induced fault: membership is checked per field over the union of catalog values instead of binding the record, so catalog values can be recombined freely (induced fault F-1). (?)
- A-2: Developer assumption: ui_id is the caller's job identity and can be trusted as the correlation key for status reporting.
    - induced fault: an unvalidated, unbound client string is stored on the job record and echoed in broadcast status events (induced fault F-2). (?)
- A-3: Developer assumption: only the deployment's operator reaches the manager routes, so triggering downloads and advancing the queue need no principal gate.
    - induced fault: no privilege layer exists on state-changing, egress-producing, filesystem-writing operations (induced fault F-3). (?)
- A-4: Developer assumption: the pending queue belongs to the caller that filled it and stays stable until that caller starts it.
    - induced fault: the queue is a single global set with no ownership binding, so third-party resets and starts act on foreign work (induced fault F-4). (?)
- A-5: Developer assumption: queue transitions are atomic with respect to in-flight work; a reset cannot disturb a job the worker is already consuming.
    - induced fault: pending/in-progress states are not distinguished for reset, and the in-flight guard is client-side only (induced fault F-5). (?)
- A-6: Developer assumption: the bytes fetched from the catalog url are the artifact the catalog intends; size is informational and integrity need not be verified.
    - induced fault: no hash, signature or size enforcement gates the install (induced fault F-6). (?)
- A-7: Developer assumption: catalog-derived strings are inert when the manager shell renders them.
    - induced fault: catalog fields are interpolated into the grid DOM with an unquoted attribute and no escaping (induced fault F-7). (?)
- A-8: Developer assumption: membership in the catalog value sets is sufficient proof that a save_path/filename is path-safe.
    - induced fault: path safety is delegated entirely to catalog membership; no normalization or canonical check guards accepted values (induced fault F-8). (?)
- A-9: Developer assumption: malformed bodies cannot reach business logic (missing keys and wrong types are impossible through the shell).
    - induced fault: unguarded field access and type use in the validation path raise unhandled exceptions (induced fault F-9). (?)

## Vulnerabilities
- V-1: catalog record recombination (validation-scope confusion): any catalog url can be paired with any other record's filename and save_path, so the fetch source and the write destination need not belong together (fault F-1)
- V-2: unbound job-identifier spoofing: ui_id is a caller-chosen correlation key rendered by other clients' shells, with no binding to the submitting session (fault F-2)
- V-3: forced operations via cross-site request forgery: download-triggering POSTs accept simple content types without a token or origin check, and queue advancement/clearing happens over GET (fault F-3)
- V-4: shared-queue manipulation without ownership binding: any caller can clear pending work or advance another submitter's jobs, with no notification to the owner (fault F-4)
- V-5: TOCTOU/race between queue reset-start and the worker's fetch-write: state transitions are not atomic and the in-flight guard is client-side only (fault F-5)
- V-6: unverified third-party artifact installation: model files land in the model directories with no integrity check; the artifacts are later loaded by a pickle-capable stack (fault F-6)
- V-7: catalog-driven DOM injection in the manager shell: record name and reference are interpolated into the grid with an unquoted attribute and no escaping (stored XSS shape) (fault F-7)
- V-8: path traversal contingent on a catalog entry value: membership is the only path-safety control, so a catalog value containing traversal segments would be admitted verbatim (fault F-8)
- V-9: validation-layer oracle: differentiated rejections (400 invalid request / 403 security error / 500 server trouble) tell a caller which field failed and which layer guards it (fault F-9)
- V-D1: DROPPED (falsified): server-side request forgery via the client-supplied url field of an install record (fault F-1)
- V-D2: DROPPED (falsified): SSRF via the catalog mode parameter driving the outbound catalog fetch (fault F-1)
- V-D3: DROPPED (falsified): untrusted fetch via the record reference field (a forged reference was accepted into the queue) (fault F-1)
- V-D4: DROPPED (falsified): catalog-source redirection by injecting a name::url value into the channel selection (would have enabled a stored SSRF/XSS precondition) (fault F-3)

## Loops
- loop-1: fault F-1 -> V-1 (high)
- loop-2: fault F-3 -> V-3 (high)
- loop-3: fault F-4 -> V-4 (medium)
- loop-4: fault F-9 -> V-9 (medium)
- loop-5: fault F-5 -> V-5 (low)
- loop-6: fault F-7 -> V-7 (low)
- loop-7: fault F-6 -> V-6 (low)
- loop-8: fault F-8 -> V-8 (low)
- loop-9: fault F-2 -> V-2 (low)
