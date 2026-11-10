"""Private bounded orchestration boundaries for generated-JS structure."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import selectors
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class StructureParseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StructureLimits:
    max_input_bytes: int = 8 * 1024 * 1024
    deadline_s: float = 20.0
    parser_timeout_s: float = 20.0
    max_parser_memory_bytes: int = 384 * 1024 * 1024
    max_items: int = 10_000
    max_index_bytes: int = 16 * 1024 * 1024
    max_parser_output_bytes: int = 16 * 1024 * 1024
    node_heap_mb: int = 384

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("structure limits must be positive")


@dataclass(frozen=True)
class ParsedStructure:
    format: str
    status: str
    items: tuple[dict, ...]
    gaps: tuple[str, ...]
    parse_errors: tuple[dict, ...]
    parser: dict
    source_sha256: str
    source_size: int
    index_bytes: int
    parser_memory_bytes: int


def _parser_path() -> Path:
    return Path(__file__).resolve().with_name("parser") / "structure_parser.mjs"


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (AttributeError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=2)
    except (AttributeError, subprocess.TimeoutExpired, OSError):
        pass


def _write_stdin(proc: subprocess.Popen, source: bytes) -> None:
    try:
        assert proc.stdin is not None
        proc.stdin.write(source)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _run_parser(
    source: bytes,
    *,
    limits: StructureLimits,
    parser_command: Sequence[str] | None,
) -> tuple[bytes, int]:
    node = shutil.which("node") or "node"
    command = list(
        parser_command
        or [
            node,
            "--expose-gc",
            f"--max-old-space-size={limits.node_heap_mb}",
            str(_parser_path()),
        ]
    )
    command.append(
        json.dumps(
            {
                "max_items": limits.max_items,
                "max_index_bytes": limits.max_index_bytes,
            },
            separators=(",", ":"),
        )
    )
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    writer = threading.Thread(
        target=_write_stdin,
        args=(proc, source),
        daemon=True,
    )
    writer.start()
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    assert proc.stderr is not None
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    chunks: list[bytes] = []
    stderr_bytes = 0
    total = 0
    timed_out = False
    exceeded = False
    memory_exceeded = False
    deadline = started + min(limits.deadline_s, limits.parser_timeout_s)
    try:
        while selector.get_map():
            try:
                rss_kb = int(
                    next(
                        line.split()[1]
                        for line in Path(f"/proc/{proc.pid}/status")
                        .read_text()
                        .splitlines()
                        if line.startswith("VmRSS:")
                    )
                )
            except (OSError, StopIteration, ValueError):
                rss_kb = 0
            if rss_kb * 1024 > limits.max_parser_memory_bytes:
                memory_exceeded = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, remaining)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > limits.max_parser_output_bytes:
                    exceeded = True
                    break
                if key.data == "stdout":
                    chunks.append(chunk)
                else:
                    stderr_bytes += len(chunk)
            if exceeded:
                break
        if timed_out or exceeded or memory_exceeded:
            _kill(proc)
        else:
            try:
                proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill(proc)
    finally:
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
        writer.join(timeout=1)
    if timed_out:
        raise StructureParseError("parser_timeout")
    if exceeded:
        raise StructureParseError("parser_output_limit")
    if memory_exceeded:
        raise StructureParseError("parser_memory_limit")
    if proc.returncode != 0:
        raise StructureParseError("parser_process_failed")
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak = max(usage_before, usage_after) * 1024
    return b"".join(chunks), peak


def parse_structure_bytes(
    source: bytes,
    *,
    limits: StructureLimits | None = None,
    parser_command: Sequence[str] | None = None,
) -> ParsedStructure:
    limits = limits or StructureLimits()
    if not isinstance(source, bytes):
        raise StructureParseError("source_must_be_bytes")
    if len(source) > limits.max_input_bytes:
        raise StructureParseError("input_size_limit")
    output, parser_memory = _run_parser(
        source,
        limits=limits,
        parser_command=parser_command,
    )
    if len(output) > limits.max_index_bytes:
        raise StructureParseError("index_size_limit")
    try:
        payload = json.loads(output)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StructureParseError("invalid_parser_output") from None
    if not isinstance(payload, dict):
        raise StructureParseError("invalid_parser_output")
    expected_hash = hashlib.sha256(source).hexdigest()
    source_meta = payload.get("source") or {}
    if (
        source_meta.get("sha256") != expected_hash
        or source_meta.get("bytes") != len(source)
    ):
        raise StructureParseError("parser_source_mismatch")
    status = payload.get("status")
    if status not in {"complete", "partial", "unsupported", "failed"}:
        raise StructureParseError("invalid_parser_status")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) > limits.max_items:
        raise StructureParseError("invalid_parser_items")
    allowed_kinds = {"import", "module", "dependency", "chunk", "loader"}
    for item in items:
        if not isinstance(item, dict) or item.get("kind") not in allowed_kinds:
            raise StructureParseError("invalid_structure_item")
        if not item.get("occurrence_key"):
            raise StructureParseError("invalid_structure_identity")
        start = item.get("start_byte")
        end = item.get("end_byte")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end < start
            or end > len(source)
        ):
            raise StructureParseError("invalid_structure_range")
    parse_errors = payload.get("parse_errors") or []
    gaps = payload.get("gaps") or []
    if not isinstance(parse_errors, list) or not isinstance(gaps, list):
        raise StructureParseError("invalid_parser_diagnostics")
    return ParsedStructure(
        format=str(payload.get("format") or "unknown"),
        status=status,
        items=tuple(items),
        gaps=tuple(str(value) for value in gaps),
        parse_errors=tuple(parse_errors),
        parser=dict(payload.get("parser") or {}),
        source_sha256=expected_hash,
        source_size=len(source),
        index_bytes=len(output),
        parser_memory_bytes=parser_memory,
    )
