"""The one shared read/write agent tool over the auth store (#220, T3).

The hunting module's `graph_view` tool is the repeated precedent: one
implementation, the factory binding the ambient seam (here the project id +
the store), the usage contract riding the tool description verbatim, and
fail-open coded results - nothing raises into the turn. Import performs no
I/O (CODING_STANDARD section 6): the default production store is constructed
lazily inside the factory call, never at import.

Trust split: origin is always agent through this tool. Agent writes to the
operator-owned overview or to operator-stamped accounts refuse with the
`operator_immutable` envelope; overview changes arrive only via the operator
seed primitive (`AuthStore.replace_operator_state`, the T4 face).
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from polymerhus.app.auth.store import (
    AuthInvalidError,
    AuthStore,
    DuplicateAuthError,
    DuplicateIdentityError,
    OperatorImmutableError,
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
    "bucket (a credentials file plus the operator-owned overview file). An "
    "account record is one named bundle of credentials, tokens, and Steel "
    "browser-state. The operator section (the overview plus operator-stamped "
    "accounts) is the operator's ground truth and is immutable to you; the "
    "agent section (agent-stamped accounts) is yours to mint and merge. A "
    "technical condition is an optional assertable procedure condition "
    "(`{name, check}`) to verify when a login fails unexpectedly while "
    "following the procedure in the overview. A browser-profile reference is "
    "the minimal durable Steel profile key (`steel: {profile}`) - record only "
    "the key so the next agent rebinds the same profile through its browser "
    "tool, secrets never touching the store. A concrete snapshot is "
    "point-in-time captured request state (`{headers, cookies, params, "
    "captured_at}`) that request-based followers replay exactly. An operator "
    "seed is the operator's wholesale replace of the operator-owned state - "
    "your agent-minted accounts survive it untouched. A procedure label names "
    "the skill procedure that minted or serves an account.\n\n"
    "ACCOUNT IDENTITY - an account is keyed by the credential identity it "
    "authenticates, and the account NAME carries that identity. Name an "
    "account `<email>-<minting_context>`: the credential username, a hyphen, "
    "then the context that minted it, which you assess at write time (for "
    "example `<email>-first_authn_bootstrap` or `<email>-hunting_misauthr`). "
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
    "merges into the known record. Operator-owned paths refuse with "
    "`operator_immutable`. Creating an already-known account name fails with "
    "`duplicate_auth` - reflect, merge, or refresh instead of duplicating. "
    "Creating an account whose credential username (default or any role) "
    "already belongs to another account fails with `duplicate_identity` - add "
    "a role to the existing account, never a second account for the same "
    "identity. "
    "Shape violations fail with `auth_invalid` naming the offending field. A "
    "degraded store fails with `store_unavailable`. Every outcome arrives as "
    "an in-band coded envelope; nothing raises into the turn."
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
            "one token, `overview.notes` is operator-owned and refuses."
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


def build_auth_store_tool(project_id: str | None = None, store: AuthStore | None = None):
    """Build the ONE shared `auth_store` tool bound to `project_id`.

    `project_id` defaults to the control-plane project (`config.PROJECT_ID`,
    the deployment's single project) resolved LAZILY here, so no agent harness
    threads identity and import never touches config/env (CODING_STANDARD §6).
    `store` is the auth seam (default: the production `AuthStore` -
    constructing it performs no I/O; tests inject an explicit-root store).
    The contract rides the tool's description verbatim.
    """
    if project_id is None:
        from polymerhus.app.config import config  # noqa: PLC0415 - lazy, no env at import

        project_id = config.PROJECT_ID
    seam = store if store is not None else AuthStore()

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
            except OperatorImmutableError as exc:
                return {"ok": False, "error": "operator_immutable",
                        "detail": str(exc)}
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
    "build_auth_store_tool",
]
