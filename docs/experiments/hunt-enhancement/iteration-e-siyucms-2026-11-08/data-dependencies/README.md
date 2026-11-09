# Iteration E data dependencies - the Steel session alignment

The live siyucms data dependency is at `/root/eval-dd/data/siyucms/`.
The files below hold the operational state; the copies in this directory are
sanitised so the repository never carries target secrets.

## Live files

| Path | Pre-iteration backup |
|---|---|
| `/root/eval-dd/data/siyucms/auth/overview.yaml` | `overview.yaml.pre-iteration-e` if edited |
| `/root/eval-dd/data/siyucms/auth/credentials.yaml` | `credentials.yaml.pre-iteration-e` |
| `/root/eval-dd/data/siyucms/skills/authn/SKILL.md` | `SKILL.md.pre-iteration-e` |

`overview.yaml` already carried the designed oracle
`auth_probe.url: /index.php/admin/Index/index.html`.
It was not changed.

## What changed

### Credentials

The admin account moved from the retired steel profile to the designed
decoupled browser context:

```yaml
admin-first_authn_bootstrap:
  browser_context:
    ref: steel-auth-siyucms-web-admin-first-authn-bootstrap
```

`steel.state: e2e-siyucms` is gone.
The admin account is asserted `valid` because the operator preflight mints a
fresh session after the single target bring-up; the auth gateway re-validates
the oracle in the one browser tool.
Each account is one session.
The admin account carries `role: super_administrator`,
`root_url: /index.php/admin/Index/index.html`, and the same `auth_probe`.
The member account carries `role: member`,
`root_url: /index.php/index/user/index.html`, and the same `auth_probe`.
The member account starts `not_valid` until the preflight mints its decoupled
browser context; the preflight writes the reference and sets it `valid`.
An account with no `role` starts at `/`; an account with no `auth_probe` uses
its root URL as the oracle.
The preflight mints every credential-bearing account, not only the admin.

The admin snapshot was cleaned to the siyucms `PHPSESSID` only.
The C.a target substitution had left `cf_clearance`, `PrestaShop-*`, and
`thinkphp_show_page_trace` cookies in the snapshot.
Those cookies belong to other targets and never to siyucms.

The `browser_context.ref` is a safe store key.
The live run derives the same key from the project id and the account name;
the stored value is the readable, project-scoped reference.

### Authn skill

The nine stale live-session overlays are gone.
They named operator-created `steel-crawl-*` sessions from earlier E2E runs.
The skill now opens with one browser-session section:

- the auth gateway and the crawl mount the account's decoupled context
  through the one `browser` tool;
- the model never passes a session name, a worker URL, or a profile;
- `browser(command="end", persist_context=true)` is the only state write;
- the oracle is the only pass signal.

The sign-in procedures stay unchanged and request-replayable.
The skill's description now says the sign-in procedures are request-based and
the gateway still uses the one browser tool for the oracle and the context.

## The first work item

The setup records `steel-browser-sessions` as its first `work_items` entry
with `status: complete`.
The orchestrator gate refuses a new trial while a required work item is
incomplete, so the alignment is a precondition, not a note.

## Sanitised copies

- `credentials.template.yaml` - the account shape with the browser-context
  reference and every secret redacted.
- `authn-SKILL.md` - the aligned skill. It cites secret names only.

The live files remain the source of truth for the run.
