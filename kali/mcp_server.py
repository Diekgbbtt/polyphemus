"""fastmcp execution server for the reused Kali image.
Exposes execute_command + steel_exec over native HTTP at /mcp; per-session workdir isolation;
ANSI-stripped output; PATH primed for the ProjectDiscovery + gap tools.
No scope enforcement (MVP)."""
import json, os, re, shlex, subprocess, tempfile, time
from fastmcp import FastMCP

os.environ["PATH"] = ":".join([
    "/opt/localbin", "/root/go/bin", "/opt/venv/bin", "/usr/local/go/bin", os.environ.get("PATH", ""),
])

mcp = FastMCP("kali-exec")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_STEEL_TOKEN = re.compile(r"\bsteel\b")
_STEEL_VERSION_PIN = "0.4.4"
_START_SHAPE = re.compile(r"\bbrowser\s+start\b")
_SESSION_FLAG = re.compile(r"--session[= ]+(?:\"([^\"]+)\"|'([^']+)'|(\S+))")
_STEEL_WAIT = re.compile(r"(?<!\S)--timeout[= ]+(\d+)")
_CATALOGUE_TIMEOUT_S = 30
_VERSION_TIMEOUT_S = 15
_SCRIPT_RUNNERS = {"sh": "sh", "py": "python3"}
# Every variadic verb the pinned CLI exposes (`<--help>`): `fill`/`type`/
# `setvalue`/`select`/`upload` take `[VALUE(S)]...` after `<SELECTOR>`, and
# `batch` takes `[COMMANDS]...`. clap's variadic greedily consumes a flag that
# follows the first positional, folding it into the value silently - a trailing
# `--session` folds too, dropping the command onto an auto-provisioned billable
# `default` session. The CLI's own end-of-options marker is the fix (D19).
_VARIADIC_VERBS = frozenset({"fill", "type", "setvalue", "select", "upload", "batch"})
_BOUNDARY = "--"
# The canonical form per verb, quoted back on refusal so re-encoding is trivial.
_CANONICAL_FORM = {
    **{v: f"steel browser {v} [OPTIONS] <selector> -- <value>..." for v in
       ("fill", "type", "setvalue", "select", "upload")},
    "batch": 'steel browser batch [OPTIONS] -- "<cmd>" "<cmd>"...',
}

def _workdir(session_id: str) -> str:
    # KALI_WORKDIR redirects only the root for host-side tests; in-container
    # default is /work, read at call time so import performs no I/O.
    workdir = os.path.join(os.environ.get("KALI_WORKDIR", "/work"), session_id)
    os.makedirs(workdir, exist_ok=True)
    return workdir

def _refused(kind: str, detail: str) -> dict:
    # Typed refusal: stable refused:<kind> prefix, never raises, never executes.
    return {"stdout": "", "stderr": f"refused:{kind}: {detail}",
            "returncode": 2, "duration_ms": 0}

def _run(command: str, session_id: str, timeout_s: int) -> dict:
    # The one exec implementation both tools share: per-session workdir,
    # ANSI-stripped {stdout, stderr, returncode, duration_ms} envelope.
    workdir = _workdir(session_id)
    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=workdir,
                              capture_output=True, text=True, timeout=timeout_s)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), f"timeout after {timeout_s}s"
    return {"stdout": _ANSI.sub("", out), "stderr": _ANSI.sub("", err),
            "returncode": rc, "duration_ms": int((time.time() - start) * 1000)}

@mcp.tool()
def execute_command(command: str, session_id: str, timeout_s: int = 300) -> dict:
    """Run a shell command in /work/{session_id} and return
    {stdout, stderr, returncode, duration_ms}. ANSI stripped."""
    return _run(command, session_id, timeout_s)

def _session_name(command: str) -> str | None:
    # Narrow start-shape detection for the namespace guard: command-mode
    # session starts only. Scripts rely on skill-constructed unique names,
    # so script text is never scanned here.
    if not _START_SHAPE.search(command):
        return None
    m = _SESSION_FLAG.search(command)
    if not m:
        return None
    return m.group(1) or m.group(2) or m.group(3)


def _shlex_tokens(text: str) -> list[str] | None:
    # Shell-aware tokenization, so a `--` inside a quoted value stays one token
    # and is not mistaken for the boundary. None on unparseable text: the shell
    # rejects that itself, so the guard stays out of it rather than guess.
    try:
        return shlex.split(text)
    except ValueError:
        return None


def _verb_of(tokens: list[str]) -> str | None:
    # The dispatched subcommand: the token after `browser` for a top-level
    # command, the first token for a `batch` element (which carries no `browser`).
    for i, tok in enumerate(tokens):
        if tok == "browser" and i > 0:
            return tokens[i + 1] if i + 1 < len(tokens) else None
    return tokens[0] if tokens else None


def _boundary_gap(command: str) -> str | None:
    # The offending verb when a variadic command omits the `--` boundary, else
    # None. This never guesses where the boundary is and never reorders: it
    # requires the caller to declare it with the CLI's own end-of-options token,
    # so a canonical command cannot fold and a non-canonical one fails loudly
    # rather than folding a trailing flag into the entered value.
    tokens = _shlex_tokens(command)
    if not tokens:
        return None
    verb = _verb_of(tokens)
    if verb not in _VARIADIC_VERBS:
        return None
    if _BOUNDARY not in tokens:
        return verb
    if verb == "batch":
        # Each batch element is its own command over the same variadic grammar,
        # so a text-entry element must carry its own boundary too.
        for element in tokens[tokens.index(_BOUNDARY) + 1:]:
            sub = _shlex_tokens(element)
            sub_verb = _verb_of(sub) if sub else None
            if sub_verb in _VARIADIC_VERBS and sub_verb != "batch" \
                    and _BOUNDARY not in sub:
                return sub_verb
    return None


def _boundary_refused(verb: str) -> dict:
    target = "commands" if verb == "batch" else "value"
    return _refused(
        "variadic-boundary",
        f"{verb} needs its -- boundary before the {target}: "
        f"{_CANONICAL_FORM[verb]} (options precede the --; everything after it "
        "is the value, verbatim)")


def _live_session_names() -> set[str] | None:
    # The session catalogue (re-probed live 2026-09-16): `steel browser
    # sessions --json` returns every live session this key owns as
    # {id, mode, name, status, viewerUrl}, and `data: []` once none is live -
    # one read answers the name question that used to cost a per-name `live`
    # probe, and it is visible across processes and workdirs (proven by
    # starting through this tool and listing from a separate shell). Fail-open:
    # an error or unparseable shape returns None ("cannot verify"), so a broken
    # catalogue never blocks a start. The check-then-start race is accepted and
    # documented, not solved.
    try:
        proc = subprocess.run(
            "steel browser sessions --json",
            shell=True, capture_output=True, text=True,
            timeout=_CATALOGUE_TIMEOUT_S)
        data = json.loads(proc.stdout or "").get("data")
        if not isinstance(data, list):
            return None
        return {s["name"] for s in data
                if isinstance(s, dict) and isinstance(s.get("name"), str)}
    except Exception:
        return None


def _steel_version_ok() -> bool:
    # Cheap re-check of the pinned CLI before running: `steel --version`
    # must name the pin. Fail-closed on a proven mismatch; fail-open when
    # the probe itself errors, so a missing binary surfaces as the run's
    # own shell error instead of a version verdict.
    try:
        proc = subprocess.run("steel --version", shell=True, capture_output=True,
                              text=True, timeout=_VERSION_TIMEOUT_S)
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 or not out.strip():
            return True
        return _STEEL_VERSION_PIN in out
    except Exception:
        return True


def _steel_waits_s(command: str) -> list[float]:
    # Steel op waits ride `--timeout` in milliseconds (spike: 10000 lands the
    # ~11s timeout path). `--session-timeout` is a session lifetime, not a
    # wait, and the lookbehind keeps it out of the ordering check.
    return [int(v) / 1000 for v in _STEEL_WAIT.findall(command)]

def _run_script(script: str, script_lang: str, session_id: str, timeout_s: int) -> dict:
    # Verbatim write (no templating) to a unique session-workdir file, then run
    # through the shared runner so the envelope stays identical.
    workdir = _workdir(session_id)
    with tempfile.NamedTemporaryFile(mode="w", suffix=f".{script_lang}", prefix="steel_exec_",
                                     dir=workdir, delete=False, encoding="utf-8") as f:
        f.write(script)
    return _run(f"{_SCRIPT_RUNNERS[script_lang]} {shlex.quote(f.name)}", session_id, timeout_s)

@mcp.tool()
def steel_exec(command: str = "", script: str = "", script_lang: str = "sh",
               session_id: str = "steel", timeout_s: int = 600) -> dict:
    """Run a steel CLI command or automation script in /work/{session_id} and
    return the unchanged {stdout, stderr, returncode, duration_ms} envelope.
    Exactly one of command/script; commands must carry the steel token.
    Guards, in order: pinned steel version re-check; longest steel --timeout
    must sit below timeout_s (default 600, steel clock authoritative); a
    command-mode start on a name the live session catalogue reports is refused
    with `<name> is already used`; a variadic command (fill/type/setvalue/
    select/upload/batch) without the `--` boundary is refused, because clap
    would silently fold a trailing flag into the value. Scripts carry timeout
    ordering, unique names, and the boundary by skill construction and are
    never scanned."""
    if bool(command) == bool(script):
        return _refused("ambiguous-input", "pass exactly one of command or script")
    if command:
        if not _STEEL_TOKEN.search(command):
            return _refused("not-steel-command", "command carries no steel token")
        if not _steel_version_ok():
            return _refused("steel-version-mismatch",
                            f"need steel {_STEEL_VERSION_PIN}")
        waits = _steel_waits_s(command)
        if waits and max(waits) >= timeout_s:
            return _refused("timeout-ordering",
                            f"longest steel wait {max(waits)}s needs tool timeout_s above it, got {timeout_s}")
        name = _session_name(command)
        if name is not None:
            live = _live_session_names()
            if live is not None and name in live:
                return _refused("session-taken", f"{name} is already used")
        gap = _boundary_gap(command)
        if gap is not None:
            return _boundary_refused(gap)
        return _run(command, session_id, timeout_s)
    if script_lang not in _SCRIPT_RUNNERS:
        return _refused("unsupported-script-lang", f"want one of {sorted(_SCRIPT_RUNNERS)}")
    if not _steel_version_ok():
        return _refused("steel-version-mismatch",
                        f"need steel {_STEEL_VERSION_PIN}")
    return _run_script(script, script_lang, session_id, timeout_s)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
