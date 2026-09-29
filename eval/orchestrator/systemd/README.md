# Install: the eval artifact store sync

One systemd unit per `PolyphemusInstance` runs a strictly one-way `lsyncd`
(inotify -> rsync) that streams the instance data root into the artifact store's
secondary live mirror, `<store>/<instance_id>/live/` (D7/D12).
The store is a sink, never an authority: no write path exists from the store
back into the instance data root, and the unit template renders only a source
(the data root) and a target (under the store).
The authoritative record is the self-contained per-trial tree the orchestrator
materializes with `python -m orchestrator store materialize`.

## Files

The config and unit are not committed per instance; `store render-sync`
generates them, one pair per instance, into `<store>/_sync/` by default:

- `eval-store-<instance_id>.conf` - the `lsyncd` configuration.
- `eval-store-<instance_id>.service` - the systemd unit.

## Install

1. Render the configs and units (from the checkout's `eval/` directory so
   `orchestrator` is importable):

   ```sh
   PYTHONPATH=eval python3 -m orchestrator store render-sync <setup.yaml>
   ```

2. Inspect the plan first, if you like; `--dry-run` prints it and writes nothing:

   ```sh
   PYTHONPATH=eval python3 -m orchestrator store render-sync <setup.yaml> --dry-run
   ```

3. Install and start one unit per instance:

   ```sh
   install -m 0644 <store>/_sync/eval-store-<instance_id>.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now eval-store-<instance_id>
   systemctl status eval-store-<instance_id>
   ```

## One-way guarantee

- The generated `sync` block always names the instance data root as `source` and
  the store's live directory as `target`; no rule can name the store as a source.
- `delete = false` keeps the mirror append-only, so a source deletion never
  removes a store copy.
- The materializer reads the instance data root and writes only under the store
  root (every write is guarded); it never mutates the live instance.

## Out of scope

Retention and pruning of the store are deliberately not implemented here.
The store grows for the life of an evaluation; an operator prunes it.
