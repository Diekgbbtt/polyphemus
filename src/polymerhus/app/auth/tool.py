"""The one shared read/write agent tool over the auth store (#220, T3).

The hunting module's `graph_view` tool is the repeated precedent: one
implementation, the factory binding the ambient seam (here the project id +
the store), the usage contract riding the tool description verbatim, and
fail-open coded results - nothing raises into the turn. Import performs no
I/O (CODING_STANDARD section 6): the default production store is constructed
lazily inside the factory call, never at import.

Origin is always agent through this tool. Both sections are writable (D220-12
retires the trust-boundary refusal): an agent write merges into the overview
and into operator-stamped accounts alike, the stored `origin` stamp is
preserved as provenance, and `updated_at` refreshes. The operator seed
primitive (`AuthStore.replace_operator_state`, the T4 face) remains the
operator's wholesale replace of the operator section.

`read_only=True` builds the analysis-side READ-ONLY form of the SAME tool
(#364, `docs/design/analysis-auth-store-view-364-adr.md`): the same name over
the same store, an argument surface with no write field at all, and a read
that returns the REDACTED projection (names, shapes, and statuses - never a
secret value). The rationale for one tool and one name is the census: the
ticket's measurement counts anonymous calls by tool name, so the analysis
read must be the name the census already reports.
"""
from __future__ import annotations

import copy
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from polymerhus.app.auth.store import (
    AuthInvalidError,
    AuthStore,
    DuplicateAuthError,
    DuplicateIdentityError,
    StoreUnavailableError,
)

# The single usage contract, rendered verbatim into the tool description at
# every binding so no agent receives a divergent contract (the
# `GRAPH_VIEW_CONTRACT` precedent in `attack/hunting/graph_view_tool.py`).
AUTH_STORE_CONTRACT = (
    "Read and write the run's per-project auth store: the one shared bucket "
    "holding every credential the agents may reuse, so sibling agents "
    "authenticate from known state instead of re-deriving access from scratch.\n\n"
    "DOMAIN MODEL - an auth store is the per-project `data/<project_id>/auth/` "
    "bucket (a credentials file plus the login-mechanism overview file). An "
    "account record is one named bundle of credentials, tokens, and Steel "
    "browser-state. The operator section (the overview plus operator-stamped "
    "accounts) is the operator's ground truth and is WRITABLE to you: you "
    "merge into it (tokens, status, snapshot, steel, notes), and the stored "
    "`origin: operator` stamp stays as provenance; the agent section "
    "(agent-stamped accounts) is yours to mint. A "
    "technical condition is an optional assertable procedure condition "
    "(`{name, check}`) to verify when a login fails unexpectedly while "
    "following the procedure in the overview. A browser-profile reference is "
    "the minimal durable Steel profile key (`steel: {profile}`) - record only "
    "the key so the next agent rebinds the same profile through its browser "
    "tool, secrets never touching the store. A concrete snapshot is "
    "point-in-time captured request state (`{headers, cookies, params, "
    "captured_at}`) that request-based followers replay exactly. An operator "
    "seed is the operator's wholesale replace of the operator section - your "
    "agent-minted accounts survive it untouched, while your edits inside a "
    "seeded account are replaced by the seed. A procedure label names "
    "the skill procedure that minted or serves an account.\n\n"
    "ACCOUNT IDENTITY - an account is keyed by the credential identity it "
    "authenticates, and the account NAME carries that identity. Name an "
    "account `<username>-<minting_context>`: the credential username with its "
    "email location suffix stripped (`diegogobbetti69@gmail.com` -> "
    "`diegogobbetti69`), a hyphen, then the context that minted it, which you "
    "assess at write time (for example `diegogobbetti69-first_authn_bootstrap` "
    "or `<username>-hunting_misauthr`). The tool strips the location suffix "
    "systematically, so a name written in the full-email form addresses the "
    "same record; keep the dot-free form canonical. "
    "The minting context is the run or flow that created the account, never "
    "the procedure: sign-up and sign-in in one bootstrap share one name, so "
    "the second write collides on `duplicate_auth` and you merge instead of "
    "forking. One credential identity is ONE account per minting context: the "
    "identity is the default `credentials.username` plus every "
    "`roles.*.username`, so adding access for a known identity is a new ROLE on "
    "the existing account (`accounts.<name>.roles.<role>`), never a second "
    "account; `procedure` labels which flow serves it and is not an identity "
    "axis.\n\n"
    "SCHEMA - overview (all optional): `login_endpoint`, `required_headers`, "
    "`mechanism`, `defences`, `fingerprinting`, `technical_conditions` "
    "(optional list of `{name, check}`, absent by default), `notes`. Account "
    "record: `origin` (operator or agent, stamped server-side), optional "
    "`procedure` label, optional `credentials` (`username`, `password`, "
    "`login_url` plus optional `domain` and form selectors), optional `roles` "
    "(role name -> credential set) with `default_role` naming a configured "
    "role, optional "
    "`tokens` (each `{value, location: cookie | header | storage, target?, "
    "expiry?}`), optional `steel` (`{profile}` key only), optional concrete "
    "`snapshot` (`{headers, cookies, params, captured_at}`), optional "
    "`notes`, the loop-asserted validity fact `status` (`valid` | `not_valid`, "
    "absent until asserted - any other value refuses with `auth_invalid`), "
    "and the server-stamped recency fact `updated_at` (refreshed on every "
    "write and seed; a value you supply is overwritten, never trusted). "
    "Full state shape: `{\"overview\": ..., \"accounts\": ...}`.\n\n"
    "READ/WRITE RULES - reads are field-arbitrary: an empty path returns the "
    "full state, a dot-path (`accounts.alice`, `accounts.alice.tokens.session`, "
    "`overview.notes`) projects that field, and a missing path is a valid "
    "empty (`{}`), never an error. Writes are single-field merges: one field "
    "per call, siblings untouched, and a null value removes an optional "
    "field. Creating an account writes its record mapping at "
    "`accounts.<name>`; writing deeper (`accounts.<name>.tokens.session`) "
    "merges into the known record, operator-stamped or agent-stamped alike. "
    "Creating an already-known account name fails with "
    "`duplicate_auth` - reflect, merge, or refresh instead of duplicating. "
    "Creating an account whose credential username (default or any role) "
    "already belongs to another account fails with `duplicate_identity` - add "
    "a role to the existing account, never a second account for the same "
    "identity. "
    "Shape violations fail with `auth_invalid` naming the offending field. A "
    "degraded store fails with `store_unavailable`. Every outcome arrives as "
    "an in-band coded envelope; nothing raises into the turn."
)

# The redaction marker the read-only view substitutes for every secret value
# (#364 D364-2). One literal, shared by the redactor and the contract below, so
# the model is told exactly what it will read.
REDACTED = "<redacted>"

# The READ-ONLY contract (the analysis-side view, #364). Deliberately NOT the
# read/write contract above: a binding that cannot write must not teach a write
# path, and the redaction rule is load-bearing usage information (what the model
# may conclude from what it reads).
AUTH_STORE_READ_CONTRACT = (
    "Read the run's per-project auth store in its READ-ONLY form: the one "
    "shared bucket of recorded session material (the login-mechanism overview "
    "plus the account records), so a request shape can be typed against what "
    "was actually recorded instead of inferred from responses.\n\n"
    "DOMAIN MODEL - the store is the per-project `data/<project_id>/auth/` "
    "bucket. An overview is the login-mechanism header: `login_endpoint`, "
    "`required_headers` (header NAMES), `mechanism`, `defences`, "
    "`fingerprinting`, `technical_conditions` (a list of `{name, check}` "
    "pairs), `notes`. An account record is one named bundle: `origin` "
    "(operator or agent), an optional `procedure` label, optional "
    "`credentials` (`username`, `login_url`, `domain`, form selectors), "
    "optional `roles` (role -> credential set) with `default_role`, optional "
    "`tokens` (each `{value, location: cookie | header | storage, target?, "
    "expiry?}`), an optional `steel` browser-profile reference, an optional "
    "concrete `snapshot` (`{headers, cookies, params, captured_at}` - the "
    "point-in-time request state a follower replays), `notes`, the "
    "loop-asserted `status` (`valid` | `not_valid`, absent until asserted), "
    "and the server-stamped `updated_at`.\n\n"
    "REDACTION - this view carries NAMES, SHAPES, AND STATUSES, NEVER SECRET "
    "VALUES: every password, every token value, and every snapshot cookie, "
    "header, or param value reads as the literal " + REDACTED + " marker. Type "
    "the request shape FROM the names, the locations, and the statuses - the "
    "cookie and header NAMES, a token's `location` / `target` / `expiry`, the "
    "account identity, the login endpoint. Never ask for a value, never try to "
    "reconstruct or replay the material, and never quote a credential or a "
    "session value into a proposal.\n\n"
    "READ RULES - reads are field-arbitrary: an empty path returns the full "
    "redacted state (`{\"command\": \"read\", \"path\": \"\"}`), a dot-path "
    "(`overview`, `accounts.alice`, `accounts.alice.tokens`) projects that "
    "field, and a missing path is a valid empty (`{}`), never an error. The "
    "redaction is applied BEFORE the projection, so a narrow path cannot "
    "address a raw value either.\n\n"
    "NO WRITE RULES - this binding is READ-ONLY (D223-5): the analysis turns "
    "read the store, they never write it and never authenticate from it. Every "
    "command but `read` refuses with `auth_readonly`; a store that cannot be "
    "read degrades fail-open to an empty value, and a read that itself fails "
    "refuses `store_unavailable`. Every outcome arrives as an in-band coded "
    "envelope; nothing raises into the turn."
)


# The tool args: each parameter documents its own role with the optimal
# request shapes (whole-state reads for orientation, narrow path reads per
# turn, single-field writes for merges), so an agent derives them unprompted.
class AuthStoreArgs(BaseModel):
    """The `auth_store` args (bound project needs no identity parameter)."""

    command: str = Field(
        description=(
            "read or write. `read` projects state (empty path for the "
            "full state); `write` merges one field (the value rides "
            "`value`)."
        )
    )
    path: str = Field(
        default="",
        description=(
            "Dot-path selecting the field. On read an empty path returns "
            "the full state for orientation (`{\"command\": \"read\", "
            "\"path\": \"\"}`), while a narrow path keeps the turn small "
            "and precise (`overview` for the login-mechanism header, "
            "`accounts.alice` for one account, "
            "`accounts.alice.tokens.session` for one token, "
            "`overview.technical_conditions` for the procedure "
            "conditions). On write it names the single field to merge: "
            "`accounts.bob` with a record mapping creates the account, "
            "`accounts.alice.tokens.session` with a token entry merges "
            "one token, `overview.notes` merges into the login-mechanism "
            "header."
        ),
    )
    value: Any = Field(
        default=None,
        description=(
            "Write only, ignored on read: the new value at `path`. "
            "Single-field writes for merges (one token entry, one note, "
            "one snapshot - never a whole bucket). Null removes an "
            "optional field (`{\"command\": \"write\", \"path\": "
            "\"accounts.alice.notes\", \"value\": null}` deletes the "
            "note). Creating vs merging: a record mapping at "
            "`accounts.<name>` creates (a known name fails with "
            "`duplicate_auth`); a value at a deeper path merges into the "
            "stored record."
        ),
    )


_ARGS_SCHEMA = AuthStoreArgs


class AuthStoreReadArgs(BaseModel):
    """The READ-ONLY `auth_store` args (#364 D364-3): the projection path and
    the read verb alone. `value` is deliberately absent, so a write-shaped
    payload has no field to ride - the write path is not expressible from this
    binding, not merely refused at run time."""

    command: str = Field(
        default="read",
        description=(
            "`read` (the only available command). This binding is READ-ONLY: "
            "any other command refuses with `auth_readonly` - the analysis "
            "turns read the store, never write it (D223-5)."
        ),
    )
    path: str = Field(
        default="",
        description=(
            "Dot-path selecting the field to project. An empty path returns "
            "the full redacted state (`{\"command\": \"read\", \"path\": \"\"}`) "
            "for orientation, while a narrow path keeps the turn small and "
            "precise (`overview` for the login-mechanism header, "
            "`accounts.alice` for one account, `accounts.alice.tokens` for its "
            "token names, locations, and statuses). Secret values read as the "
            "redaction marker, never as the value - a narrow path cannot reach "
            "one either."
        ),
    )


def _redact_password(credentials: Any) -> None:
    """In-place redaction of one credential set's password (malformed shapes
    pass through untouched)."""
    if isinstance(credentials, dict) and "password" in credentials:
        credentials["password"] = REDACTED


def _redact_values(mapping: Any) -> None:
    """In-place redaction of a name -> value map's values (the snapshot's header
    and param maps; the names are the request shape and stay)."""
    if isinstance(mapping, dict):
        for key in list(mapping):
            mapping[key] = REDACTED


def _redact_account(record: Any) -> None:
    """In-place redaction of ONE account record: the password of the default
    credential set and of every role set, every token's `value`, and the
    snapshot's header / param / cookie values. Identity (`username`), the
    request shape (`login_url`, the selectors, a token's `location` / `target` /
    `expiry`, a cookie's `name`), and the server-stamped facts are untouched."""
    if not isinstance(record, dict):
        return
    _redact_password(record.get("credentials"))
    roles = record.get("roles")
    if isinstance(roles, dict):
        for role_set in roles.values():
            _redact_password(role_set)
    tokens = record.get("tokens")
    if isinstance(tokens, dict):
        for entry in tokens.values():
            if isinstance(entry, dict) and "value" in entry:
                entry["value"] = REDACTED
    snapshot = record.get("snapshot")
    if isinstance(snapshot, dict):
        _redact_values(snapshot.get("headers"))
        _redact_values(snapshot.get("params"))
        cookies = snapshot.get("cookies")
        if isinstance(cookies, list):
            for cookie in cookies:
                if isinstance(cookie, dict) and "value" in cookie:
                    cookie["value"] = REDACTED


def redact_auth_state(state: Any) -> dict:
    """The read-only view's projection of the bucket state (#364 D364-2): the
    shape, every NAME, and every server-stamped fact stay; every secret VALUE
    becomes the `REDACTED` marker.

    Applied to the FULL state BEFORE the dotted projection, so a narrow read
    cannot address a raw leaf (`accounts.<name>.credentials.password` reads the
    marker, not the password). The redaction is a VIEW over a deep copy: the
    store on disk keeps the real material for the gateway and the
    job-specialised agents, who replay it (D223-19). A malformed record passes
    through rather than raising - the store's own read is the fail-open
    boundary, and this view never raises into a turn."""
    out = copy.deepcopy(state) if isinstance(state, dict) else {}
    accounts = out.get("accounts")
    if isinstance(accounts, dict):
        for record in accounts.values():
            _redact_account(record)
    return out


def build_auth_store_tool(project_id: str | None = None, store: AuthStore | None = None,
                          *, read_only: bool = False):
    """Build the ONE shared `auth_store` tool bound to `project_id`.

    `project_id` defaults to the control-plane project (`config.PROJECT_ID`,
    the deployment's single project) resolved LAZILY here, so no agent harness
    threads identity and import never touches config/env (CODING_STANDARD §6).
    `store` is the auth seam (default: the production `AuthStore` -
    constructing it performs no I/O; tests inject an explicit-root store).
    The contract rides the tool's description verbatim.

    `read_only=True` (#364) builds the analysis-side form: the SAME tool name
    and the same bound handle, the read-only args schema (no write field), the
    redacted read, and `auth_readonly` for every command but `read` - refused
    before the store is touched, so no write path is reachable from this
    binding.
    """
    if project_id is None:
        from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import

        project_id = config.PROJECT_ID
    seam = store if store is not None else AuthStore()

    if read_only:
        @tool(args_schema=AuthStoreReadArgs)
        def auth_store(command: str = "read", path: str = "") -> dict:
            """Placeholder - the read-only contract is assigned below."""
            if command != "read":
                return {"ok": False, "error": "auth_readonly",
                        "detail": f"auth_readonly: this binding is read-only; "
                                  f"{command!r} is not available - read the "
                                  f"store, never write it"}
            at = path or ""
            try:
                # Redact the WHOLE state first, project second: the projection
                # is the store's own (#247 name canonicalisation included), so
                # no second copy of that rule exists here.
                state = redact_auth_state(seam.read(project_id, ""))
                return {"ok": True, "command": "read", "path": at,
                        "value": AuthStore._project(state, at)}
            except Exception as exc:  # noqa: BLE001 - fail-open, never a raise
                return {"ok": False, "error": "store_unavailable",
                        "detail": f"store_unavailable: {exc}"}

        tool_obj = auth_store
        if hasattr(tool_obj, "description"):
            tool_obj.description = AUTH_STORE_READ_CONTRACT
        return tool_obj

    @tool(args_schema=_ARGS_SCHEMA)
    def auth_store(command: str, path: str = "", value: Any = None) -> dict:
        """Placeholder - the real contract is assigned below (the `@tool`
        decorator reads the docstring at decoration time, so the interpolated
        `AUTH_STORE_CONTRACT` is set on the returned tool explicitly)."""
        at = path or ""
        if command == "read":
            try:
                return {"ok": True, "command": "read", "path": at,
                        "value": seam.read(project_id, at)}
            except Exception as exc:  # noqa: BLE001 - fail-open, never a raise
                return {"ok": False, "error": "store_unavailable",
                        "detail": f"store_unavailable: {exc}"}
        if command == "write":
            try:
                seam.write(project_id, at, value, origin="agent")
            except DuplicateAuthError as exc:
                return {"ok": False, "error": "duplicate_auth",
                        "detail": str(exc)}
            except DuplicateIdentityError as exc:
                return {"ok": False, "error": "duplicate_identity",
                        "detail": str(exc)}
            except AuthInvalidError as exc:
                return {"ok": False, "error": "auth_invalid",
                        "detail": str(exc)}
            except StoreUnavailableError as exc:
                return {"ok": False, "error": "store_unavailable",
                        "detail": str(exc)}
            except Exception as exc:  # noqa: BLE001 - fail-open, never a raise
                return {"ok": False, "error": "store_unavailable",
                        "detail": f"store_unavailable: {exc}"}
            # The envelope echoes the REQUEST value, not the stored record -
            # the store keeps its own server stamp (`updated_at`), so a read
            # back is the only view of what landed.
            return {"ok": True, "command": "write", "path": at, "value": value}
        return {"ok": False, "error": "auth_invalid",
                "detail": 'auth_invalid: command must be "read" or "write"'}

    # The `@tool` decorator snapshots the docstring at decoration; assign the
    # interpolated contract as the description so every binding carries it.
    tool_obj = auth_store
    if hasattr(tool_obj, "description"):
        tool_obj.description = AUTH_STORE_CONTRACT
    return tool_obj


__all__ = [
    "AUTH_STORE_CONTRACT",
    "AUTH_STORE_READ_CONTRACT",
    "AuthStoreReadArgs",
    "REDACTED",
    "build_auth_store_tool",
    "redact_auth_state",
]
