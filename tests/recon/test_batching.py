import base64

from agent.recon.batching import (
    build_batch_assets,
    build_batch_command,
    build_batches,
    build_jsluice_command,
    bundle_url,
    is_first_party,
    reduce_bundles,
)
from agent.recon.jobs import JOBS


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
def test_reduce_dedups_exact_url_and_basename_across_hosts():
    assets = [
        _ep(url="https://a.houseofhr.com/static/app.4f3a.js"),
        _ep(url="https://a.houseofhr.com/static/app.4f3a.js"),  # exact dup
        _ep(url="https://b.houseofhr.com/static/app.4f3a.js"),  # same basename, other host
        _ep(url="https://a.houseofhr.com/static/vendor.9c1d.js"),
    ]
    out = reduce_bundles(assets, apex_registrable="houseofhr.com")
    assert out == [
        "https://a.houseofhr.com/static/app.4f3a.js",
        "https://a.houseofhr.com/static/vendor.9c1d.js",
    ]


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
