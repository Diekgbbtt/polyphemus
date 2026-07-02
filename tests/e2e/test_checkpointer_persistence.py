"""Deep e2e — the durability mechanism (AsyncPostgresSaver's sync sibling
PostgresSaver, same tables) actually persists and resumes a checkpoint.
Runs inside the agent container to use its exact installed langgraph.
Critical components: postgres + the agent runtime."""
import subprocess

SNIPPET = (
    "from langgraph.checkpoint.postgres import PostgresSaver\n"
    "from langgraph.checkpoint.base import empty_checkpoint\n"
    "import os\n"
    "with PostgresSaver.from_conn_string(os.environ['POSTGRES_DSN']) as s:\n"
    "    s.setup()\n"
    "    cfg = {'configurable': {'thread_id': 'e2e-ckpt', 'checkpoint_ns': ''}}\n"
    "    chk = empty_checkpoint()\n"
    "    s.put(cfg, chk, {'source': 'e2e'}, {})\n"
    "    got = s.get_tuple(cfg)\n"
    "    assert got is not None, 'checkpoint not persisted'\n"
    "    assert got.checkpoint['id'] == chk['id'], 'resumed checkpoint id mismatch'\n"
    "    print('CKPT_OK')\n"
)

def test_checkpointer_persists_and_resumes():
    subprocess.run(["docker", "compose", "up", "-d", "agent"], check=True)  # deps auto-start
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "agent", "python", "-c", SNIPPET],
        capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    assert "CKPT_OK" in r.stdout, r.stdout + r.stderr
