import base64

from polymerhus.recon.control.batching import (
    build_arjun_command,
    build_batch_assets,
    build_batch_command,
    build_batches,
    build_jsluice_command,
    endpoint_url,
    is_first_party,
    prepare_endpoint_profile_assets,
    reduce_endpoints,
)
from polymerhus.recon.control.jobs import JOBS


def _ep(url=None, baseurl=None, path=None, method=None):
    a = {}
    if url is not None:
        a["url"] = url
    if baseurl is not None:
        a["baseurl"] = baseurl
    if path is not None:
        a["path"] = path
    if method is not None:
        a["method"] = method
    return a


# ------------------------------ endpoint_url -------------------------------- #
def test_endpoint_url_prefers_url_prop():
    assert endpoint_url(_ep(url="https://h/a.js", baseurl="https://h", path="/a.js")) == "https://h/a.js"


def test_endpoint_url_reconstructs_from_baseurl_and_path():
    assert endpoint_url(_ep(baseurl="https://h", path="/x/a.js")) == "https://h/x/a.js"


def test_endpoint_url_none_when_underivable():
    assert endpoint_url({"method": "GET"}) is None


# ---------------------------- first-party -------------------------------- #
def test_is_first_party_matches_subdomain_of_apex():
    assert is_first_party("https://mycv-uat.houseofhr.com/app.js", "houseofhr.com")
    assert is_first_party("https://houseofhr.com/app.js", "houseofhr.com")


def test_is_first_party_rejects_third_party_cdn():
    assert not is_first_party("https://assets.allegrostatic.com/x.js", "houseofhr.com")
    assert not is_first_party("https://www.googletagmanager.com/gtm.js", "houseofhr.com")


# ---------------------------- reductions --------------------------------- #
def test_reduce_dedups_exact_url_and_fingerprinted_basename_across_hosts():
    assets = [
        _ep(url="https://a.houseofhr.com/static/app.a1b2c3d4.js"),
        _ep(url="https://a.houseofhr.com/static/app.a1b2c3d4.js"),  # exact dup
        _ep(url="https://b.houseofhr.com/static/app.a1b2c3d4.js"),  # same fp basename, other host
        _ep(url="https://a.houseofhr.com/static/vendor.9c1d2e3f.js"),
    ]
    out = reduce_endpoints(assets, apex_registrable="houseofhr.com")
    assert out == [
        "https://a.houseofhr.com/static/app.a1b2c3d4.js",
        "https://a.houseofhr.com/static/vendor.9c1d2e3f.js",
    ]


def test_reduce_keeps_generic_basename_per_host_across_hosts():
    # main.js has no content hash, so two hosts' copies may genuinely differ -
    # both survive (recall-safe); the pod's md5 source dedup is the finer net.
    assets = [
        _ep(url="https://a.houseofhr.com/main.js"),
        _ep(url="https://b.houseofhr.com/main.js"),
        _ep(url="https://c.houseofhr.com/index.js"),
    ]
    out = reduce_endpoints(assets, apex_registrable="houseofhr.com")
    assert out == [
        "https://a.houseofhr.com/main.js",
        "https://b.houseofhr.com/main.js",
        "https://c.houseofhr.com/index.js",
    ]


def test_reduce_generic_basename_still_dedups_exact_url():
    # The exact-URL dedup is unchanged: the same main.js on ONE host collapses.
    assets = [
        _ep(url="https://a.houseofhr.com/main.js"),
        _ep(url="https://a.houseofhr.com/main.js"),
    ]
    out = reduce_endpoints(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/main.js"]


def test_reduce_dedups_hashless_bundler_marker_basename_across_hosts():
    # A bundler-marker name (vendor/runtime/chunk/polyfill) counts as
    # fingerprinted per the D15 rule even without a hash, so it dedups.
    assets = [
        _ep(url="https://a.houseofhr.com/runtime.js"),
        _ep(url="https://b.houseofhr.com/runtime.js"),
    ]
    out = reduce_endpoints(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/runtime.js"]


def test_reduce_drops_third_party_when_apex_given():
    assets = [
        _ep(url="https://a.houseofhr.com/app.js"),
        _ep(url="https://assets.allegrostatic.com/lib.js"),
    ]
    out = reduce_endpoints(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/app.js"]


def test_reduce_keeps_all_when_no_apex():
    assets = [_ep(url="https://a/x.js"), _ep(url="https://b/y.js")]
    assert reduce_endpoints(assets, apex_registrable=None) == ["https://a/x.js", "https://b/y.js"]


# ---------------------------- build_batches ------------------------------ #
def test_build_batches_respects_max_pods_and_balances():
    items = [f"u{i}" for i in range(10)]
    batches = build_batches(items, max_pods=3)
    assert len(batches) == 3
    assert sum(len(b) for b in batches) == 10
    assert max(len(b) for b in batches) - min(len(b) for b in batches) <= 1
    # every item appears exactly once
    flat = [x for b in batches for x in b]
    assert sorted(flat) == sorted(items)


def test_build_batches_fewer_items_than_pods_gives_one_each():
    batches = build_batches(["a", "b"], max_pods=20)
    assert batches == [["a"], ["b"]]


def test_build_batches_bounded_chunks_by_max_batch_size():
    # arjun #37: each pod's batch must be small enough to finish under the exec
    # timeout, so the chunk size (not the pod count) is the bound.
    items = [f"u{i}" for i in range(10)]
    batches = build_batches(items, max_pods=5, max_batch_size=4)
    assert [len(b) for b in batches] == [4, 4, 2]
    assert [x for b in batches for x in b] == items


def test_build_batches_bounded_is_one_chunk_when_under_the_size():
    batches = build_batches(["a", "b", "c"], max_pods=5, max_batch_size=4)
    assert batches == [["a", "b", "c"]]


def test_build_batches_empty():
    assert build_batches([], max_pods=20) == []


def test_build_batches_keeps_one_origin_in_one_pod():
    # Load-bearing for the runtime-baseURL chaining (2026-10-16): a prefix
    # discovered in one bundle of an origin must reach the pod scanning that
    # origin's other bundles (the lazy chunks), or chaining `/login` ->
    # `/api/login` is nondeterministic (#185 ADR deferral).
    items = [f"https://h.example.com/b{i}.js" for i in range(9)]
    assert build_batches(items, max_pods=8) == [items]


def test_build_batches_distributes_origins_round_robin():
    a = [f"https://a.example.com/b{i}.js" for i in range(3)]
    b = [f"https://b.example.com/b{i}.js" for i in range(3)]
    c = [f"https://c.example.com/b{i}.js" for i in range(3)]
    batches = build_batches(a + b + c, max_pods=2)
    # Whole origins, round-robin across the pod budget - never split.
    assert batches == [a + c, b]


def test_build_batches_oversized_origin_degrades_to_round_robin(monkeypatch):
    # Past `_ORIGIN_GROUP_MAX` a single origin could outlive EXEC_TIMEOUT_S in
    # one pod, so it degrades to per-item units: today's exact round-robin, no
    # chaining. The pod must never time out and lose the whole batch.
    monkeypatch.setattr("polymerhus.recon.control.batching._ORIGIN_GROUP_MAX", 4)
    items = [f"https://big.example.com/b{i}.js" for i in range(10)]
    batches = build_batches(items, max_pods=3)
    assert [len(b) for b in batches] == [4, 3, 3]
    assert sorted(x for b in batches for x in b) == sorted(items)


# -------------------------- build_batch_assets --------------------------- #
def test_build_batch_assets_wraps_batches_and_caps_pods():
    assets = [_ep(url=f"https://h.houseofhr.com/b{i}.js") for i in range(50)]
    out = build_batch_assets(assets, apex_registrable="houseofhr.com", max_pods=20)
    # One origin stays in ONE pod (the chaining contract), so the pod budget
    # is an upper bound - `<=` - not a target.
    assert len(out) <= 20
    assert all("batch" in a and a["batch"] for a in out)
    total = sum(len(a["batch"]) for a in out)
    assert total == 50


# ------------------------- command construction -------------------------- #
def test_build_jsluice_command_embeds_runner_and_quoted_urls():
    urls = ["https://h/a.js", "https://h/b c.js"]  # second has a space -> must quote
    cmd = build_jsluice_command(urls)
    assert cmd.startswith("echo ")
    assert "| base64 -d | python3 - " in cmd
    # the embedded blob decodes back to the real runner script source
    blob = cmd.split("echo ", 1)[1].split(" |", 1)[0]
    decoded = base64.b64decode(blob).decode()
    assert "def scan_bundles(" in decoded
    # both URLs present, the spaced one shell-quoted
    assert "https://h/a.js" in cmd
    assert "'https://h/b c.js'" in cmd


def test_build_batch_command_dispatches_jsluice():
    cmd = build_batch_command(JOBS["jsluice"], ["https://h/a.js"])
    assert "python3 -" in cmd


def test_build_arjun_command_seeds_imports_and_cats():
    urls = ["https://h/account", "https://h/api"]
    cmd = build_arjun_command(urls, session_id="s1", extra={})
    # The zero-findings seed: arjun writes no `-oJ` file on a clean batch, so a
    # bare `&& cat` would fail the pod (the AMV-14 trap).
    assert "printf '{}' > /work/s1/arjun.json" in cmd
    # The URL list is base64-embedded and decoded into the `-i` import file.
    assert "| base64 -d > /work/s1/arjun_urls.txt" in cmd
    assert "arjun -i /work/s1/arjun_urls.txt --rate-limit 5" in cmd
    assert "-oJ /work/s1/arjun.json" in cmd
    assert ">/dev/null" in cmd  # arjun's `[!]` progress must not reach the parser
    assert cmd.rstrip().endswith("cat /work/s1/arjun.json")
    blob = cmd.split("echo ", 1)[1].split(" |", 1)[0]
    assert base64.b64decode(blob).decode() == "https://h/account\nhttps://h/api"


def test_build_arjun_command_serializes_auth_headers():
    cmd = build_arjun_command(
        ["https://h/api"],
        session_id="s2",
        extra={"auth_context": {"Authorization": "Bearer tok"}},
    )
    assert "--headers" in cmd


def test_build_batch_command_dispatches_arjun():
    cmd = build_batch_command(JOBS["arjun"], ["https://h/api"], session_id="s3", extra={})
    assert "arjun -i /work/s3/arjun_urls.txt" in cmd


def test_build_webpack_chunks_command_embeds_runner_and_quoted_urls():
    urls = ["https://h/static/js/manifest.847c.js", "https://h/a b.js"]
    cmd = build_batch_command(JOBS["webpack_chunks"], urls)
    assert cmd.startswith("echo ")
    assert "| base64 -d | python3 - " in cmd
    blob = cmd.split("echo ", 1)[1].split(" |", 1)[0]
    decoded = base64.b64decode(blob).decode()
    assert "def scan_bundles(" in decoded
    assert "https://h/static/js/manifest.847c.js" in cmd
    assert "'https://h/a b.js'" in cmd


def test_build_batch_command_unknown_tool_raises():
    import pytest

    with pytest.raises(ValueError):
        build_batch_command(JOBS["katana"], ["https://h/a.js"])


# ---------------- prepare_endpoint_profile_assets (D16 split) ---------------- #

def test_prepare_materializes_a_root_endpoint_per_baseurl():
    # A crawler-minted BaseURL reached only via a deep path has no root `/`
    # Endpoint; the profiling pass must synthesise one so the root is probed and
    # BaseURL.profile (the root mirror) is set.
    out = prepare_endpoint_profile_assets(
        [_ep(url="https://h/api/v1/x", baseurl="https://h", path="/api/v1/x")]
    )
    paths = {(a.get("baseurl"), a.get("path")) for a in out}
    assert ("https://h", "/") in paths          # synthesised root
    assert ("https://h", "/api/v1/x") in paths   # original survives
    root = next(a for a in out if a.get("path") == "/")
    assert root["url"] == "https://h/"


def test_prepare_does_not_duplicate_an_existing_root():
    out = prepare_endpoint_profile_assets(
        [
            _ep(url="https://h/", baseurl="https://h", path="/"),
            _ep(url="https://h/api/x", baseurl="https://h", path="/api/x"),
        ]
    )
    roots = [a for a in out if a.get("baseurl") == "https://h" and a.get("path") == "/"]
    assert len(roots) == 1


def test_prepare_dedups_dynamic_path_segments_per_host():
    # /users/1 and /users/2 are the same route template; probing both is wasted
    # requests on a constrained host -> collapse to one probe.
    out = prepare_endpoint_profile_assets(
        [
            _ep(url="https://h/users/1", baseurl="https://h", path="/users/1"),
            _ep(url="https://h/users/2", baseurl="https://h", path="/users/2"),
        ]
    )
    non_root = [a for a in out if a.get("path") != "/"]
    assert len(non_root) == 1


def test_prepare_keeps_distinct_hosts_separate():
    out = prepare_endpoint_profile_assets(
        [
            _ep(url="https://a/api/x", baseurl="https://a", path="/api/x"),
            _ep(url="https://b/api/x", baseurl="https://b", path="/api/x"),
        ]
    )
    baseurls = {a.get("baseurl") for a in out}
    assert baseurls == {"https://a", "https://b"}
    # each host gets its own synthesised root
    assert sum(1 for a in out if a.get("path") == "/") == 2


def test_prepare_keeps_a_write_route_distinct_from_its_get_twin():
    # #365: the dedup key carries the method, so a GET probe of a path does NOT
    # swallow the POST-hinted route on the same path - the write-probe execs
    # need the POST asset to survive input-prep (white-jotter has both nodes).
    out = prepare_endpoint_profile_assets(
        [
            _ep(url="https://h/api/register", baseurl="https://h",
                path="/api/register", method="GET"),
            _ep(url="https://h/api/register", baseurl="https://h",
                path="/api/register", method="POST"),
        ]
    )
    methods = {(a.get("path"), a.get("method")) for a in out if a.get("path") != "/"}
    assert ("/api/register", "GET") in methods
    assert ("/api/register", "POST") in methods


# -------------------- build_api_scope_assets (D16 split) --------------------- #

def test_build_api_scope_assets_derives_prefix_targets_per_host():
    from polymerhus.recon.control.batching import build_api_scope_assets
    assets = [
        _ep(url="https://h/api/v1/users", baseurl="https://h", path="/api/v1/users"),
        _ep(url="https://h/api/v1/orders", baseurl="https://h", path="/api/v1/orders"),
        _ep(url="https://h/rest/things", baseurl="https://h", path="/rest/things"),
    ]
    out = build_api_scope_assets(assets)
    urls = {a["url"] for a in out}
    assert urls == {"https://h/api/", "https://h/rest/"}


def test_build_api_scope_assets_empty_when_no_endpoints():
    from polymerhus.recon.control.batching import build_api_scope_assets
    assert build_api_scope_assets([]) == []


# -------------- #365 per-method write probe groups + command ---------------- #
# The reprofile pass stays ONE pod over ONE all-GET exec (the #208 shape, byte-
# unchanged); write-hinted routes additionally get ONE `httpx -x <METHOD>` exec
# per hinted method, appended to the same pod command by
# `build_reprofile_write_probes`.

def test_probe_method_groups_partitions_by_hinted_method_in_fixed_order():
    from polymerhus.recon.control.batching import probe_method_groups

    assets = [
        _ep(url="https://h/api/register", method="POST"),
        _ep(url="https://h/api/orders/1", method="put"),  # case-insensitive
        _ep(url="https://h/api/orders/1", method="PATCH"),
        _ep(url="https://h/api/things/1", method="DELETE"),  # mint-only, never probed
        _ep(url="https://h/admin"),  # unhinted -> GET default
        _ep(url="https://h/", method="GET"),
    ]
    groups = probe_method_groups(assets)
    assert list(groups) == ["POST", "PUT", "PATCH"]
    assert groups["POST"] == ["https://h/api/register"]
    assert "DELETE" not in groups  # mutation-bounded: never probed live
    assert "GET" not in groups


def test_probe_method_groups_dedups_urls_within_a_method_first_seen():
    from polymerhus.recon.control.batching import probe_method_groups

    assets = [
        _ep(url="https://h/api/register", method="POST"),
        _ep(baseurl="https://h", path="/api/register", method="POST"),  # same URL
        _ep(url="https://h/a", method="POST"),
    ]
    assert probe_method_groups(assets)["POST"] == [
        "https://h/api/register",
        "https://h/a",
    ]


def test_probe_method_groups_keeps_one_probe_per_hinted_method():
    # One path hinted POST in one bundle and PUT in another keeps BOTH probes:
    # each hint is a candidate the live probe arbitrates.
    from polymerhus.recon.control.batching import probe_method_groups

    groups = probe_method_groups(
        [_ep(url="https://h/x", method="POST"), _ep(url="https://h/x", method="PUT")]
    )
    assert groups == {"POST": ["https://h/x"], "PUT": ["https://h/x"]}


def test_probe_method_groups_empty_for_get_only_set():
    from polymerhus.recon.control.batching import probe_method_groups

    assert probe_method_groups(
        [_ep(url="https://h/"), _ep(url="https://h/x", method="GET")]
    ) == {}


def test_build_reprofile_write_probes_empty_for_get_only_set():
    from polymerhus.recon.control.batching import build_reprofile_write_probes

    assert build_reprofile_write_probes([_ep(url="https://h/")], session_id="s") == ""
    assert build_reprofile_write_probes([], session_id="s") == ""


def test_build_reprofile_write_probes_builds_one_x_exec_per_method_in_order():
    from polymerhus.recon.control.batching import build_reprofile_write_probes
    from polymerhus.recon.control.jobs import REPROFILE_PROBE_FLAGS

    frag = build_reprofile_write_probes(
        [
            _ep(url="https://h/api/register", method="POST"),
            _ep(url="https://h/api/orders/1", method="PUT"),
            _ep(url="https://h/api/orders/1", method="PATCH"),
        ],
        session_id="s9",
    )
    # appended to the all-GET exec, never replacing it
    assert frag.startswith(" && ")
    assert frag.index("-x POST") < frag.index("-x PUT") < frag.index("-x PATCH")
    assert (
        f"httpx -l /work/s9/write_post.txt {REPROFILE_PROBE_FLAGS} -x POST" in frag
    )
    assert "printf '%s\\n' https://h/api/register > /work/s9/write_post.txt" in frag
    assert "cat /work/s9/reprofile_post.json" in frag
    # empty-seed guard per method file (httpx -o may not create it on zero hits)
    assert frag.count("printf '' > /work/s9/reprofile_") == 3


def test_build_reprofile_write_probes_threads_the_auth_flags():
    from polymerhus.recon.control.batching import build_reprofile_write_probes

    frag = build_reprofile_write_probes(
        [_ep(url="https://h/api/register", method="POST")],
        session_id="s",
        extra={"auth_context": {"Authorization": "Bearer tok"}},
    )
    assert "-H 'Authorization: Bearer tok'" in frag
