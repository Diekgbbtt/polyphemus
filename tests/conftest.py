import os
import sys
import time
from pathlib import Path

DOCPREP_SRC = Path(__file__).resolve().parents[1] / "data" / "lightrag" / "preprocessing_pipeline" / "src"
if DOCPREP_SRC.is_dir():
    sys.path.insert(0, str(DOCPREP_SRC))

import pytest

# Unit tests import config-backed modules (polymerhus.app.config eager-reads these
# env vars at import time). setdefault fills dummies ONLY when the var is
# absent, so a real sourced .env / the in-network compose env is never
# overridden, while a clean-env unit run (CI / fresh clone) can still import.
#
# The dummy HOST must be un-resolvable. It used to be `localhost:7687`, which is
# not a dead address on any machine running the compose stack - Bolt is published
# to the host (`0.0.0.0:7687`), so the "safe dummy" pointed at the REAL database
# and authenticated with the wrong password. Neo4j locks an account after 3
# consecutive failures (`dbms.security.auth_max_failed_attempts`), so a unit run
# would lock out the account the live stack was using, and any test whose Neo4j
# access is fail-open degraded into an assertion that named something else
# entirely. `.invalid` is reserved by RFC 6761 and can never resolve, so an
# accidental hit now fails instantly and legibly instead.
os.environ.setdefault("NEO4J_URI", "bolt://neo4j.invalid:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "dummy-not-a-real-password")
os.environ.setdefault("POSTGRES_DSN", "postgresql://postgres:postgres@postgres.invalid:5432/postgres")
os.environ.setdefault("KALI_MCP_URL", "http://kali.invalid:8000/mcp")


def neo4j_target():
    """The (uri, auth) the LIVE tiers connect with - the single source of truth.

    Read from the environment so the same test file works unchanged in both
    contexts: in-network (`bolt://neo4j:7687`, the compose service DNS, which is
    how `docker compose --profile test` runs it) and from the host against the
    published port. This replaced a `URI, AUTH = "bolt://localhost:7687",
    ("neo4j", "polymerhus")` constant duplicated across 14 files, which pinned
    the credential in 14 places and hardcoded a hostname that cannot resolve
    inside the Docker network.

    The fallback is the compose default, not the conftest dummy above: a live
    test that reaches this helper wants a real database, and failing to connect
    is the honest outcome when there isn't one."""
    uri = os.environ.get("NEO4J_URI") or "bolt://neo4j:7687"
    if uri.endswith(".invalid:7687") or ".invalid" in uri:
        # The unit-tier dummy is in force (no real env). Fall back to the host
        # view of the published port so a live tier run from the host works.
        uri = "bolt://localhost:7687"
    user = os.environ.get("NEO4J_USER") or "neo4j"
    pwd = os.environ.get("NEO4J_PASSWORD") or "polymerhus"
    if pwd.startswith("dummy-"):
        pwd = "polymerhus"
    return uri, (user, pwd)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_neo4j: test legitimately talks to a real Neo4j (integration/e2e tier); "
        "exempt from the unit-tier no-live-database guard.",
    )


def pytest_collection_modifyitems(config, items):
    """Auto-mark the live tiers so they are exempt from the guard below.

    Path-based for the whole integration/e2e trees; individual live tests that
    live outside those trees carry `pytestmark = pytest.mark.live_neo4j`."""
    for item in items:
        path = str(getattr(item, "fspath", ""))
        if f"{os.sep}integration{os.sep}" in path or f"{os.sep}e2e{os.sep}" in path:
            item.add_marker(pytest.mark.live_neo4j)


@pytest.fixture(autouse=True)
def _no_live_neo4j_in_unit_tier(request, monkeypatch):
    """Make ANY live Neo4j access from the unit tier fail loudly and immediately.

    The unit tier is not testing integration with Neo4j, so it must mock it. The
    failure mode this prevents is not a slow test - it is a SILENT one: most call
    sites are deliberately fail-open (a read error degrades to an empty result so
    a live run never crashes), so a leaked live call gets swallowed and the test
    fails much later on an assertion that mentions something else entirely. One
    such leak cost a full forensic session to trace back to a wrong password in
    this file.

    Raising at the point of contact means the next leak names itself. Live tiers
    opt out with `@pytest.mark.live_neo4j` (auto-applied to integration/ and
    e2e/); a unit test that needs graph data injects a fake `read_fn`/`merge_fn`,
    which every module in this codebase already supports."""
    from polymerhus.app.clients import neo4j_client

    if request.node.get_closest_marker("live_neo4j"):
        # Live tier: point the config-backed client at the SAME target the
        # self-built drivers use.
        #
        # Without this there are two sources of truth again. `neo4j_client`
        # binds its driver at import from `polymerhus.app.config`, which reads the
        # unit-tier dummy when no real env is exported - so a live test calling
        # `neo4j_client.merge()` died on `Cannot resolve neo4j.invalid` from the
        # host while a sibling test that built its own driver from
        # `neo4j_target()` passed. In-network (the sanctioned runner) the two
        # already agree and this rebind is a no-op; from the host it makes the
        # client follow the live target rather than the dummy.
        from neo4j import GraphDatabase
        uri, auth = neo4j_target()
        if uri != getattr(neo4j_client, "_bound_uri", None):
            monkeypatch.setattr(
                neo4j_client, "_driver", GraphDatabase.driver(uri, auth=auth), raising=False
            )
        return

    def _forbidden(name):
        def _raise(*args, **kwargs):
            raise RuntimeError(
                f"neo4j_client.{name}() was called from a UNIT test "
                f"({request.node.nodeid}). The unit tier must not touch a real "
                "database - inject a fake read_fn/merge_fn instead. If this test "
                "genuinely needs live Neo4j, move it to tests/integration/ or "
                "mark it @pytest.mark.live_neo4j."
            )
        return _raise

    for fn in ("read", "merge", "check", "ensure_schema", "ensure_l1_schema"):
        monkeypatch.setattr(neo4j_client, fn, _forbidden(fn), raising=False)

    # Guarding the helper functions alone is NOT enough: some call sites reach
    # past them for the raw driver (`pipeline.read_steering_signals` does
    # `driver = neo4j_client._driver`, then `driver.session()`), which sails
    # straight through a helper-level patch. That is exactly how the arjun
    # pipeline e2e leaked to a live database undetected. Block the driver too,
    # so there is no path left.
    class _ForbiddenDriver:
        def __getattr__(self, attr):
            raise RuntimeError(
                f"neo4j_client._driver.{attr} was accessed from a UNIT test "
                f"({request.node.nodeid}). The unit tier must not touch a real "
                "database - inject a driver/read_fn, or mark the test "
                "@pytest.mark.live_neo4j if it genuinely needs one."
            )

    monkeypatch.setattr(neo4j_client, "_driver", _ForbiddenDriver(), raising=False)

def pg_live_dsn():
    """Return POSTGRES_DSN if a real connection succeeds, else None.

    conftest fills a dummy POSTGRES_DSN so config-backed modules can import,
    which defeats a bare `skipif(not env)` gate. Live-PG tests must gate on
    actual reachability instead, so a clean-env run skips cleanly rather than
    failing against the dummy credentials."""
    import psycopg
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return None
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
        return dsn
    except Exception:  # noqa: BLE001
        return None


def neo4j_live():
    """True when the Neo4j the LIVE tiers target is reachable (skip gate).

    Gates on `neo4j_target()`, NOT on the config-backed client. Going through
    config made this return False whenever the conftest dummy was in force - so
    live tests reported "live Neo4j required" and skipped while a perfectly
    healthy database was running, hiding real coverage loss behind a plausible
    skip message."""
    from neo4j import GraphDatabase
    uri, auth = neo4j_target()
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=auth)
        driver.verify_connectivity()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:  # noqa: BLE001
                pass


def wait_for(fn, timeout=120, interval=2):
    """Poll fn() until truthy or non-raising; re-raise last error on timeout."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(interval)
    if last:
        raise last
    raise TimeoutError(f"wait_for timed out after {timeout}s")
