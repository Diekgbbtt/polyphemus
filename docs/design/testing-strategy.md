# Testing strategy - tiers, discipline, and how to run them

*Authoritative reference for how this repo's tests are layered, what each tier may touch, and the procedure for running them.
Written 2026-07-22 after a test-framework repair that fixed a long-standing failure and uncovered several silently-dead tests.
Read this before adding a test that needs a database.*

---

## 1. The tiers

| Tier | Location | May touch a real database? | Runs where |
|---|---|---|---|
| **Unit** | `tests/`, `tests/recon/`, `tests/recon/**` | **NO - enforced at runtime** | host, no infra needed |
| **Integration** | `tests/integration/` | yes (auto-marked) | inside the Docker network |
| **E2E** | `tests/e2e/` | yes (auto-marked) | inside the Docker network |

The unit tier is by far the largest (~890 tests) and must stay runnable on a laptop with nothing running.
Every module in this codebase takes an injectable `read_fn` / `merge_fn` / `exec_fn` / `propose_fn` precisely so unit tests can supply a fake.
If a unit test seems to need a database, it is either misplaced or the seam it needs is missing - fix one of those, never reach for the live driver.

## 2. The unit tier must mock Neo4j - and this is ENFORCED

`tests/conftest.py` installs an autouse fixture that makes **any** live Neo4j access from an unmarked test raise immediately, naming the offending test.
It blocks both the helper functions (`read`, `merge`, `check`, `ensure_schema`, `ensure_l1_schema`) **and the raw `_driver` attribute**.

The driver guard is not belt-and-braces, it is load-bearing.
`pipeline.read_steering_signals` reaches past the helpers with `driver = neo4j_client._driver`, so a helper-only guard misses it entirely - which is exactly how a live-database call hid in the unit tier for months.

**Why raise rather than let it fail naturally.**
Most database call sites here are deliberately fail-open: a read error degrades to an empty result so a live run never crashes on a blip.
That is correct in production and poisonous in a test, because the error is swallowed and the test fails much later on an assertion that names something unrelated.
Raising at the point of contact means the next leak names itself instead of costing a forensic session.

To opt out, a test must be in `tests/integration/` or `tests/e2e/` (auto-marked by path), or carry `pytestmark = pytest.mark.live_neo4j` explicitly.
Opting out is a statement that the test genuinely needs a real database - not a way to silence the guard.

## 3. One source of truth for connection config

`tests/conftest.py::neo4j_target()` returns the `(uri, auth)` the live tiers use, read from the environment.
Live tests must use it. Do not write a connection literal into a test file.

This replaced `URI, AUTH = "bolt://localhost:7687", ("neo4j", "polymerhus")` duplicated across **14 files**, which pinned the credential in fourteen places and hardcoded a hostname that cannot resolve inside the Docker network - so the live tiers could only ever run from the host, against a different configuration from the one the agent actually uses.

Live tests reaching Neo4j through the config-backed `neo4j_client` are handled too: the same fixture rebinds `neo4j_client._driver` to `neo4j_target()` for marked tests, because `agent.app.config` is read at import and would otherwise still hold the unit-tier dummy.

**The unit-tier dummies must stay un-resolvable.** They are `*.invalid` hosts (reserved by RFC 6761, can never resolve). Never point them at `localhost` - see §6.

## 4. How to run each tier

**Unit tier** - the default; needs nothing running:

    .venv/bin/python -m pytest tests/ -q

**Integration / E2E tier** - run INSIDE the compose network, which is the sanctioned path:

    docker compose -f docker-compose.yml -f docker-compose.dev.yml \
      run --rm tests tests/integration -q

The `tests` service (defined in `docker-compose.dev.yml`, `profiles: [test]`) reuses the agent image, mounts the working tree at `/srv`, and inherits the in-network env - so it resolves `neo4j` by service DNS exactly as the agent does, and the tier exercises the real config path rather than a host-only substitute.
It is a one-shot runner, not a long-lived service; `profiles` keeps it out of `docker compose up`.

Running the live tiers from the host also works (Bolt is published), and `neo4j_target()` falls back to the host view. Prefer the in-network runner: it is the configuration production uses.

**Expected results** (2026-07-22): host `tests/` → 892 passed, 37 skipped, 0 failed. In-network `tests/integration` → 41 passed, 0 skipped.

## 5. Two known hazards when running the suite

- **`tests/e2e/test_stack_smoke.py` runs `docker compose up -d --build`.** A plain suite run therefore rebuilds and restarts your stack. Do not run the host suite and an in-network run concurrently - the restart will make the concurrent run's Postgres-gated tests skip, which looks like a regression and is not.
- **Python version divergence.** The test container is Python **3.11**; the host venv is **3.13**. The tier passes on both, but CI running only in-network would silently stop covering 3.13.

## 6. The failure modes this design exists to prevent

These are not hypotheticals. Each cost real debugging time and is the reason for a rule above.

**A "safe dummy" that was not safe.**
`tests/conftest.py` set `NEO4J_URI=bolt://localhost:7687` with password `test`, on the reasoning that a dummy is unreachable so tests degrade cleanly.
That is false on any machine running the stack: compose publishes Bolt to the host, so the dummy pointed at the **real database** and authenticated with the wrong password.
Neo4j locks an account after 3 consecutive failures (`dbms.security.auth_max_failed_attempts`), so a unit run locked out the account the live stack was using, and the resulting error surfaced as `AuthenticationRateLimit` - which reads like throttling and is not. It is wrong-password lockout.
**Rule: a dummy must be structurally un-resolvable, not merely wrong.**

**A broken skip gate hiding real coverage loss.**
`neo4j_live()` gated through the config-backed client, so the dummy password made it return `False` against a perfectly healthy database.
Every test gated on it skipped, reporting `live neo4j not reachable` - a plausible message that concealed the fact that the tier was not running.
One live test in `tests/recon/test_graph_read.py` had **never executed once**.
**Rule: a skip gate must test the thing it claims to test. A skip is a silent failure with good manners.**

**An assertion that quietly stopped asserting.**
`tests/recon/test_pipeline_e2e.py` filtered executed commands with `c.startswith("arjun")`.
When the arjun template gained a `printf '{}' > … && arjun …` prefix (commit `77dc0c2`, the contaminated-stdout fix), that filter matched nothing, and the test failed as `no arjun command was executed` - while arjun was wired correctly the whole time.
It was recorded as a permanent known-failure and misdiagnosed as a hermeticity defect for months.
**Rule: when a test asserts over a filtered collection, assert the filter is non-empty for the right reason.** This is the same vacuous-assertion family as the FR-CURE2E dedup defect, where a repair stage was indistinguishable from a no-op on clean input.

**Two sources of truth, reintroduced during the fix itself.**
While centralising config, `neo4j_target()` and the config-backed client were left disagreeing, so the same test passed in-network and failed on the host.
Worth recording because it happened *during* the repair of exactly that class of bug.
**Rule: when you centralise a config, check every consumer of it, including the ones that read it indirectly.**

## 7. Adding a test - the decision

1. Does it need a real database? Almost always **no** - inject a fake `read_fn`/`merge_fn`. Put it in the unit tier.
2. If it genuinely does (schema constraints, real MERGE semantics, idempotency against a live store), put it in `tests/integration/`, use `neo4j_target()`, and scope it to a unique per-test `project_id` so parallel runs do not collide.
3. Never add a live test to the unit tree with a `skipif` gate. That is how a test ends up never running and nobody noticing.
