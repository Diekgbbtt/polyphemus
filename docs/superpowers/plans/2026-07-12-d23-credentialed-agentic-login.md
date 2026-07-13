# D23 - Autonomous Credentialed Login for the Agentic Crawl - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an unattended agentic crawl log itself into a target using operator-stored credentials (the LLM ReAct loop drives the login), instead of requiring hand-harvested cookies or a human in the Steel viewer.

**Architecture:** Add a THIRD auth mode to the crawl node alongside the existing cookie-inject and human-interactive paths. Credentials live inside the existing `settings.recon.auth_context` (as a `credentials` sub-object), so the pipeline threads them through unchanged. The login is executed by the existing crawl ReAct loop (D23-1 = LLM-driven): a new prompt branch instructs the crawler agent to navigate to `login_url`, fill + submit the form once (heuristic selectors, or operator overrides), then verify via the existing `steel_await_auth` detector before crawling. On MFA/SSO/captcha/unknown-portal the login cannot complete, the pod blocks and degrades to the existing `reduced_crawl_coverage` (D23-5 = blocking, not handoff - deferred).

**Tech Stack:** Python 3.13, pydantic, langchain/langgraph, FastAPI, Steel.dev (Playwright-over-CDP). Tests: pytest in the project `.venv`.

## Global Constraints

- **The auth split is by CONSUMER (D23-2), not precedence:** `auth_context.credentials` drive the AGENTIC (steel) crawl login; `auth_context.cookies` remain the request-based tools' `-H Cookie` header (httpx/katana/ffuf/arjun) and are untouched by this plan. Inside the crawl node, credentials (when present and host-matched) take the new branch; the existing cookie-inject/interactive/anonymous arms are the fallback when credentials are absent.
- **D23-1 = LLM ReAct loop** executes the login (not a deterministic Playwright routine). Credential-in-trace exposure is accepted under the pen-test threat model (operator owns the credentials + target).
- **D23-3 = heuristic selectors by default, operator selectors override.** Heuristic: `input[type=password]` for the password, the nearest preceding `input[type=email|text]` for the username, the form's submit control.
- **D23-4 = login_url may be ANY origin**, but login success is asserted **target-scoped** (an in-scope session cookie), so a dedicated `login.*`/`accounts.*` works while a true third-party IdP fails to the blocking state.
- **D23-6 = hardened success detection:** login counts as authenticated only when a NEW session-like cookie appeared (vs the session-start baseline) AND the browser navigated OFF a login path - both, not either.
- **D23-7 = host-gated:** only crawl pods whose target host matches the credentials' domain (explicit `credentials.domain`, else the `login_url` host) attempt the login; other hosts crawl anonymous.
- **D23-5 = MFA/SSO/captcha is a BLOCKING state (deferred):** the login just fails to complete and the pod degrades to `reduced_crawl_coverage` (existing best-effort path). Do NOT build a degrade-to-interactive/Discord handoff in this plan.
- **Secrets:** the password is operator-owned; it is stored in `settings.recon.auth_context.credentials` and may appear in the crawl LLM trace (accepted). It must NEVER be written to a committed file, a log line at INFO, or `.env.example`. No real credential value in any test.
- **Adaptation note:** `crawl_agentic.py` already has one documented adaptation (the skill-path resolution). Task 3 adds a SECOND, clearly-marked local adaptation (a credentials request field + a credentialed-login prompt branch). Mark it in the module docstring exactly like the existing adaptation note.
- **Best-effort / fail-open:** every new path degrades to the empty manifest / anonymous crawl on any error; nothing may abort the pipeline. Run tests with `.venv/bin/pytest`. TDD: failing test first. Commit path-scoped (`git add <exact files>`, never `git add -A`); no Co-Authored-By/agent trailer; plain dash only.

---

## File Structure

- `agent/app/routes.py` - extend `_validate_auth_context` to accept the optional `credentials` sub-object (Task 1).
- `agent/recon/crawl/steel_provider.py` - add the pure `login_succeeded(...)` hardened combinator (Task 2).
- `agent/recon/crawl/crawl_agentic.py` - add `credentials` to `AgenticCrawlRequest` + a credentialed-login prompt branch in `_run_agentic_crawl` (Task 3, the marked vendored extension).
- `agent/recon/crawl/steel_crawl_skill.md` - add a "Credentialed login" section (Task 3).
- `agent/recon/crawl/crawl_agent.py` - add `run_crawl_credentialed(...)` adapter (Task 4).
- `agent/recon/crawl/crawl_pod.py` - add the host-gate helper + the new credentials branch in the `crawl` node (Task 5).
- `.env.example` / `docs/design/recon-pipeline-forward-decisions.md` - D23 status already recorded; no new secret env.

---

### Task 1: Credentials settings schema + validation

**Files:**
- Modify: `agent/app/routes.py` (`_validate_auth_context`, routes.py:46-64)
- Test: `tests/test_rest_api.py`

**Interfaces:**
- Produces: `auth_context.credentials` accepted shape = dict with required string `username`, `password`, `login_url`; optional string `domain`, `username_selector`, `password_selector`, `submit_selector`. Absent `credentials` is valid (backward compatible).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_rest_api.py`:

```python
def test_put_settings_valid_credentials_200(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append(recon))
    recon = {"target_domain": "example.com", "auth_context": {
        "cookies": [],
        "credentials": {"username": "u@e.com", "password": "pw",
                        "login_url": "https://login.example.com/", "domain": "example.com"}}}
    resp = client.put("/projects/p1/settings", json={"recon": recon})
    assert resp.status_code == 200
    assert saved and saved[0]["auth_context"]["credentials"]["username"] == "u@e.com"


def test_put_settings_malformed_credentials_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)
    # missing password
    resp = client.put("/projects/p1/settings", json={"recon": {"auth_context": {
        "cookies": [], "credentials": {"username": "u", "login_url": "https://x"}}}})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/pytest tests/test_rest_api.py::test_put_settings_valid_credentials_200 tests/test_rest_api.py::test_put_settings_malformed_credentials_400 -v`
Expected: the malformed test FAILS (no validation yet -> 200 instead of 400).

- [ ] **Step 3: Implement the validation extension**

In `agent/app/routes.py::_validate_auth_context`, after the `scope` check, add:

```python
    credentials = auth_context.get("credentials")
    if credentials is not None:
        if not isinstance(credentials, dict):
            raise ValueError("auth_context.credentials must be an object")
        for field in ("username", "password", "login_url"):
            if not isinstance(credentials.get(field), str) or not credentials[field]:
                raise ValueError(f"auth_context.credentials.{field} must be a non-empty string")
        for field in ("domain", "username_selector", "password_selector", "submit_selector"):
            if field in credentials and not isinstance(credentials[field], str):
                raise ValueError(f"auth_context.credentials.{field} must be a string")
```

- [ ] **Step 4: Run and watch pass**

Run: `.venv/bin/pytest tests/test_rest_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/app/routes.py tests/test_rest_api.py
git commit -m "feat(recon): accept auth_context.credentials in settings validation (D23)"
```

---

### Task 2: Hardened login-success predicate

**Files:**
- Modify: `agent/recon/crawl/steel_provider.py` (add near the auth-detection predicates, steel_provider.py:73-88)
- Test: `tests/recon/crawl/test_steel_provider_cookies.py` (or the nearest steel_provider unit test file)

**Interfaces:**
- Produces: `login_succeeded(baseline_names: set, current_cookies: list, url: str, scope: list) -> bool` - true ONLY when a new in-scope session-like cookie appeared AND the URL is an in-scope non-login page (D23-6). Pure, reuses the existing predicates.

- [ ] **Step 1: Write the failing test**

Add to the steel_provider unit test file:

```python
def test_login_succeeded_requires_both_cookie_and_off_login_nav():
    from agent.recon.crawl.steel_provider import login_succeeded
    scope = ["example.com"]
    baseline = {"visitor"}
    new_session = [{"name": "sessionid", "value": "x", "domain": "example.com", "httpOnly": True}]

    # both conditions -> success
    assert login_succeeded(baseline, new_session, "https://app.example.com/dashboard", scope) is True
    # new cookie but still on the login path -> NOT success (failed submit)
    assert login_succeeded(baseline, new_session, "https://login.example.com/login", scope) is False
    # off-login page but no new session cookie -> NOT success
    assert login_succeeded(baseline, [{"name": "visitor", "value": "x", "domain": "example.com"}],
                           "https://app.example.com/home", scope) is False
    # new cookie scoped to the wrong (out-of-scope) domain -> NOT success
    assert login_succeeded(baseline, [{"name": "sessionid", "value": "x", "domain": "idp.other.com",
                                       "httpOnly": True}], "https://app.example.com/home", scope) is False
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/pytest tests/recon/crawl/test_steel_provider_cookies.py -k login_succeeded -v`
Expected: FAIL (`login_succeeded` not defined).

- [ ] **Step 3: Implement (reusing the existing predicates)**

In `agent/recon/crawl/steel_provider.py`, after `_url_is_authenticated_app` (line ~88):

```python
def login_succeeded(baseline_names: set, current_cookies: list, url: str, scope: list) -> bool:
    """D23 hardened success test: an autonomous login counts as authenticated
    ONLY when BOTH hold - a NEW in-scope session-like cookie appeared vs the
    pre-login baseline AND the browser navigated to an in-scope non-login page.
    Either alone is a false positive (a CSRF/visitor cookie on the login page,
    or an off-login bounce with no session), which unattended login cannot
    afford. Pure; composes the existing steel_await_auth predicates."""
    return _has_new_session_cookie(baseline_names, current_cookies, scope) and \
        _url_is_authenticated_app(url, scope)
```

- [ ] **Step 4: Run and watch pass**

Run: `.venv/bin/pytest tests/recon/crawl/test_steel_provider_cookies.py -k login_succeeded -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/recon/crawl/steel_provider.py tests/recon/crawl/test_steel_provider_cookies.py
git commit -m "feat(recon): hardened login_succeeded predicate for autonomous login (D23-6)"
```

---

### Task 3: Credentialed-login request field + prompt branch + skill section

**Files:**
- Modify: `agent/recon/crawl/crawl_agentic.py` (AgenticCrawlRequest model at :33-45; the prompt build in `_run_agentic_crawl` at :160-178; the module docstring adaptation note at :7-14)
- Modify: `agent/recon/crawl/steel_crawl_skill.md` (add a section)
- Test: `tests/recon/crawl/test_crawl_agent.py` (or the nearest crawl-agentic test)

**Interfaces:**
- Consumes: nothing new.
- Produces: `AgenticCrawlRequest.credentials: Optional[dict] = None`; when set (and no `pre_created_crawl_id`), `_run_agentic_crawl` emits a credentialed-login user prompt naming `login_url`, the selectors (or "auto-detect"), and the submit-once + verify + blocking-on-MFA/SSO rules.

- [ ] **Step 1: Write the failing test**

The prompt is built inside `_run_agentic_crawl`; assert it via a fake LLM that captures the messages. Add to `tests/recon/crawl/test_crawl_agent.py`:

```python
def test_credentialed_login_prompt_names_login_url_and_submit_once(monkeypatch):
    import asyncio
    from agent.recon.crawl import crawl_agentic

    captured = {}

    class FakeLLM:
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages):
            captured["messages"] = messages
            from langchain_core.messages import AIMessage
            return AIMessage(content="", tool_calls=[])  # no tools -> loop ends fast

    class FakeMgr:
        async def get_tools(self): return []

    body = crawl_agentic.AgenticCrawlRequest(
        target="https://app.example.com", scope=["example.com"], model="crawler",
        max_iterations=1,
        credentials={"username": "u", "password": "pw", "login_url": "https://login.example.com/"},
    )
    asyncio.run(crawl_agentic._run_agentic_crawl(body, FakeMgr(), build_llm_fn=lambda m, u: FakeLLM()))

    text = captured["messages"][1].content  # the HumanMessage
    assert "https://login.example.com/" in text
    assert "credentials" in text.lower()
    assert "u" in text  # username surfaced to the agent
    # submit-once + blocking rules present
    assert "once" in text.lower()
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_agent.py::test_credentialed_login_prompt_names_login_url_and_submit_once -v`
Expected: FAIL (`AgenticCrawlRequest` has no `credentials`; no credentialed prompt branch).

- [ ] **Step 3: Add the request field**

In `agent/recon/crawl/crawl_agentic.py::AgenticCrawlRequest`, add:

```python
    credentials: Optional[dict] = None
```

- [ ] **Step 4: Add the credentialed-login prompt branch**

In `_run_agentic_crawl`, the prompt build currently has `if pre_created_crawl_id: ... else: ...` (:161-177). Insert a credentialed branch as the FIRST case (credentialed login is distinct from both the human-interactive precreate and the anonymous case):

```python
    creds = body.credentials or {}
    if pre_created_crawl_id:
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"A Steel session is ALREADY STARTED for this crawl: crawl_id={pre_created_crawl_id}\n"
            f"A human operator is logging in manually right now. Do NOT call steel_crawl_start.\n"
            f"FIRST call steel_await_auth(crawl_id={pre_created_crawl_id!r}). When it returns "
            f"authenticated=true, crawl the now-authenticated routes; if it returns timed_out=true, "
            f"crawl whatever is reachable. Then steel_crawl_finish.\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} wait_ms={body.navigate_wait_ms}"
        )
    elif creds:
        sel = (
            f"username selector={creds.get('username_selector') or 'auto-detect the email/text login input'}; "
            f"password selector={creds.get('password_selector') or 'auto-detect input[type=password]'}; "
            f"submit={creds.get('submit_selector') or 'the login form submit control'}"
        )
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"Begin by calling steel_crawl_start. You must AUTHENTICATE with credentials BEFORE crawling:\n"
            f"1. steel_navigate to login_url={creds.get('login_url')!r}.\n"
            f"2. Fill the login form with username={creds.get('username')!r} and the provided password "
            f"using steel_eval; {sel}.\n"
            f"3. steel_click the submit control EXACTLY ONCE. Do NOT resubmit on failure (account lockout).\n"
            f"4. Verify: an in-scope session cookie appeared AND you are on an in-scope non-login page. "
            f"If instead you are redirected off {body.scope} (SSO/OAuth), see a second factor / one-time "
            f"code / captcha, or no login form is present, you are BLOCKED: do NOT loop - call "
            f"steel_crawl_finish with whatever is reachable and stop.\n"
            f"5. Once authenticated, crawl the now-authenticated routes, then steel_crawl_finish.\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} wait_ms={body.navigate_wait_ms}"
        )
    else:
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} "
            f"wait_ms={body.navigate_wait_ms} proxy_escalation={body.proxy_escalation}\n"
            f"Begin by calling steel_crawl_start."
        )
```

- [ ] **Step 5: Mark the vendored adaptation**

In the module docstring (`crawl_agentic.py:7-14`), extend the "ONLY adaptation" note to record the second local adaptation: the `credentials` field on `AgenticCrawlRequest` and the credentialed-login prompt branch in `_run_agentic_crawl` (D23), so the divergence from the upstream vendored file stays documented.

- [ ] **Step 6: Add the skill section**

Append a `## Credentialed login (autonomous)` section to `agent/recon/crawl/steel_crawl_skill.md` restating the loop rules for the agent: navigate to login_url, fill with the provided username/password (heuristic selectors unless given), submit ONCE and never retry (lockout), success = a new in-scope session cookie AND an off-login in-scope page, and BLOCK (finish + stop, do not loop) on SSO/MFA/captcha/no-form. Keep it consistent with the existing skill's tone and the "do not retry" rule already present.

- [ ] **Step 7: Run and watch pass**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_agent.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add agent/recon/crawl/crawl_agentic.py agent/recon/crawl/steel_crawl_skill.md tests/recon/crawl/test_crawl_agent.py
git commit -m "feat(recon): credentialed-login prompt branch in the crawl ReAct loop (D23-1)"
```

---

### Task 4: `run_crawl_credentialed` adapter

**Files:**
- Modify: `agent/recon/crawl/crawl_agent.py` (add alongside `run_crawl` / `run_crawl_authenticated`; export in `__all__`)
- Test: `tests/recon/crawl/test_crawl_agent.py`

**Interfaces:**
- Produces: `async run_crawl_credentialed(target, *, scope, credentials, model_role="crawler", tools=None, llm=None, max_pages=None, max_depth=None, max_iters=None) -> dict` - builds an `AgenticCrawlRequest` with `credentials=` set and runs the loop; best-effort empty manifest on any error (mirrors `run_crawl`).

- [ ] **Step 1: Write the failing test**

```python
def test_run_crawl_credentialed_threads_credentials_into_request(monkeypatch):
    import asyncio
    from agent.recon.crawl import crawl_agent

    seen = {}

    async def fake_run_agentic(body, mcp_manager, *, build_llm_fn=None, pre_created_crawl_id=None):
        seen["credentials"] = body.credentials
        seen["target"] = body.target
        return {"endpoints": [{"url": "https://app.example.com/account"}], "js_urls": []}

    monkeypatch.setattr(crawl_agent, "_run_agentic_crawl", fake_run_agentic)

    manifest = asyncio.run(crawl_agent.run_crawl_credentialed(
        "https://app.example.com", scope=["example.com"],
        credentials={"username": "u", "password": "pw", "login_url": "https://login.example.com/"},
        tools=[], llm=object(),
    ))
    assert seen["credentials"]["username"] == "u"
    assert manifest["endpoints"][0]["url"].endswith("/account")


def test_run_crawl_credentialed_best_effort_on_error(monkeypatch):
    import asyncio
    from agent.recon.crawl import crawl_agent

    async def boom(*a, **k): raise RuntimeError("steel down")
    monkeypatch.setattr(crawl_agent, "_run_agentic_crawl", boom)

    manifest = asyncio.run(crawl_agent.run_crawl_credentialed(
        "https://app.example.com", scope=["example.com"],
        credentials={"username": "u", "password": "pw", "login_url": "https://l"}, tools=[], llm=object()))
    assert manifest == {"endpoints": [], "js_urls": []}
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_agent.py -k run_crawl_credentialed -v`
Expected: FAIL (function missing).

- [ ] **Step 3: Implement the adapter**

In `agent/recon/crawl/crawl_agent.py`, add `"run_crawl_credentialed"` to `__all__`, and add:

```python
async def run_crawl_credentialed(
    target: str,
    *,
    scope: list[str],
    credentials: dict,
    model_role: str = "crawler",
    tools: Optional[list] = None,
    llm=None,
    max_pages: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_iters: Optional[int] = None,
) -> dict:
    """Autonomous credentialed agentic crawl (D23): the ReAct loop logs in with
    `credentials` (username/password/login_url [+ optional selectors]) before
    crawling. Best-effort: any failure (Steel unconfigured, login blocked by
    MFA/SSO/captcha, tool/LLM error) yields the empty manifest so the crawl pod
    degrades to reduced coverage rather than crashing the pipeline."""
    try:
        resolved_tools = tools
        if resolved_tools is None:
            resolved_tools = await steel_client.get_crawl_tools()
        mcp_manager = _ToolsManager(resolved_tools)

        if llm is not None:
            def build_llm_fn(model, user_id, _llm=llm):
                return _llm
        else:
            from agent.app.llm.roles import chat_model_for

            def build_llm_fn(model, user_id, _role=model_role):
                return chat_model_for(_role)

        body = AgenticCrawlRequest(
            target=target,
            scope=list(scope),
            model=model_role,
            max_depth=max_depth if max_depth is not None else config.CRAWL_MAX_DEPTH,
            max_pages=max_pages if max_pages is not None else config.CRAWL_MAX_PAGES,
            max_iterations=max_iters if max_iters is not None else config.CRAWL_MAX_ITERS,
            job_timeout_s=config.CRAWL_JOB_TIMEOUT_S,
            auth_required=True,
            credentials=credentials,
        )
        return await _run_agentic_crawl(body, mcp_manager, build_llm_fn=build_llm_fn)
    except Exception:  # noqa: BLE001 - best-effort, see module docstring
        return dict(_EMPTY_MANIFEST)
```

Also import `_run_agentic_crawl` at the top of `crawl_agent.py` (the module currently imports `AgenticCrawlRequest, CRAWL_TOOL_NAMES, _run_agentic_crawl, precreate_auth_session` from `crawl_agentic` - `_run_agentic_crawl` is already imported; confirm and keep).

- [ ] **Step 4: Run and watch pass**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/recon/crawl/crawl_agent.py tests/recon/crawl/test_crawl_agent.py
git commit -m "feat(recon): run_crawl_credentialed adapter for autonomous login (D23)"
```

---

### Task 5: Crawl-node credentials branch + host gate

**Files:**
- Modify: `agent/recon/crawl/crawl_pod.py` (the `crawl` node mode fork, crawl_pod.py:171-233; add a module-level host-gate helper + a default credentialed-crawl fn, mirroring `default_run_crawl_authenticated_fn`)
- Test: `tests/recon/crawl/test_crawl_pod.py`

**Interfaces:**
- Consumes: `run_crawl_credentialed` (Task 4); `login_succeeded` is used inside the loop, not here.
- Produces: `credentials_apply_to_target(credentials: dict, target_url: str) -> bool` (host gate, D23-7); `build_crawl_pod(..., run_crawl_credentialed_fn=None)`; the `crawl` node routes to the credentialed path when credentials are present AND host-matched.

- [ ] **Step 1: Write the failing tests**

Add to `tests/recon/crawl/test_crawl_pod.py`:

```python
def test_credentials_apply_to_target_gates_on_host():
    from agent.recon.crawl.crawl_pod import credentials_apply_to_target
    creds = {"login_url": "https://login.example.com/", "domain": "example.com"}
    assert credentials_apply_to_target(creds, "https://app.example.com") is True   # in credentials domain
    assert credentials_apply_to_target(creds, "https://other.org") is False        # different app
    # no explicit domain -> fall back to the login_url host's registrable domain
    assert credentials_apply_to_target({"login_url": "https://login.example.com/"},
                                       "https://app.example.com") is True


def test_crawl_node_takes_credentialed_path_for_matching_host():
    from agent.recon.crawl.crawl_pod import build_crawl_pod
    from agent.recon.types import JobSpec

    called = {}

    def fake_credentialed(target, *, scope, credentials):
        called["target"] = target
        called["credentials"] = credentials
        return {"pages": [{"url": target}]}

    graph = build_crawl_pod(
        run_crawl_fn=lambda *a, **k: {"pages": []},
        parse_fn=lambda s: [],
        triage_fn=lambda e, a, j: [],
        curate_fn=lambda a, o, pid, **k: (0, 0),
        run_crawl_credentialed_fn=lambda target, scope, credentials: fake_credentialed(
            target, scope=scope, credentials=credentials),
    )
    job = JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="",
                  produces=["BaseURL"], consumes="BaseURL", use_auth=True, configurator_mode="agent")
    state = {"job": job, "input_asset": {"url": "https://app.example.com"},
             "extra": {"auth_context": {"credentials": {
                 "username": "u", "password": "pw",
                 "login_url": "https://login.example.com/", "domain": "example.com"}}},
             "project_id": "p1", "run_id": "r", "phase": 4}
    graph.invoke(state)
    assert called["target"] == "https://app.example.com"
    assert called["credentials"]["username"] == "u"
```

- [ ] **Step 2: Run and watch fail**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_pod.py -k "credentials" -v`
Expected: FAIL (`credentials_apply_to_target` missing; `build_crawl_pod` has no `run_crawl_credentialed_fn`).

- [ ] **Step 3: Add the host gate + default fn**

In `agent/recon/crawl/crawl_pod.py`, near the other `default_*` fns:

```python
from agent.recon.parsers._urls import registrable_domain  # add to imports if absent


def credentials_apply_to_target(credentials: dict, target_url: str) -> bool:
    """D23-7: credentials belong to ONE app. A crawl pod attempts the login only
    when its target host is in the credentials' domain - the explicit
    `credentials.domain`, else the registrable domain of `login_url`. Prevents
    submitting the same credentials to every host in a multi-BaseURL run
    (lockout / mis-auth). Fail-closed: no usable domain -> False."""
    if not isinstance(credentials, dict):
        return False
    dom = credentials.get("domain")
    if not dom:
        login_url = credentials.get("login_url") or ""
        host = login_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        dom = registrable_domain(host) if host else ""
    if not dom:
        return False
    target_host = (target_url or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    dom = dom.lower()
    return target_host == dom or target_host.endswith("." + dom)


def default_run_crawl_credentialed_fn(target: str, *, scope: list[str], credentials: dict) -> dict:
    """Real collaborator: autonomous credentialed agentic crawl (D23), sync."""
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking
    return run_coro_blocking(
        crawl_agent.run_crawl_credentialed(target, scope=scope, credentials=credentials)
    )
```

- [ ] **Step 4: Wire the branch into `build_crawl_pod` + the `crawl` node**

Add `run_crawl_credentialed_fn=None` to `build_crawl_pod`'s signature. In the `crawl` node, read credentials and route BEFORE the existing cookies/interactive fork:

```python
        auth_context = extra.get("auth_context") or {}
        credentials = auth_context.get("credentials") or {}
        auth_cookies = auth_context.get("cookies") or []
        use_auth_signal = bool(job is not None and getattr(job, "use_auth", False) and auth_context)
        cred_fn = run_crawl_credentialed_fn if run_crawl_credentialed_fn is not None else default_run_crawl_credentialed_fn

        viewer_url = None
        try:
            if use_auth_signal and credentials and credentials_apply_to_target(credentials, target):
                # D23: autonomous credentialed login drives the agentic crawl.
                manifest = cred_fn(target, scope=scope, credentials=credentials)
            elif use_auth_signal and auth_cookies:
                manifest = run_crawl_fn(target, scope=scope, auth_cookies=auth_cookies)
            elif use_auth_signal and run_crawl_authenticated_fn is not None:
                ...  # unchanged existing interactive branch
```

(Keep the rest of the node - the interactive/anonymous arms, `_manifest_is_empty`, the export - unchanged. The default `crawl_pod = build_crawl_pod(...)` construction at the module bottom needs `run_crawl_credentialed_fn` left to default, i.e. no change there.)

- [ ] **Step 5: Run and watch pass, then the full crawl suite**

Run: `.venv/bin/pytest tests/recon/crawl/test_crawl_pod.py -v`
Then: `.venv/bin/pytest tests/recon/crawl -q`
Expected: PASS (existing cookie/interactive/anonymous crawl-pod tests still green - credentials absent leaves them on their original branches).

- [ ] **Step 6: Commit**

```bash
git add agent/recon/crawl/crawl_pod.py tests/recon/crawl/test_crawl_pod.py
git commit -m "feat(recon): crawl-node credentialed-login branch, host-gated (D23-5/D23-7)"
```

---

## Final verification

- [ ] Full recon + API suite: `.venv/bin/pytest tests/recon tests/test_rest_api.py -q` (expect all green; existing crawl tests unaffected because credentials are absent in them).
- [ ] Secret guard: `git grep -nE "password|passwd" -- agent/ | grep -iv "password_selector\|password\"\|credentials\|# " ` shows no hardcoded credential value; confirm no real secret in tests or `.env.example`.
- [ ] Confirm no pipeline change was needed (auth_context threads through unchanged) and no change to the request-based tools' cookie handling.

## Deferred (recorded in D23, NOT built here)

- MFA/SSO/OAuth completion (blocking state only this build - the pod degrades to `reduced_crawl_coverage`).
- Degrade-to-interactive/Discord handoff from a failed autonomous login.
- Multi-step (identifier-first) login flows; SPA/token-in-localStorage auth (no cookie) success detection.
- The pre-existing `extra["scope"]` wiring bug (flagged in D23; verify + fix separately).

## Self-review notes (author)

- Spec coverage: D23-1 LLM loop = Task 3; D23-2 consumer-split = Global Constraints + Task 5 branch order; D23-3 selectors = Task 3 prompt; D23-4 any-origin/target-scoped = Task 2 `login_succeeded` (target scope) + Task 3 prompt; D23-6 hardened detection = Task 2; D23-7 host gate = Task 5; D23-5 blocking = Task 3 prompt (finish+stop) + best-effort degrade. Schema/validation = Task 1. Adapter = Task 4.
- Type consistency: `credentials` dict shape is identical across Task 1 (validation), Task 3 (`AgenticCrawlRequest.credentials`), Task 4 (`run_crawl_credentialed(credentials=)`), Task 5 (`credentials_apply_to_target`, `default_run_crawl_credentialed_fn`). `run_crawl_credentialed_fn(target, scope=, credentials=)` signature matches between Task 4's adapter and Task 5's default fn + injected test fake.
- Fail-open verified per task: absent credentials leaves every existing path unchanged; adapter + node degrade to empty manifest / reduced coverage on any error.
