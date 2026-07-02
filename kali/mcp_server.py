"""Single-tool fastmcp execution server for the reused Kali image.
Exposes execute_command over native HTTP at /mcp; per-session workdir isolation;
ANSI-stripped output; PATH primed for the ProjectDiscovery + gap tools.
No scope enforcement (MVP)."""
import os, re, subprocess, time
from fastmcp import FastMCP

os.environ["PATH"] = ":".join([
    "/opt/localbin", "/root/go/bin", "/opt/venv/bin", "/usr/local/go/bin", os.environ.get("PATH", ""),
])

mcp = FastMCP("kali-exec")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

@mcp.tool()
def execute_command(command: str, session_id: str, timeout_s: int = 300) -> dict:
    """Run a shell command in /work/{session_id} and return
    {stdout, stderr, returncode, duration_ms}. ANSI stripped."""
    workdir = f"/work/{session_id}"
    os.makedirs(workdir, exist_ok=True)
    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=workdir,
                              capture_output=True, text=True, timeout=timeout_s)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, (e.stdout or ""), f"timeout after {timeout_s}s"
    return {"stdout": _ANSI.sub("", out), "stderr": _ANSI.sub("", err),
            "returncode": rc, "duration_ms": int((time.time() - start) * 1000)}

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
