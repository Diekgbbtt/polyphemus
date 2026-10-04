# ADR: the Kali MCP exec surface must not block the server - async tool bodies and a client read timeout above the command bound

*Status: RATIFIED (2026-10-04). New record. It supersedes no earlier decision; it corrects the implicit assumption that the FastMCP tool bodies may be plain sync functions.*

## Context

A live hunting run surfaced a burst of `exec_failed` results on the Kali MCP `execute_command` tool: `{"ok": false, "error": "exec_failed", "detail": "unhandled errors in a TaskGroup (1 sub-exception)"}`.
The underlying exception was an `httpx.ReadTimeout` inside `mcp.client.streamable_http`, and the MCP session then failed to terminate.

The reproduction was exhaustive:

- A long command on the Kali MCP server stalls **every** other request on that server.
  A `sleep 150` call and a concurrent `echo hello` call both returned after ~210-225s; the trivial command waited for the long one.
- The cause is FastMCP 2.14.7 `FunctionTool.run`: it invokes a **sync** tool body directly on the event loop (`TypeAdapter.validate_python(arguments)`), so a sync `execute_command` running `subprocess.run(..., timeout=300)` blocks the whole asyncio loop.
- The MCP client's streamable-HTTP read timeout defaulted to **300s**, exactly equal to the server's own `EXEC_TIMEOUT_S` (300s).
  A command that ran to its bound raced the client: the client gave up at 300s just as the server returned, raising `ReadTimeout` and tearing down the session.
- The failure was triggered by a hunter probe without a `--max-time` bound (`curl` to a target path that hangs). Once the server was stalled, every concurrent exec call (including trivial ones) timed out in the same window.

## Decision

### 1. Every Kali MCP tool body is `async def`; blocking work moves to a worker thread

`kali/mcp_server.py` defines `execute_command`, `search_http_history`, `get_http_artifact`, `replay_http_request`, `proxy_status` and `steel_exec` as `async def`.
Each body delegates its blocking implementation through one helper, `_offload`, which calls `anyio.to_thread.run_sync`.
FastMCP awaits an async body instead of calling it inline, so one long command no longer stalls the server and concurrent requests keep flowing.

The native primitives are used: FastMCP's own async-tool support and `anyio`, the async runtime FastMCP already runs on.

### 2. The client read timeout must exceed the server's command bound

The MCP client connection sets `sse_read_timeout` to `EXEC_TIMEOUT_S + 60` (langchain-mcp-adapters passes it to `httpx.Timeout(read=...)`).
The client must never give up while the server is still legitimately running a command.
The margin covers a per-call `timeout_s` the caller passes.

### 3. The client re-handshakes once on a broken session

`recon/domain/pod.py::default_exec_fn` retries its MCP invocation once when the call raises a transport error.
A tool's own failure never raises (it rides the result), so a raised error means a broken session; the retry builds a fresh client and session, so one poisoned session does not surface as an `exec_failed`.
The retry is logged.

### 4. Regression guard

`tests/kali/test_http_history_mcp_tools.py::test_tools_are_async_so_a_long_command_never_blocks_the_server` asserts every tool body is a coroutine function, so a future revert to a sync body fails the suite.

## Alignment

`kali/**` is bind-mounted read-only into the running Kali container, so the fix takes effect with `docker restart kali` (the eval environment's alignment action for `kali/**`, `eval-environment-version-pinning-adr.md`).
No image rebuild is required.
