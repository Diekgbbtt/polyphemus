#!/usr/bin/env python3
"""A light scaffold of the pinned `steel` executable (#395 tests).

The module is two things at once:

- runnable as `steel` (it is copied to a temp `bin/steel`), so the host unit
  and mocked-e2e tiers drive the REAL `steel_exec` gateway against it with no
  docker, no network, and no cloud key;
- importable by tests, through `install()`, which writes the executable,
  points PATH at it, and exposes the recorded calls and the session state.

Fidelity that matters for the assertions:

- the JSON envelopes the `skills/steel-browser/SKILL.md` command families
  document (`sessions`, `start`, `stop`, `navigate`, `snapshot`, `get`,
  `eval`, `fill`/`type`/`setvalue`, `wait`, `batch`, `cookies`, `storage`,
  `scrape`, `profile`);
- the variadic fold: for `fill`/`type`/`setvalue`/`select`/`upload`/`batch`,
  option parsing stops at the first positional, so a flag after the value is
  swallowed into the VALUE exactly as clap does. A mis-encoded command is
  therefore detectable by reading the stored value, which is the D19 defect.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path

# --- state helpers -----------------------------------------------------------


def _state_path() -> Path:
    return Path(os.environ["STEEL_SCAFFOLD_STATE"])


def _load() -> dict:
    path = _state_path()
    if not path.exists():
        return {"sessions": {}}
    return json.loads(path.read_text())


def _save(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=2, sort_keys=True))


def _log_call() -> None:
    log = os.environ.get("STEEL_SCAFFOLD_CALLS")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\n")


def _out(payload: dict, *, code: int = 0) -> None:
    print(json.dumps(payload))
    sys.exit(code)


def _err(message: str, *, code: int = 1) -> None:
    _out({"error": message, "error_code": "internal_error", "success": False}, code=code)


VALUE_FLAGS = {
    "--session": "session",
    "--session-timeout": "session_timeout",
    "--inactivity-timeout": "inactivity_timeout",
    "--profile": "profile",
    "--proxy": "proxy",
    "--api-url": "api_url",
    "--wait-until": "wait_until",
    "--timeout": "timeout",
    "--selector": "selector",
    "--format": "format",
    "--load-state": "load_state",
}
SHORT_VALUE_FLAGS = {"-t": "text", "-u": "url", "-f": "function", "-l": "load_state", "-p": "proxy"}
BOOL_FLAGS = {"--json", "--local", "--stealth", "--update-profile", "-i", "-a", "--all",
              "--bail", "--use-proxy", "--pdf", "--screenshot", "-c", "-s", "-d", "-u"}


def _parse(args: list[str]) -> tuple[dict, list[str]]:
    opts: dict[str, object] = {}
    positional: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in VALUE_FLAGS:
            opts[VALUE_FLAGS[token]] = args[i + 1] if i + 1 < len(args) else ""
            i += 2
            continue
        if token in SHORT_VALUE_FLAGS:
            opts[SHORT_VALUE_FLAGS[token]] = args[i + 1] if i + 1 < len(args) else ""
            i += 2
            continue
        if token in BOOL_FLAGS or token.startswith("-"):
            opts[token] = True
            i += 1
            continue
        positional.append(token)
        i += 1
    return opts, positional


def _variadic(args: list[str]) -> tuple[dict, str, list[str], bool]:
    """Parse a variadic verb: options, one selector, then VALUES.

    Returns (opts, selector, values, boundary_seen). Without a `--` boundary
    every token after the selector is a value, so a trailing flag folds into
    the value, exactly the clap behaviour the D19 guard exists to prevent.
    """
    opts: dict[str, object] = {}
    i = 0
    selector = ""
    while i < len(args):
        token = args[i]
        if token == "--":
            return opts, selector, args[i + 1:], True
        if token in VALUE_FLAGS:
            opts[VALUE_FLAGS[token]] = args[i + 1] if i + 1 < len(args) else ""
            i += 2
            continue
        if token in SHORT_VALUE_FLAGS:
            opts[SHORT_VALUE_FLAGS[token]] = args[i + 1] if i + 1 < len(args) else ""
            i += 2
            continue
        if token.startswith("-") and token not in BOOL_FLAGS:
            opts[token] = True
            i += 1
            continue
        if token in BOOL_FLAGS:
            opts[token] = True
            i += 1
            continue
        selector = token
        remaining = args[i + 1:]
        if remaining and remaining[0] == "--":
            return opts, selector, remaining[1:], True
        return opts, selector, remaining, False
    return opts, selector, [], False


# --- session layer -----------------------------------------------------------


def _ref_css(ref: str) -> str:
    # The scaffold's snapshot maps refs to real CSS elements; the number ref
    # from `snapshot -i` is the text input.
    return "input"


def _title_for(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    known = {
        "example.com": "Example Domain",
        "the-internet.herokuapp.com": "The Internet",
    }
    if host in known:
        return known[host]
    if host.endswith(".target"):
        return "Target"
    return host or "about:blank"


def _session(state: dict, opts: dict, *, required: bool) -> dict | None:
    name = str(opts.get("session") or "default")
    sess = state["sessions"].get(name)
    if sess is None and required:
        _err(f"No session named {name}")
    return sess


def _start(state: dict, opts: dict) -> dict:
    name = str(opts.get("session") or "default")
    existing = state["sessions"].get(name)
    if existing:
        return existing
    requested = int(str(opts.get("session_timeout") or "600000"))
    sess = {
        "id": f"scaffold-{len(state['sessions']) + 1}",
        "mode": "local" if opts.get("--local") else "cloud",
        "sessionTimeoutMs": requested,
        "remainingMs": requested - 100,
        "url": "about:blank",
        "title": "",
        "values": {},
        "cookies": [{"name": "scaffold_session", "value": "1", "domain": "scaffold.test"}],
        "storage": {},
    }
    state["sessions"][name] = sess
    return sess


def _receipt(sess: dict, name: str) -> dict:
    return {
        "data": {
            "connectUrl": "ws://steel-scaffold/",
            "id": sess["id"],
            "inactivityTimeoutMs": 120000,
            "liveUrl": "http://steel-scaffold/",
            "mode": sess["mode"],
            "name": name,
            "remainingMs": sess["remainingMs"],
        },
        "success": True,
    }


# --- dispatch ----------------------------------------------------------------


def _browser(args: list[str], state: dict) -> None:
    if not args:
        _err("a browser subcommand is required", code=2)
    verb, rest = args[0], args[1:]

    if verb == "sessions":
        _out({"data": [
            {"id": s["id"], "mode": s["mode"], "name": n, "status": "live",
             "viewerUrl": "http://steel-scaffold/"}
            for n, s in sorted(state["sessions"].items())
        ], "success": True})

    if verb == "start":
        opts, _ = _parse(rest)
        name = str(opts.get("session") or "default")
        _out(_receipt(_start(state, opts), name))

    if verb == "stop":
        opts, _ = _parse(rest)
        if opts.get("-a") or opts.get("--all"):
            stopped = sorted(state["sessions"])
            state["sessions"] = {}
        else:
            name = str(opts.get("session") or "default")
            stopped = [name] if state["sessions"].pop(name, None) else []
        _out({"data": {"stoppedSessions": stopped}, "success": True})

    if verb in {"navigate", "open", "goto"}:
        opts, positional = _parse(rest)
        if not positional:
            _err("a URL is required", code=2)
        sess = _session(state, opts, required=True)
        url = positional[0]
        sess["url"] = url
        sess["title"] = _title_for(url)
        _out({"data": {"title": sess["title"], "url": url}, "success": True})

    if verb in {"fill", "type", "setvalue", "select", "upload"}:
        opts, selector, values, boundary = _variadic(rest)
        sess = _session(state, opts, required=True)
        value = " ".join(values)
        sess["values"][selector] = value
        if selector.startswith("@"):  # a ref resolves to the CSS element
            sess["values"][_ref_css(selector)] = value
        key = {"fill": "filled", "type": "typed", "setvalue": "set",
               "select": "selected", "upload": "uploaded"}[verb]
        _out({"data": {key: selector, "boundary": boundary}, "success": True})

    if verb == "snapshot":
        opts, _ = _parse(rest)
        _session(state, opts, required=True)
        tree = (
            "- generic\n"
            "  - textbox \"Username\" [ref=e4]\n"
            "  - textbox \"Password\" [ref=e6]\n"
            "  - spinbutton \"Number\" [ref=e7]\n"
            "  - button \"Submit\" [ref=e9]"
        )
        _out({"data": tree, "success": True})

    if verb == "get":
        opts, positional = _parse(rest)
        sess = _session(state, opts, required=True)
        what = positional[0] if positional else ""
        arg = positional[1] if len(positional) > 1 else ""
        if what == "title":
            _out({"data": sess["title"], "success": True})
        if what == "url":
            _out({"data": sess["url"], "success": True})
        if what == "value":
            _out({"data": {"value": sess["values"].get(arg)}, "success": True})
        if what == "count":
            _out({"data": {"count": 1 if arg in sess["values"] else 0}, "success": True})
        if what == "text":
            _out({"data": {"text": sess["title"]}, "success": True})
        _err(f"unknown get target: {what}", code=2)

    if verb == "content":
        opts, _ = _parse(rest)
        sess = _session(state, opts, required=True)
        _out({"data": f"<html><head><title>{sess['title']}</title></head></html>",
              "success": True})

    if verb == "eval":
        opts, positional = _parse(rest)
        sess = _session(state, opts, required=True)
        expr = positional[0] if positional else ""
        if "location.href" in expr:
            result: object = sess["url"]
        elif "document.title" in expr:
            result = sess["title"]
        elif "value" in expr:
            result = next(iter(sess["values"].values()), None)
        else:
            result = None
        _out({"data": result, "success": True})

    if verb == "wait":
        opts, _ = _parse(rest)
        _session(state, opts, required=True)
        _out({"data": {"matched": True}, "success": True})

    if verb in {"cookies", "storage"}:
        opts, _ = _parse(rest)
        sess = _session(state, opts, required=True)
        if verb == "cookies":
            _out({"data": sess["cookies"], "success": True})
        _out({"data": sess["storage"], "success": True})

    if verb in {"click", "dblclick", "press", "hover", "focus", "check", "uncheck",
                "clear", "selectall", "scroll", "scrollintoview", "drag", "back",
                "forward", "reload"}:
        opts, positional = _parse(rest)
        _session(state, opts, required=True)
        _out({"data": {"action": verb, "target": positional[0] if positional else ""},
              "success": True})

    if verb == "batch":
        opts, _selector, commands, _boundary = _variadic(rest)
        _session(state, opts, required=True)
        parent_name = str(opts.get("session") or "default")
        results = []
        failed = False
        for command in commands:
            parts = shlex.split(command)
            if parts and "--session" not in parts:
                parts = [parts[0], "--session", parent_name, *parts[1:]]
            try:
                data = _run_browser_subcommand(parts, state)
                results.append({"command": command, "data": data, "success": True})
            except _CommandError as exc:
                failed = True
                results.append({"command": command, "error": str(exc), "success": False})
        print(json.dumps({"data": {"results": results}, "success": not failed}))
        if failed:
            print(json.dumps({"error": "One or more batch commands failed"}))
            sys.exit(1)
        sys.exit(0)

    _err(f"unknown browser subcommand: {verb}", code=2)


class _CommandError(Exception):
    pass


def _run_browser_subcommand(parts: list[str], state: dict) -> object:
    """Run one batch element, capturing its `data` instead of printing."""
    if not parts:
        raise _CommandError("empty command")
    verb, rest = parts[0], parts[1:]
    captured: dict[str, object] = {}

    original_out = globals()["_out"]

    def capture(payload: dict, *, code: int = 0) -> None:
        captured["payload"] = payload
        raise _CommandError(str(payload.get("error") or f"{verb} failed"))

    if verb in {"fill", "type", "setvalue", "select", "upload"}:
        opts, selector, values, _boundary = _variadic(rest)
        sess = _session(state, opts, required=True)
        sess["values"][selector] = " ".join(values)
        if selector.startswith("@"):
            sess["values"][_ref_css(selector)] = " ".join(values)
        return {"filled": selector}
    if verb == "snapshot":
        opts, _ = _parse(rest)
        _session(state, opts, required=True)
        return "- generic\n  - spinbutton \"Number\" [ref=e7]"
    globals()["_out"] = capture
    try:
        _browser([verb, *rest], state)
    except _CommandError as exc:
        payload = captured.get("payload")
        if payload is not None and payload.get("success") is not False:
            return payload.get("data")
        raise exc
    finally:
        globals()["_out"] = original_out
    raise _CommandError(f"{verb} produced no result")


def _strip_leading_globals(argv: list[str]) -> tuple[list[str], list[str]]:
    """Pull the global flags the gateway injects ahead of the subcommand."""
    leading: list[str] = []
    while argv:
        token = argv[0]
        if token in {"--json", "--local"}:
            leading.append(argv.pop(0))
            continue
        if token == "--api-url":
            argv = argv[2:]
            continue
        break
    return leading, argv


def _top(argv: list[str], state: dict) -> None:
    if not argv:
        _err("a command is required", code=2)
    leading, argv = _strip_leading_globals(list(argv))
    if not argv:
        _err("a command is required", code=2)
    command, rest = argv[0], argv[1:]
    if command == "--version":
        print("steel 0.5.0-preview.6")
        sys.exit(0)
    if command == "browser":
        if rest:
            rest = [rest[0], *leading, *rest[1:]]
        _browser(rest, state)
    if command == "scrape":
        _, positional = _parse(rest)
        url = positional[0] if positional else ""
        _out({"data": {
            "content": {"markdown": f"# {_title_for(url)}\n\nScaffold content."},
            "links": [],
            "metadata": {"title": _title_for(url), "statusCode": 200},
        }, "success": True})
    if command == "profile":
        _out({"data": [], "success": True})
    _err(f"unknown command: {command}", code=2)


def main() -> None:
    _log_call()
    state = _load()
    try:
        _top(sys.argv[1:], state)
    finally:
        _save(state)


# --- pytest helper -----------------------------------------------------------


def install(tmp_path: Path, monkeypatch) -> dict:
    """Install the scaffold as `steel` on PATH; return its handles.

    The returned dict carries `bindir`, `state` (the JSON state path), and
    `calls` (the recorded argv log). Environment variables are set through
    `monkeypatch`, so they revert after the test.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = Path(__file__).resolve()
    program = bindir / "steel"
    program.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    state = tmp_path / "state.json"
    calls = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("STEEL_SCAFFOLD_STATE", str(state))
    monkeypatch.setenv("STEEL_SCAFFOLD_CALLS", str(calls))
    return {"bindir": bindir, "state": state, "calls": calls}


def read_state(handle: dict) -> dict:
    path: Path = handle["state"]
    if not path.exists():
        return {"sessions": {}}
    return json.loads(path.read_text())


def calls(handle: dict) -> list[list[str]]:
    path: Path = handle["calls"]
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


if __name__ == "__main__":
    main()
