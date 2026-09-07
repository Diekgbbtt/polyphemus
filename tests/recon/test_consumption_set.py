"""Consumption-set derivation (unified) for #37 - arjun's naive input set.

The recon job agent maps each job's input assets into pod inputs through ONE
derivation - `batching.derive_consumption_set` - driven by the per-job
`JobSpec.consumption` options (option B, operator ruling 2026-09-07). This
replaces the accreted if/elif chain in `default_preprocess_fn` (one bespoke
branch per consumer + a silent 1:1 fallback arjun fell through): jsluice,
httpx_reprofile, kiterunner keep byte-identical behavior (equivalence tests
below pin the legacy building-block outputs as oracles), and arjun finally
gets a designed input set - route-cluster dedup + malformed-path exclusion +
restapi-first ordering, still one pod per surviving endpoint.

Scope notes (grilling record, operator-confirmed):
- 404/403/401 responses are KEPT: a 404 on a crawled endpoint means the
  request shape is wrong - exactly where the job-specific agent must reason
  (Q6 ruling). The derivation selects WHAT to probe; #208's request-shape
  adaptation decides what each endpoint IS.
- `is_malformed_concat_path` catches JS-concat/template junk ONLY. Katana
  `-aff` mangling artifacts (`/EXPRindex.php`, `/.json`) are NOT matched by
  the gate predicate - they belong to the separate katana upstream ticket
  (grey point 8) and are deliberately KEPT here (recall bias).
- Repeat-signature suppression is DEFERRED (no parameter-set plumbing, Q7).
- Profile preference is ORDERING only, never exclusion (corrected record 2):
  `webapp` endpoints are still probed, after `restapi` ones.

Pure + deterministic throughout: no Neo4j, no LLM, no gateway.
"""
from polymerhus.recon.control import batching
from polymerhus.recon.control import job_agent as ja
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.types import ConsumptionOptions, JobSpec


def _ep(path, **kw):
    base = {"url": f"https://h{path}", "baseurl": "https://h", "path": path,
            "method": "GET"}
    base.update(kw)
    return base


# --- ConsumptionOptions defaults: the plain-job no-op -------------------------

def test_consumption_defaults_are_noop():
    opts = ConsumptionOptions()
    assert opts.route_dedup is False
    assert opts.materialise_root is False
    assert opts.skip_profiled is False
    assert opts.drop_malformed is False
    assert opts.order_restapi_first is False
    assert opts.pack == "none"


def test_legacy_dispatch_flags_are_views_of_consumption():
    assert JOBS["jsluice"].batch is True
    assert JOBS["jsluice"].endpoint_profiling is False
    assert JOBS["httpx_reprofile"].endpoint_profiling is True
    assert JOBS["httpx_reprofile"].batch is False
    assert JOBS["kiterunner"].api_scope is True
    plain = JobSpec(tool="katana", skill="crawl", command_template="k",
                    produces=["Endpoint"], consumes="BaseURL")
    assert plain.batch is False
    assert plain.endpoint_profiling is False
    assert plain.api_scope is False


def test_arjun_declares_param_discovery_consumption():
    job = JOBS["arjun"]
    assert job.consumes == "Endpoint"
    assert job.consumes_where is None  # profile is ordering, never exclusion
    assert job.use_auth is True  # P5: the auth channel is untouched
    assert job.consumption.route_dedup is True
    assert job.consumption.materialise_root is False  # probing `/` is low-value
    assert job.consumption.skip_profiled is False  # a profile is not parameters
    assert job.consumption.drop_malformed is True
    assert job.consumption.order_restapi_first is True
    assert job.consumption.pack == "none"  # still one pod per endpoint
    assert job.batch is False
    assert job.endpoint_profiling is False
    assert job.api_scope is False


# --- route-cluster dedup (the shared P1 seam) ----------------------------------

def test_derive_route_dedup_collapses_dynamic_templates():
    assets = [_ep("/users/1"), _ep("/users/2"), _ep("/orders")]
    out = batching.derive_consumption_set(
        assets, consumption=ConsumptionOptions(route_dedup=True),
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/users/1", "/orders"]


def test_derive_route_dedup_keeps_method_and_host_distinct():
    assets = [
        _ep("/users/1", method="GET"),
        _ep("/users/1", method="POST"),
        {"url": "https://other/users/1", "baseurl": "https://other",
         "path": "/users/1", "method": "GET"},
    ]
    out = batching.derive_consumption_set(
        assets, consumption=ConsumptionOptions(route_dedup=True),
        max_pods=20, set_cap=500,
    )
    assert len(out) == 3


def test_derive_dedup_is_stable_first_seen_order():
    assets = [_ep("/b"), _ep("/users/2"), _ep("/a"), _ep("/users/1")]
    out = batching.derive_consumption_set(
        assets, consumption=ConsumptionOptions(route_dedup=True),
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/b", "/users/2", "/a"]


# --- malformed/junk exclusion (P3: the gate's predicate, never a copy) ---------

def test_derive_drop_malformed_uses_gate_predicate():
    assets = [
        _ep("/api/users"),
        _ep("/'+_(i[8])+'"),  # JS string-concat fragment: dropped
        _ep("/i.document.do"),  # minified member-expression segment: dropped
        _ep("/{{href}}"),  # template placeholder: dropped
    ]
    out = batching.derive_consumption_set(
        assets, consumption=ConsumptionOptions(drop_malformed=True),
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/api/users"]


def test_derive_keeps_katana_aff_artifacts_for_the_upstream_ticket():
    # `/EXPRindex.php` and `/.json` are katana `-aff` mangling artifacts, NOT
    # JS-concat fragments: the gate predicate does not match them, and this
    # derivation must not invent its own URL-shape verdict (corrected record
    # 2). They stay for the separate katana ticket; this test pins that the
    # malformed filter does not silently swallow them.
    assets = [_ep("/EXPRindex.php"), _ep("/.json"), _ep("/api/users")]
    out = batching.derive_consumption_set(
        assets,
        consumption=ConsumptionOptions(route_dedup=True, drop_malformed=True),
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/EXPRindex.php", "/.json", "/api/users"]


# --- restapi-first ordering (ordering only, never exclusion) -------------------

def test_derive_restapi_first_orders_without_excluding():
    assets = [
        _ep("/page", profile="webapp"),
        _ep("/api/orders", profile="restapi"),
        _ep("/about"),  # unprofiled: kept, after restapi
        _ep("/api/users", profile="restapi"),
        _ep("/gql", profile="graphql_api"),  # not restapi: kept, after restapi
    ]
    out = batching.derive_consumption_set(
        assets,
        consumption=ConsumptionOptions(
            route_dedup=True, drop_malformed=True, order_restapi_first=True),
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == [
        "/api/orders", "/api/users", "/page", "/about", "/gql"]
    # every input survives: ordering, never exclusion (corrected record 2)
    assert len(out) == len(assets)


# --- arjun variant semantics ----------------------------------------------------

def test_derive_arjun_never_materialises_root():
    assets = [_ep("/api/users")]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/api/users"]  # no synthetic `/`


def test_derive_arjun_keeps_real_root_when_crawled():
    assets = [_ep("/"), _ep("/api/users")]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    # no restapi profiles here: stable input order survives, nothing synthesised
    assert [a["path"] for a in out] == ["/", "/api/users"]


def test_derive_arjun_keeps_profiled_endpoints():
    # A profile is orthogonal to parameter discovery: skip_profiled is False.
    assets = [_ep("/api/a", profile="restapi"), _ep("/b", profile="webapp")]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    assert len(out) == 2


def test_derive_arjun_keeps_error_statuses_per_q6():
    # Q6 ruling: 404/403/401 are kept - the request shape may be wrong, and
    # that is exactly where probing (arjun + #208's adaptation) must go.
    assets = [
        _ep("/a", status_code=404),
        _ep("/b", status_code=403),
        _ep("/c", status_code=401),
        _ep("/d", status_code=200),
        _ep("/e"),  # never probed (jsluice/katana-minted): kept by recall bias
    ]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    assert len(out) == 5


def test_derive_is_deterministic_and_pure():
    assets = [_ep("/users/2"), _ep("/b"), _ep("/users/1"),
              _ep("/api/x", profile="restapi")]
    first = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500)
    second = batching.derive_consumption_set(
        [dict(a) for a in assets], consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500)
    assert first == second
    assert assets[0]["path"] == "/users/2"  # input untouched


def test_derive_empty_is_empty():
    assert batching.derive_consumption_set(
        [], consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500) == []


# --- legacy equivalence: the unify must not move the three working jobs --------

def test_derive_batches_variant_matches_legacy_build_batch_assets():
    assets = [{"path": f"/b{i}.js", "url": f"https://a.houseofhr.com/b{i}.js"}
              for i in range(60)]
    assert batching.derive_consumption_set(
        assets, consumption=JOBS["jsluice"].consumption,
        apex_registrable="houseofhr.com", max_pods=8, set_cap=500,
    ) == batching.build_batch_assets(
        assets, apex_registrable="houseofhr.com", max_pods=8)


def test_derive_reprofile_variant_matches_legacy_prepare():
    assets = [
        _ep("/api/v1/users/1"), _ep("/api/v1/users/2"),
        _ep("/api/v1/orders", profile="restapi"),
    ]
    assert batching.derive_consumption_set(
        assets, consumption=JOBS["httpx_reprofile"].consumption,
        max_pods=20, set_cap=500,
    ) == [{"endpoints": batching.prepare_endpoint_profile_assets(assets)[:500]}]


def test_derive_scan_targets_variant_matches_legacy():
    assets = [_ep("/api/v1/users"), _ep("/api/v1/orders")]
    assert batching.derive_consumption_set(
        assets, consumption=JOBS["kiterunner"].consumption,
        max_pods=20, set_cap=500,
    ) == batching.build_api_scope_assets(assets)


def test_derive_one_pod_set_cap_bounds_probe_set():
    assets = [_ep(f"/p{i}") for i in range(10)]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["httpx_reprofile"].consumption,
        max_pods=20, set_cap=3,
    )
    assert len(out) == 1
    assert len(out[0]["endpoints"]) == 3  # C7: the cap bounds the SET


# --- preprocess: the unified single call ---------------------------------------

def test_preprocess_arjun_derives_clusters_not_endpoints(monkeypatch):
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    monkeypatch.setattr(ja, "MAX_PODS", 20)
    assets = [_ep("/users/1"), _ep("/users/2"),
              _ep("/api/orders", profile="restapi")]
    pod_inputs = ja.default_preprocess_fn(
        assets, JOBS["arjun"], {"auth_context": {"cookies": "a=b"}}, "")
    # two route clusters -> two pods, not three endpoints; restapi first
    assert [pi["input_asset"]["path"] for pi in pod_inputs] == [
        "/api/orders", "/users/1"]
    # P5: the auth channel rides through to every pod
    assert all(pi["extra"]["auth_context"] == {"cookies": "a=b"}
               for pi in pod_inputs)


def test_preprocess_arjun_empty_set_is_empty_pass():
    pod_inputs = ja.default_preprocess_fn([], JOBS["arjun"], {}, "")
    assert pod_inputs == []


def test_preprocess_fail_open_on_derivation_error(monkeypatch, caplog):
    import logging

    from polymerhus.recon.control import batching as batching_module

    def _boom(*args, **kwargs):
        raise RuntimeError("dedup exploded")

    monkeypatch.setattr(batching_module, "derive_consumption_set", _boom)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 2)
    assets = [_ep("/a"), _ep("/b"), _ep("/c")]
    with caplog.at_level(logging.WARNING, logger="polymerhus.recon.control.job_agent"):
        pod_inputs = ja.default_preprocess_fn(assets, JOBS["arjun"], {}, "")
    # P6: degrade to the previous behavior (capped raw 1:1), never raise
    assert [pi["input_asset"]["path"] for pi in pod_inputs] == ["/a", "/b"]
    assert "derive_consumption_set failed" in caplog.text


def test_preprocess_plain_job_unchanged(monkeypatch):
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    job = JobSpec(tool="katana", skill="crawl", command_template="k",
                  produces=["Endpoint"], consumes="BaseURL")
    pod_inputs = ja.default_preprocess_fn(
        [{"url": "https://a"}, {"url": "https://b"}], job, {"project_id": "p1"}, "")
    assert [pi["input_asset"]["url"] for pi in pod_inputs] == [
        "https://a", "https://b"]


# --- fail-open fallback stays dispatch-compatible (review finding) --------------

def test_preprocess_fallback_packs_one_pod_shape(monkeypatch):
    from polymerhus.recon.control import batching as batching_module

    def _boom(*args, **kwargs):
        raise RuntimeError("dedup exploded")

    monkeypatch.setattr(batching_module, "derive_consumption_set", _boom)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    assets = [_ep("/a"), _ep("/b")]
    pod_inputs = ja.default_preprocess_fn(assets, JOBS["httpx_reprofile"], {}, "")
    # the #208 TOTAL seam demands the `endpoints` key: the fallback packs it
    assert len(pod_inputs) == 1
    assert pod_inputs[0]["input_asset"]["endpoints"] == assets


def test_preprocess_fallback_packs_batch_shape(monkeypatch):
    from polymerhus.recon.control import batching as batching_module

    def _boom(*args, **kwargs):
        raise RuntimeError("dedup exploded")

    monkeypatch.setattr(batching_module, "derive_consumption_set", _boom)
    monkeypatch.setattr(ja, "MAX_JOB_ASSETS", 500)
    assets = [{"url": "https://a.houseofhr.com/x.js", "path": "/x.js"}]
    pod_inputs = ja.default_preprocess_fn(
        assets, JOBS["jsluice"], {"apex_registrable": "houseofhr.com"}, "")
    assert len(pod_inputs) == 1
    assert pod_inputs[0]["input_asset"]["batch"] == [
        "https://a.houseofhr.com/x.js"]


# --- independent oracles: hand-computed, never calling the shared blocks --------
# (Review finding: the equivalence tests above pin wiring only, since derive
# calls the very functions they compare against. These pin BEHAVIOR with
# literal expectations derived by hand from the documented rules.)

def test_independent_oracle_jsluice_batching():
    a_app = "https://a.houseofhr.com/app.4f3a2b1c.js"
    a_main = "https://a.houseofhr.com/main.js"
    b_main = "https://b.houseofhr.com/main.js"
    assets = [
        {"url": a_app, "path": "/app.4f3a2b1c.js"},
        {"url": "https://b.houseofhr.com/app.4f3a2b1c.js",
         "path": "/app.4f3a2b1c.js"},  # same fingerprinted basename: dropped
        {"url": a_main, "path": "/main.js"},
        {"url": b_main, "path": "/main.js"},  # generic: kept per host
    ]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["jsluice"].consumption,
        apex_registrable="houseofhr.com", max_pods=2, set_cap=500,
    )
    assert out == [{"batch": [a_app, b_main]}, {"batch": [a_main]}]


def test_independent_oracle_reprofile_one_pod():
    u1 = _ep("/users/1")
    orders = _ep("/orders")
    out = batching.derive_consumption_set(
        [u1, _ep("/users/2"), orders],
        consumption=JOBS["httpx_reprofile"].consumption,
        max_pods=20, set_cap=500,
    )
    assert out == [{"endpoints": [
        u1, orders,
        {"url": "https://h/", "baseurl": "https://h", "path": "/",
         "method": "GET"},
    ]}]


def test_independent_oracle_kiterunner_scan_targets():
    assets = [
        _ep("/api/v1/users", profile="restapi"),
        _ep("/api/v1/orders", profile="restapi"),
        _ep("/api/v2/items", profile="restapi"),
        _ep("/internal/stats", profile="restapi"),
    ]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["kiterunner"].consumption,
        max_pods=20, set_cap=500,
    )
    # last-noun cut: /api/v1/* + /api/v2/* -> /api/ (x3); /internal/* (x1)
    assert out == [{"url": "https://h/api/"}, {"url": "https://h/internal/"}]


# --- AC4: measured reduction on a representative surface -------------------------
# A moodique-shaped 500-endpoint population (PrestaShop-style statics, dynamic
# pairs, concat-fragment junk, -aff artifacts, restapi-profiled APIs, POST
# endpoints). The ticket's acceptance criterion in deterministic form: the
# derived set is much smaller, and every genuinely parameter-bearing endpoint
# (profiled, query-bearing, or non-GET) survives by identity.

def _representative_surface():
    assets = []
    for i in range(140):  # dynamic pairs on distinct routes -> one cluster each
        assets.append(_ep(f"/shop/cat-{i}/product/{i}"))
        assets.append(_ep(f"/shop/cat-{i}/product/{i + 1000}"))
    for i in range(100):  # distinct statics
        assets.append(_ep(f"/it/content-{i}"))
    for i in range(40):  # concat-fragment junk -> dropped
        assets.append(_ep(f"/'+_(x[{i}])+'"))
    for p in ["/EXPRindex.php", "/.json", "/old.php", "/backup2019.zip",
              "/page(2).php", "/file[1].php", "/data{set}.php",
              "/weird+name.php", "/100%.php", "/a;b.php"]:
        assets.append(_ep(p))  # -aff-style artifacts: kept (upstream ticket)
    for i in range(50):  # restapi-profiled APIs
        assets.append(_ep(f"/api/v1/res-{i}", profile="restapi"))
    for i in range(20):  # POST endpoints (body-carried parameters)
        assets.append(_ep(f"/form/submit-{i}", method="POST"))
    assert len(assets) == 500
    return assets


def test_measured_reduction_on_representative_surface():
    assets = _representative_surface()
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    paths = [a["path"] for a in out]
    # 500 -> 320: 140 clusters + 100 statics + 10 artifacts + 50 apis + 20 posts
    assert len(out) == 320, len(out)
    # junk gone, artifacts kept
    assert not any("+_(" in p for p in paths)
    assert "/EXPRindex.php" in paths and "/.json" in paths
    # restapi-first: the whole API block leads the ordered set
    assert [a.get("profile") for a in out[:50]] == ["restapi"] * 50
    # every genuinely parameter-bearing endpoint survives by identity
    by_path = {a["path"]: a for a in out}
    for i in range(50):
        assert by_path[f"/api/v1/res-{i}"]["profile"] == "restapi"
    for i in range(20):
        assert by_path[f"/form/submit-{i}"]["method"] == "POST"
    # dynamic pairs collapsed to their first-seen representative
    for i in range(140):
        assert f"/shop/cat-{i}/product/{i}" in by_path
        assert f"/shop/cat-{i}/product/{i + 1000}" not in by_path


# --- baseurl-less assets: the recorded third exclusion --------------------------

def test_derive_drops_assets_with_no_derivable_baseurl():
    assets = [{"path": "/orphan"}, _ep("/real")]
    out = batching.derive_consumption_set(
        assets, consumption=JOBS["arjun"].consumption,
        max_pods=20, set_cap=500,
    )
    assert [a["path"] for a in out] == ["/real"]
