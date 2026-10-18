# Anonymous model rendering - unit Service:model-download

## Interface agreements
- IA1: The client submits a model download as a JSON body to POST /manager/queue/install_model with keys name, url, filename, save_path and an optional ui_id; the /api prefix serves the same handler.
- IA2: For a filename without a .safetensors suffix the handler requires the (name, save_path, filename) triple to exist in the default-channel model catalog and the url to equal a member of the catalog URL set exactly; a missing triple gives 400, a URL outside the set gives 403.
- IA3: A filename ending in lowercase .safetensors bypasses catalog membership; any host-bearing URL is accepted with 200, while an uppercase .SAFETENSORS suffix is rejected with 400.
- IA4: Status codes form the contract: 200 queued, 400 invalid request, 403 security denial, 500 unhandled exception; GET on install_model returns 404 and POST on status returns 405.
- IA5: Accepted items do not process spontaneously; only GET /manager/queue/start drains the queue; the status counters are total_count, done_count, in_progress_count and is_processing.
- IA6: The worker, not the request handler, performs the outbound fetch; the fetch happens after the enqueue response and follows the supplied URL scheme and authority.
- IA7: The worker writes the fetched body to models/<save_path>/<filename>, creates missing directories, and concatenates the path components without canonicalization (a .. save_path is accepted).
- IA8: A manager middleware enforces the model-install security policy ahead of the handler and answers 403 with the fixed message A security error has occurred.
- IA9: The queue accepts a caller-supplied ui_id verbatim as arbitrary JSON; a dict value is accepted with 200 and processing then halts before the fetch.
- IA10: GET /externalmodel/getlist?mode=default returns the catalog JSON with entries carrying name, type, base, save_path, description, reference, filename and url; the same catalog feeds the install gate.
- IA11: Model inventory is exposed as JSON: /models lists directories, /experiment/models/<dir> lists files with size, created and modified; direct file GET paths return 404.
- IA12: The worker processes queued items serially; one start drains every item unless processing halts; several items can be enqueued between starts.

## Trust agreements
- TA1: The handler trusts the JSON body to encode a legitimate install request; no principal, session or token is read, and any anonymous client reaches the trust decision.
- TA2: The gate trusts the validated catalog tuple and the queued tuple to be the same data; actually the catalogue lookup binds name, save_path and filename while the url is only checked for set membership across catalog URLs.
- TA3: The gate trusts the filename suffix as the discriminator of scrutiny: lowercase .safetensors marks the item safe and skips catalog membership; the payload behind the name is never inspected.
- TA4: The worker trusts the queued url to be a fetchable HTTP resource; the client is trusted not to aim the fetch at the internal network, the loopback interface or local files.
- TA5: The worker trusts save_path and filename to be harmless path components under the models root; no canonicalization check runs before the write.
- TA6: The write path trusts the fetched bytes to be a model payload; content is stored under the client-chosen name and every consumer of the model tree then trusts that name.
- TA7: The queue trusts ui_id to be a hashable string; it is consumed in the progress and bookkeeping path without type validation.
- TA8: The UI and operators trust the queue counters as authoritative execution truth; the reset path trusts done_count to mean completed work.
- TA9: The manager trusts the fixed channel list (GitHub raw URLs, selected default) as the only catalog source; no runtime custom URL channel was observed.
- TA10: The queue trusts state-changing operations (start, reset) to be deliberate; both are GET endpoints with no auth and no CSRF token, so any HTTP participant can cross the idle-to-drained and drained-to-stale transitions.

## Dynamic-state transitions
- ET1: ES1 -> ES2: POST /manager/queue/install_model with a gate-passing triple.
    - enforced checks: Extension membership rule and catalog membership rule (IA2/IA3).
    - relied-on requirements: The client is a legitimate operator.
    - side effects: Queue append; total_count may advance.
- ET2: ES2 -> ES2: Further accepted installs before a start.
    - enforced checks: Same as ET1.
    - relied-on requirements: Each ui_id is unique.
    - side effects: Append; duplicate ui_ids accepted (P32/P34).
- ET3: ES2 -> ES4: GET /manager/queue/start.
    - enforced checks: None observed.
    - relied-on requirements: The queue drains serially and cleanly to an empty state.
    - side effects: Fetches and writes per item; done_count advances.
- ET4: ES4 -> ES5: GET /manager/queue/reset.
    - enforced checks: None observed; no auth, GET-accessible.
    - relied-on requirements: Reset zeroes the queue and its counters.
    - side effects: Counters retained (trust bend).
- ET5: ES5 -> ES2: Install accepted on top of stale counters.
    - enforced checks: Gate as ET1.
    - relied-on requirements: Counters restart from zero after reset.
    - side effects: Adds to stale totals; undercount persists.
- ET6: ES2 -> ES6: GET /manager/queue/start while the head item carries a non-string ui_id.
    - enforced checks: None; ui_id type never checked.
    - relied-on requirements: Client-supplied ids are always strings.
    - side effects: Worker halts; tail stays queued; no error surfaced to any client.
- ET7: ES6 -> ES7: A further GET /manager/queue/start after the poison head is disposed.
    - enforced checks: None.
    - relied-on requirements: A stalled queue needs no operator intervention beyond another start.
    - side effects: Tail item processed; done_count advances.
- ET8: ES4 -> ES4: GET start on an empty queue.
    - enforced checks: None.
    - relied-on requirements: Idempotent no-op.
    - side effects: None observed.

## Assumptions
- A1: A .safetensors filename proves the item belongs to the trusted model ecosystem, so catalog membership checks are unnecessary for such names.
    - induced fault: F1 (Catalog-membership bypass via filename extension shortcut)
- A2: Model URLs always point at public content hosts, so no destination filtering of the outbound fetch is needed.
    - induced fault: F2 (No egress allowlist on the outbound fetch)
- A3: Rejecting the file:// shape as typed covers local-file schemes; case variants and authority forms do not need separate handling.
    - induced fault: F3 (Scheme filter matches narrow textual forms only)
- A4: Any URL that appears in the catalog is safe to fetch, so url-by-url set membership is as strong as binding the URL to its catalog entry.
    - induced fault: F4 (URL checked by catalog set membership, not bound to the admitting entry)
- A5: save_path values originate from the catalog dropdown, so they are benign and need no path validation.
    - induced fault: F5 (save_path accepted as an unvalidated relative path)
- A6: Clients send well-formed JSON request bodies, so parse failures cannot occur in practice.
    - induced fault: F6 (Unhandled request-body errors return 500)
- A7: ui_id is always a string produced by the manager shell, so the queue does not validate its type.
    - induced fault: F7 (ui_id consumed without type validation)
- A8: Queue counters mirror queue contents, so status readers can trust total_count and done_count as the execution truth.
    - induced fault: F8 (Queue counters diverge from accepted and executed items)
- A9: Only the manager shell calls start and reset, so GET semantics for state-changing operations carry no risk.
    - induced fault: F9 (State-changing operations exposed as GET)
- A10: The GitHub channel is trusted to serve authentic catalog content, so catalog entries need no local integrity verification.
    - induced fault: F10 (Catalog content trusted from the fixed remote channel without local integrity anchoring)
- A11: save_path and filename are simple names without separators, so string concatenation under the models root is safe.
    - induced fault: F11 (Write path built by string concatenation without canonicalization)
- A12: The attributes that passed the gate are the same attributes the worker later uses.
    - induced fault: F12 (Check-to-use gap between gate validation and queued attributes)
- A13: Each request carries a unique ui_id, so duplicate keys cannot disturb queue bookkeeping.
    - induced fault: F13 (Duplicate ui_id accepted without reconciliation with bookkeeping)
- A14: Requests arrive one at a time, so queue mutation needs no locking against concurrent start and install calls.
    - induced fault: F14 (Queue mutation lacks concurrency guards)
- A15: The deployment is a single-user local application, so authentication is unnecessary and absence of principals is acceptable.
    - induced fault: F15 (No authentication surface anywhere on the manager routes)

## Vulnerabilities
- VUL1: Server-side request forgery (SSRF) (fault F2)
- VUL2: Local file inclusion / arbitrary local file read (fault F3)
- VUL3: Unrestricted remote-content write into the model store (write-what-where under models) (fault F5)
- VUL4: Business-logic bypass of the model catalog membership control (fault F1)
- VUL5: Path traversal via save_path (write outside the intended model subdirectory) (fault F5)
- VUL6: Cross-entry artifact substitution (validated entry not bound to the used URL) (fault F12)
- VUL7: Unauthenticated state-changing GET (CSRF-able queue control) (fault F9)
- VUL8: Denial of service via worker crash (serial worker starvation) (fault F7)
- VUL9: Queue accounting corruption (completion-state lying) (fault F8)
- VUL10: Information exposure of model inventory and fetched content (fault F15)
- VUL11: Improper error handling on request parsing (unhandled exceptions) (fault F6)
- VUL12: Race condition in queue mutation (concurrent start and install) (fault F14)
- VUL13: Archive extraction path traversal (zip-slip) on downloaded artifacts (fault F11)
- VUL14: Supply-chain substitution via repository (HuggingFace-style repo) downloads (fault F12)
- VUL15: Catalog poisoning leading to stored XSS in the manager shell (fault F10)
- VUL16: Arbitrary content staging into the custom_nodes code directory (fault F1)

## Loops
- loop-1: fault F2 -> VUL1 (high)
- loop-2: fault F3 -> VUL2 (high)
- loop-3: fault F5 -> VUL3 (high)
- loop-4: fault F1 -> VUL4 (high)
- loop-5: fault F3 -> VUL2 (medium)
- loop-6: fault F5 -> VUL5 (medium)
- loop-7: fault F12 -> VUL6 (medium)
- loop-8: fault F9 -> VUL7 (medium)
- loop-9: fault F7 -> VUL8 (medium)
- loop-10: fault F8 -> VUL9 (medium)
- loop-11: fault F15 -> VUL10 (medium)
- loop-12: fault F6 -> VUL11 (low)
- loop-13: fault F14 -> VUL12 (low)
