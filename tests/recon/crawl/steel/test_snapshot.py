"""Seam under test: the compact CLI snapshot parser and the form projection.

Spec: `docs/design/steel-crawl-spec.md` sections 2.3 (I2), 5, and 8.1.

The CLI's compact snapshot is the candidate surface: it carries the document
refs the action verbs accept, the role, the accessible name, the link URL, and
the control states. It does not carry raw HTML attributes (a form's action and
method, a field's name and type), so the real page factory merges a small JS
form projection into the tree as synthetic form nodes. A synthetic node names
its CSS selector explicitly; a snapshot node keeps its `@ref`.
"""
from __future__ import annotations

from polymerhus.recon.crawl.steel.enumerate import ElementMap, ElementType
from polymerhus.recon.crawl.steel.snapshot import (
    FormProjection,
    ProjectedField,
    merge_form_projections,
    parse_compact_snapshot,
)
from polymerhus.recon.crawl.steel.state import BrowserState

BASE = "http://t-1618c524.target"

SNAPSHOT = """- link "SIYUCMS" [ref=e105, url=http://t-1618c524.target/]
- textbox "Search here..." [ref=e119]
- button "" [ref=e120]
- checkbox "Remember" [checked=true, ref=e121]
- heading "WHY US ?" [level=3, ref=e57]
  - link "查看更多" [ref=e58, url=http://t-1618c524.target/index/information.html]
- generic "counter" [ref=e59] clickable [cursor:pointer, onclick]
- link "weibo" [ref=e60, url=https://weibo.com/]
"""


def test_the_parser_keeps_refs_names_urls_and_control_states():
    roots = parse_compact_snapshot(SNAPSHOT, base_url=BASE)

    assert [node.tag for node in roots] == [
        "a",
        "input",
        "button",
        "input",
        "h3",
        "div",
        "a",
    ]
    assert roots[0].ref == "e105"
    assert roots[0].attributes["href"] == "http://t-1618c524.target/"
    assert roots[1].attributes["type"] == "text"
    assert roots[1].name == "Search here..."
    assert roots[3].attributes["type"] == "checkbox"
    assert roots[3].attributes["checked"] == "true"
    assert roots[4].attributes["level"] == "3"
    assert roots[4].children[0].ref == "e58"
    assert roots[5].attributes["onclick"] == ""
    assert roots[6].attributes["href"] == "https://weibo.com/"


def test_the_element_map_projects_links_and_clickables_from_the_parsed_tree():
    roots = parse_compact_snapshot(SNAPSHOT, base_url=BASE)
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1",
        url=BASE + "/",
        final_url=BASE + "/",
        title="SIYUCMS",
        snapshot=roots,
    )

    elements = ElementMap().project(roots, page=page, state=state, page_url=BASE + "/")

    link = next(element for element in elements if element.selector == "@e105")
    assert link.element_type is ElementType.LINK
    assert link.change.action == "http://t-1618c524.target/"
    clickable = next(element for element in elements if element.selector == "@e59")
    assert clickable.element_type is ElementType.CLICKABLE
    external = next(element for element in elements if element.selector == "@e60")
    assert external.element_type is ElementType.EXTERNAL_LINK


def _login_form() -> FormProjection:
    return FormProjection(
        selector="form:nth-of-type(1)",
        action=BASE + "/index.php/admin/Login/checkLogin.html",
        method="POST",
        enctype="application/x-www-form-urlencoded",
        fields=(
            ProjectedField(
                name="username",
                type="text",
                label="Username",
                selector="#username",
            ),
            ProjectedField(
                name="password",
                type="password",
                label="Password",
                selector="#password",
            ),
        ),
        submit_selector="#submit",
        submit_text="登 录",
    )


def test_a_form_projection_becomes_a_form_contract_with_css_selectors():
    roots = merge_form_projections(
        parse_compact_snapshot("- textbox \"Username\" [ref=e3]", base_url=BASE),
        [_login_form()],
    )
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_login",
        url=BASE + "/index.php/admin/Login/index.html",
        final_url=BASE + "/index.php/admin/Login/index.html",
        title="Login",
        snapshot=roots,
    )

    elements = ElementMap().project(
        roots,
        page=page,
        state=state,
        page_url=BASE + "/index.php/admin/Login/index.html",
    )

    form = next(element for element in elements if element.element_type is ElementType.FORM)
    assert form.selector == "form:nth-of-type(1)"
    assert form.form is not None
    assert form.form.action == BASE + "/index.php/admin/Login/checkLogin.html"
    assert form.form.method == "POST"
    assert [field.name for field in form.form.fields] == ["username", "password"]
    assert [field.selector for field in form.form.fields] == ["#username", "#password"]
    assert form.form.submit_selector == "#submit"
    assert form.form.submit_text == "登 录"


def test_an_empty_snapshot_is_empty_not_an_error():
    assert parse_compact_snapshot("", base_url=BASE) == ()
