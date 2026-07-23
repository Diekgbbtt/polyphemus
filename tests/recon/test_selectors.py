from polymerhus.recon.domain.selectors import apply_selector, selector_matches
from polymerhus.recon.domain.types import AssetSelector

JS = AssetSelector(field="path", op="ends_with", values=[".js", ".mjs"])


def test_ends_with_matches_js_and_mjs():
    assert selector_matches({"path": "/static/app.js"}, JS)
    assert selector_matches({"path": "/x/mod.mjs"}, JS)


def test_ends_with_rejects_non_js():
    assert not selector_matches({"path": "/style.css"}, JS)
    assert not selector_matches({"path": "/api/v1/users"}, JS)


def test_missing_or_nonstring_field_is_false_not_raise():
    assert not selector_matches({}, JS)
    assert not selector_matches({"path": None}, JS)
    assert not selector_matches({"path": 3}, JS)


def test_starts_with_and_contains_and_equals():
    assert selector_matches({"path": "/api/x"}, AssetSelector(field="path", op="starts_with", values=["/api"]))
    assert selector_matches({"path": "/a/upload/x"}, AssetSelector(field="path", op="contains", values=["/upload/"]))
    assert selector_matches({"method": "POST"}, AssetSelector(field="method", op="equals", values=["POST", "PUT"]))
    assert not selector_matches({"method": "GET"}, AssetSelector(field="method", op="equals", values=["POST"]))


def test_apply_selector_filters_list():
    assets = [
        {"path": "/a.js"},
        {"path": "/b.css"},
        {"path": "/c.mjs"},
        {"path": "/d"},
    ]
    out = apply_selector(assets, JS)
    assert [a["path"] for a in out] == ["/a.js", "/c.mjs"]


def test_apply_selector_none_is_passthrough():
    assets = [{"path": "/a.js"}, {"path": "/b.css"}]
    out = apply_selector(assets, None)
    assert out == assets
    assert out is not assets  # copy, not alias
