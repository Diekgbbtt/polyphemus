# Install: the eval advancement daemon

The daemon is the advancement plane of D34.
It fast-forwards every eval worktree from `dev` to `eval` only when the idle proxy says all instances are idle, stashes and pops leaked tracked edits, records the last-known-good `eval` SHA before each move, and writes a heartbeat every poll.
It never fetches from origin and never rewinds on its own.

## Files

- `eval-advance.service` - the systemd unit.
- `eval-advance.env.example` - the full configuration surface, one variable per line.

## Install

1. Ensure the checkout's `eval/` directory is on the server at the path the unit expects, and adjust `WorkingDirectory=` in `eval-advance.service` if it is not `/opt/polymerhus/eval`.
2. Copy the env template and edit every path and URL for this host:

   ```sh
   install -d /etc/polymerhus /var/lib/polymerhus-eval
   install -m 0640 eval-advance.env.example /etc/polymerhus/eval-advance.env
   ${EDITOR:-vi} /etc/polymerhus/eval-advance.env
   ```

3. Install and start the unit:

   ```sh
   install -m 0644 eval-advance.service /etc/systemd/system/eval-advance.service
   systemctl daemon-reload
   systemctl enable --now eval-advance
   systemctl status eval-advance
   ```

4. Confirm the heartbeat is being rewritten (`timestamp` advances on each poll):

   ```sh
   cat /var/lib/polymerhus-eval/heartbeat.json
   ```

## Operator rewind

Rewind is deliberately not part of the polling loop.
An operator rolls `eval` back to a SHA the daemon recorded as last-known-good:

```sh
cd /opt/polymerhus/eval
python3 -m advance.daemon rewind <sha> --confirm
```

Without `--confirm`, or with a SHA outside the recorded history, the command is refused and nothing moves.

## Notes

- The idle proxy reads `GET /app-state` first and falls back to the documented direct-postgres query through `psql`; if both are unavailable the daemon refuses to advance (unknown is not idle).
- The alert threshold is intentionally not invented here.
  The structured log line is always emitted; an optional shell hook can be configured.
- The heartbeat carries each eval worktree's observed HEAD and whether it reached `dev`, in every state.
  A `worktree_skew` heartbeat names the divergent worktrees instead of hiding them.
- The running-stack identity for image digests has no default: set `EVAL_ADVANCE_COMPOSE_PROJECT` (eval instances run as `ph-<short>`) or `EVAL_ADVANCE_IMAGE_CONTAINERS`.
  With neither, the daemon alerts and refuses to advance (SP4).
- For N>1 instances (I1/D36), set `EVAL_ADVANCE_INSTANCES` to a JSON/YAML list (one mapping per instance with `instance_id` and `app_state_url`, optionally `compose_project`/`image_containers`).
  The advance happens only when every instance is idle; an unknown verdict for any instance refuses it, and the manifest's image digests are keyed `<instance_id>:<component>`.
- The last-known-good history is bounded to the most recent 50 SHAs (SP5), so an operator rewind only targets a recent recorded good SHA.
- The heartbeat and last-known-good history are the daemon's only writes.
