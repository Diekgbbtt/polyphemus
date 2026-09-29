"""Reset every #238 E2E target and print the fresh generations as JSON.

Run INSIDE the agent container (the fixtures have no host ports). Each target's
`/reset` mints a new generation; the counters are re-read WITH that generation
and must be zero, so a leftover run can never be mistaken for a clean one.
"""
from __future__ import annotations

import json
import urllib.request

TARGETS = (
    "no-limiter.e2e.local",
    "high-limit.e2e.local",
    "low-limit.e2e.local",
    "false-bypass.e2e.local",
    "burst-inconclusive.e2e.local",
)


def main() -> None:
    generations: dict[str, str] = {}
    for target in TARGETS:
        base = f"http://{target}"
        request = urllib.request.Request(f"{base}/reset", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            generation = json.load(response)["generation"]
        with urllib.request.urlopen(
            f"{base}/counters?generation={generation}", timeout=5
        ) as response:
            counters = json.load(response)
        assert counters["requests"] == 0, (target, counters["requests"])
        generations[target] = generation
    print(json.dumps(generations, sort_keys=True))


if __name__ == "__main__":
    main()
