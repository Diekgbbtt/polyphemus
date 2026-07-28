"""Route THIS application's logs somewhere a human can read them.

WHY THIS MODULE EXISTS. Uvicorn configures only its own `uvicorn*` loggers, so
every `logging.getLogger("polymerhus...")` call in this codebase went nowhere.
The analyser's per-pass census, the feed's degradation warnings, the pipeline's
per-job "degraded" lines and `_launch_pipeline`'s traceback were all invisible in
production. `logging.lastResort` is not a safety net either: it emits WARNING and
above with no timestamp, no logger name, and no way to configure it.

That blindness is not cosmetic. Diagnosing a stopped run on 2026-07-28 meant
reconstructing the failure from Postgres timestamps and a Neo4j node count,
because the process itself said nothing at all - and the one line that would have
named the cause immediately (`logger.exception` in `_launch_pipeline`) was being
written to a logger with no handler.

Kept in its OWN module, deliberately: `app.main` cannot be imported without the
full runtime environment (`config` reads `NEO4J_URI` at class-body time), and
logging configuration must be importable and testable without a database.
"""
from __future__ import annotations

import logging
import os
import sys

# Marker attribute so re-application is a no-op rather than a duplicated handler
# (every log line twice is its own kind of unreadable).
_MARKER = "_polymerhus_handler"

# Third parties chatty enough to bury the application's own lines at INFO.
_NOISY = ("httpx", "httpcore", "neo4j", "urllib3", "openai", "hpack", "h2")


def configure_logging(stream=None) -> logging.Handler | None:
    """Attach one stdout handler to the root logger. Idempotent.

    Applied at import of `app.main` (before uvicorn installs its own config) so
    running under uvicorn, under pytest, or as a bare module all behave the same.
    Returns the handler it installed, or the existing one when already configured.
    """
    root = logging.getLogger()
    existing = next((h for h in root.handlers if getattr(h, _MARKER, False)), None)

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):  # LOG_LEVEL=BANANA must not crash the process
        level = logging.INFO

    if existing is None:
        handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        setattr(handler, _MARKER, True)
        root.addHandler(handler)
        existing = handler

    # Never RAISE the effective threshold: a root already set louder by something
    # else (pytest -o log_cli_level, an operator's own config) keeps its setting.
    root.setLevel(min(root.level, level) if root.level else level)
    for noisy in _NOISY:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return existing
