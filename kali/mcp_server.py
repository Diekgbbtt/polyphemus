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
_ORACLE_TIMEOUT_S = 30
_VERSION_TIMEOUT_S = 15
_SCRIPT_RUNNERS = {"sh": "sh", "py": "python3"}

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


def _session_live(name: str) -> bool:
    # Uniqueness oracle (D13, proven live 2026-09-11): `live` returns
    # {success:true} iff the name is taken. Fail-open: any oracle error or
    # unparseable shape reads as free, so a broken oracle never blocks a
    # flow. The check-then-start race is accepted and documented, not solved.
    try:
        proc = subprocess.run(
            f"steel browser live --session {shlex.quote(name)} --json",
            shell=True, capture_output=True, text=True, timeout=_ORACLE_TIMEOUT_S)
        return json.loads(proc.stdout or "").get("success") is True
    except Exception:
        return False


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
    command-mode start on a live name is refused with `<name> is already
    used`. Scripts carry timeout ordering and unique names by skill
    construction and are never scanned."""
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
        if name is not None and _session_live(name):
            return _refused("session-taken", f"{name} is already used")
        return _run(command, session_id, timeout_s)
    if script_lang not in _SCRIPT_RUNNERS:
        return _refused("unsupported-script-lang", f"want one of {sorted(_SCRIPT_RUNNERS)}")
    if not _steel_version_ok():
        return _refused("steel-version-mismatch",
                        f"need steel {_STEEL_VERSION_PIN}")
    return _run_script(script, script_lang, session_id, timeout_s)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
