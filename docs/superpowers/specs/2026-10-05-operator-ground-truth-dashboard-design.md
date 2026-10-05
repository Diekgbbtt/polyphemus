# Operator-only ground truth in the Trial dashboard

## Intent and scope

An operator opening a Trial should see the benchmark reference for each
materialized verdict directly beneath that row's verdict, confidence, unit,
fault class, and symptom. The discovery agent must never gain a route to that
reference. The existing Target index / dedicated Trial page change is already
committed as `1a08c6e0`; this design adds the reference view and corrects its
`copied_at` display to the browser's local timezone. Token usage is explicitly
out of scope.

The reference is **current WebExploitBench checkout ground truth**, not an
immutable capture from the time of a historical Trial. The published Trial
manifest does not identify a benchmark checkout revision. The UI must label
this provenance and must not claim the ground truth was captured with the
Trial. A future historical-capture feature would need its own provenance and
operator-only storage design.

## Existing boundaries and data

- The normal `eval-api` and the discovery `agent` share `polymerhus-net`.
  Publishing ground truth from `eval-api`, or proxying it through the current
  dashboard container, would make it reachable from that network even though
  the host publishes port 5173 only on loopback.
- WebExploitBench has one `<target>/challenge.json`, with a `vulnerabilities`
  array. Each `vuln_id` has
  `<target>/vulnerability/<vuln_id>/metadata.json`; `eval/gt.py` already reads
  scoring signals from the first and `Location` / `Vulnerability Type` from
  the second. There is no `challenge.json` per vulnerability.
- The setup's `target_id` and `target_key` are distinct facts (for example,
  `comfyui-1` and `webexploitbench/comfyui`). The API must use an explicit,
  validated mapping from operator-approved setup files, never strip a suffix
  or treat an HTTP path segment as a filesystem path.
- `copied_at` is the store materialization timestamp; it is not the trial's
  start or finish time.

## Architecture and security

Add a separate, GET-only `eval-operator-api` in an opt-in Compose overlay.
The service mounts only the WebExploitBench checkout and the relevant eval
configuration read-only. It has no Docker socket, no agent credentials, and
is **not attached to `polymerhus-net` or any network shared with the discovery
agent**. Its own bridge network is used only for port publishing. Docker
publishes its HTTP port on server `127.0.0.1:8091` only. The existing
`eval-api`, dashboard proxy, and agent routes remain unchanged. Set the same
`unless-stopped` restart behavior as the dashboard services.

The overlay requires an explicit absolute `EVAL_WEB_DIR_HOST_PATH` for the
host's WebExploitBench checkout; startup fails if it is absent rather than
creating an empty directory. Inside the service it is mounted at a fixed
path. `EVAL_OPERATOR_SETUP_FILES` names the approved setup basenames under
`eval/setups/` (initially `first.yaml` and `webexploitbench-chain.yaml`);
arbitrary paths are not accepted. The configured CORS origin defaults to the
documented local dashboard address below.

An operator opens two forwards in one SSH command:

```text
ssh -N -L 15173:127.0.0.1:5173 -L 18091:127.0.0.1:8091 root@46.224.225.245
```

The SPA at `http://localhost:15173/` calls the operator API at
`http://localhost:18091/`. The operator API allows only the configured local
dashboard origin in CORS (default `http://localhost:15173`); no wildcard
origin. CORS supports the browser but is **not** the security boundary: the
separate Docker network and server-loopback port are. Local server processes
and users with SSH access are within the operator trust boundary. A missing
second forward must not affect the normal Trial results.

The service reads the operator-configured setup files with the existing setup
parser and builds `target_id -> target_key`. Duplicate identical mappings are
fine; conflicting mappings fail closed for that target. Only a configured
dataset/target under the mounted benchmark root may be read. Symlinks and
traversal out of that root are rejected. A new target outside the configured
setups has no ground truth until its setup is included; it is never guessed.

## Operator API contract

`GET /ground-truth/targets/{target_id}` returns a bounded, path-free JSON
projection of the target's current benchmark reference:

```json
{
  "target_id": "comfyui-1",
  "provenance": "current_benchmark_checkout",
  "vulnerabilities": [
    {
      "vuln_id": "comfyui-001",
      "location": "http://comfyui-manager:8288/",
      "type": "Arbitrary File Read",
      "scoring": ["LLM_judge"]
    }
  ]
}
```

Only these fields are returned; `scoring` is an array of validated string
signal names, not arbitrary JSON from the challenge. No raw challenge
document, reports, verify scripts, exploits, host filesystem paths, or trace
data are served. Input IDs and source strings are validated and output size
is bounded. Missing or ambiguous mapping, missing challenge, or invalid
challenge JSON produce stable
path-free unavailable/error responses. Missing or invalid metadata for one
vulnerability omits only that entry; valid siblings remain. `GET /health`
checks service readiness without returning ground truth. No ground-truth
route is added to the shared `eval-api` or dashboard proxy.

## Frontend behavior

The dedicated Trial page requests the target-level reference once, after
loading its ordinary results. Within every verdict row, immediately below
the match cards, render a small "Ground truth (current benchmark)" group
matched by exact `vuln_id`: Location, Vulnerability type, and Scoring signals.
The row remains otherwise unchanged. If the API or a matching reference is
unavailable, show "Ground truth non disponibile" in that row; never borrow a
different vulnerability's entry and never hide the verdict, diagnosis, graph,
or artifacts. The normal Target index does not fetch ground truth.

The existing `SavedOn` component formats a valid `copied_at` in the browser's
timezone and renders a semantic `<time dateTime="...">` in both Target index
and Trial detail. Null or invalid values render "Data non disponibile". No
timestamp is synthesized from `trial_id`.

## Verification and rollout

Write backend tests for mapping, conflicting IDs, path/symlink guards,
partial retention, bounded output, path-free errors, CORS, and route absence
from the shared read API. Compose tests assert the operator service is not on
`polymerhus-net`, mounts are read-only, and the published port is loopback.
Frontend tests cover exact verdict-to-reference pairing, unavailable API or
row, no fetch on Target index, and local-time/null date rendering. Verify the
normal frontend suite and build.

On the eval server, deploy the new overlay without changing the discovery
stack, inspect the service network and port binding, verify host-loopback and
SSH-tunnel requests, and test from inside the `agent` container that neither
the operator service name nor its host-loopback port is reachable. Do not
publish the operator API on a public interface. Deployment is a separate
step after implementation review; this document itself changes no server
state.
