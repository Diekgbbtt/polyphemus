"""Pure parser: `webpack_chunks` resolver stdout -> list[AssetDelta].

The resolver (`scripts/webpack_chunks.py`) emits one JSONL record per resolved
webpack lazy chunk: `{"webpack_chunk_url": "<absolute url>"}`. Each becomes a
`BaseURL` + `Endpoint` pair (source `webpack`), exactly the same decomposition
every URL-emitting parser funnels through `url_to_deltas`, so a chunk URL
discovered here MERGEs onto the same node a crawler would have minted.

Pure, deterministic, tolerant of malformed/missing-key lines - never raises.
"""
import json

from polymerhus.recon.domain.parsers._urls import url_to_deltas
from polymerhus.recon.domain.types import AssetDelta


def parse(stdout: str) -> list[AssetDelta]:
    deltas: list[AssetDelta] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        url = entry.get("webpack_chunk_url")
        if isinstance(url, str) and url:
            deltas.extend(url_to_deltas(url, method="GET", source="webpack"))

    return deltas
