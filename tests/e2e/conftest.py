"""E2E-tier isolation for the process environment.

Two live walkthroughs bridge the operator's `.env` onto host-side service
URLs (`NEO4J_URI=bolt://localhost:7687`, `KALI_MCP_URL=http://localhost:...`)
and reload the modules that read them. The bridge is correct for a host run,
but the mutation is process-wide: a later test that shells `docker compose up`
interpolates the host values into the CONTAINER environment, so the agent
boots pointing at its own loopback and crash-loops. That is exactly the
failure the eval-host run hit: every test after the first bridged module
failed against a dead agent.

Snapshot and restore the whole environment around every e2e test. The e2e
tier owns its process; a test that mutates the environment must not decide
what a later test asserts. Module-level environment writes still happen at
import time and stay the test author's responsibility.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _restore_process_environment():
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)
