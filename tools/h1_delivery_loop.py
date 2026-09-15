"""H1 Phase-1 loop v2 (parent): trace-id-direct reads, no global-window scan.

Verdict semantics (red-capable on the bug):
  CONTROL=LOST   -> bug reproduced (no barrier => receipt lost) => loop RED
  BARRIER=LANDED -> barrier rescues it (mechanism proof)
Exit 0 only when CONTROL lands (post-fix world); 1 while H1 holds.

Runs INSIDE the agent container.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _h1_env import load_langfuse_env  # noqa: E402

load_langfuse_env()

host = os.environ["LANGFUSE_HOST"].rstrip("/")
token = base64.b64encode(("%s:%s" % (
    os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])).encode()).decode()


def get_trace(tid):
    req = urllib.request.Request(host + "/api/public/traces/" + tid,
                                 headers={"Authorization": "Basic " + token})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


HERE = os.path.dirname(os.path.abspath(__file__))
ARMS = {"CONTROL": ("h1ctl", "noflush"), "BARRIER": ("h1bar", "barrier")}
STAMP = str(int(time.time()))
tids = {}
for arm, (prefix, mode) in ARMS.items():
    marker = "%s-%s" % (prefix, STAMP)
    try:
        os.remove("/tmp/h1_%s.tid" % mode)
    except OSError:
        pass
    child = subprocess.run(
        [sys.executable, os.path.join(HERE, "h1_delivery_child.py"), marker, mode],
        check=False, capture_output=True, text=True)
    if child.returncode != 0:
        print("%s child FAILED rc=%d err=%r" % (arm, child.returncode,
                                                child.stderr[-400:]), flush=True)
    try:
        with open("/tmp/h1_%s.tid" % mode) as fh:
            tids[arm] = (fh.read().strip(), marker)
    except OSError:
        tids[arm] = ("", marker)
    print("%s marker=%s trace=%s" % (arm, marker, tids[arm][0] or "NONE"),
          flush=True)

# NOTE: h1_child takes the marker from argv; env above is belt-and-braces.
found = {}
deadline = time.time() + 180
while time.time() < deadline and len(found) < 2:
    time.sleep(15)
    for arm, (tid, marker) in tids.items():
        if arm in found or not tid:
            continue
        try:
            trace = get_trace(tid)
        except Exception:  # noqa: BLE001 - 404 until ingested; 429: next round
            continue
        for obs in trace.get("observations", []):
            blob = json.dumps(obs.get("input")) + json.dumps(obs.get("output"))
            if marker in blob:
                found[arm] = (obs.get("model"), obs.get("usage"))
                print("%s HIT model=%r usage=%r" % (
                    arm, obs.get("model"), obs.get("usage")), flush=True)

for arm in ("CONTROL", "BARRIER"):
    print("%s=%s" % (arm, "LANDED" if arm in found else "LOST"), flush=True)
sys.exit(0 if "CONTROL" in found else 1)
