import base64

from polymerhus.recon.control.batching import (
    build_batch_assets,
    build_batch_command,
    build_batches,
    build_jsluice_command,
    bundle_url,
    is_first_party,
    prepare_endpoint_profile_assets,
    reduce_bundles,
)
from polymerhus.recon.control.jobs import JOBS


def _ep(url=None, baseurl=None, path=None):
    a = {}
    if url is not None:
        a["url"] = url
    if baseurl is not None:
        a["baseurl"] = baseurl
    if path is not None:
        a["path"] = path
    return a


# ------------------------------ bundle_url -------------------------------- #
def test_bundle_url_prefers_url_prop():
    assert bundle_url(_ep(url="https://h/a.js", baseurl="https://h", path="/a.js")) == "https://h/a.js"


def test_bundle_url_reconstructs_from_baseurl_and_path():
    assert bundle_url(_ep(baseurl="https://h", path="/x/a.js")) == "https://h/x/a.js"


def test_bundle_url_none_when_underivable():
    assert bundle_url({"method": "GET"}) is None


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
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
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
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
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
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/main.js"]


def test_reduce_dedups_hashless_bundler_marker_basename_across_hosts():
    # A bundler-marker name (vendor/runtime/chunk/polyfill) counts as
    # fingerprinted per the D15 rule even without a hash, so it dedups.
    assets = [
        _ep(url="https://a.houseofhr.com/runtime.js"),
        _ep(url="https://b.houseofhr.com/runtime.js"),
    ]
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/runtime.js"]


def test_reduce_drops_third_party_when_apex_given():
    assets = [
        _ep(url="https://a.houseofhr.com/app.js"),
        _ep(url="https://assets.allegrostatic.com/lib.js"),
    ]
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
    assert out == ["https://a.houseofhr.com/app.js"]


def test_reduce_keeps_all_when_no_apex():
    assets = [_ep(url="https://a/x.js"), _ep(url="https://b/y.js")]
    assert reduce_bundles(assets, apex_registrable=None) == ["https://a/x.js", "https://b/y.js"]


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


def test_build_batches_empty():
    assert build_batches([], max_pods=20) == []


# -------------------------- build_batch_assets --------------------------- #
def test_build_batch_assets_wraps_batches_and_caps_pods():
    assets = [_ep(url=f"https://h.houseofhr.com/b{i}.js") for i in range(50)]
    out = build_batch_assets(assets, apex_registrable="houseofhr.com", max_pods=20)
    assert len(out) == 20  # never exceeds the pod budget
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
