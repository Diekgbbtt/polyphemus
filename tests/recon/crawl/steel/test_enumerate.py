"""Seam under test: the `ElementMap` projection through fixture DOM snapshots.

Spec: `docs/design/steel-crawl-spec.md` sections 2.3, 6.1, 6.2, 6.3, 6.4, 6.5,
and 6.6; seam 4 of `docs/design/steel-crawl-implementation-plan.md` section 3.
Every test drives the public projection: the closed element type, the channel,
the exclusions, the identity and fingerprint, the change semantics with its
control facts, and the bounded compact projection. Expected values come from the
spec tables and the checked-in fixture pack, never from re-running the mapper.
The structured fixture is adapted to `SnapshotNode` here, in the test, so the
production module never imports a test record.
"""
from __future__ import annotations

from typing import Any

from polymerhus.recon.crawl.steel.enumerate import (
    Channel,
    Element,
    ElementMap,
    ElementType,
    ProjectElementSettings,
    RawSelectorRule,
    SnapshotNode,
    parse_snapshot_tree,
    render_projection,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.fixtures import DomNode, DomSnapshot, load_cli, load_dom


def to_snapshot_node(record: DomNode) -> SnapshotNode:
    """Adapt the fixture's structured DOM record to the production node model."""
    return SnapshotNode(
        tag=record.tag,
        ref=record.ref,
        role=record.role,
        name=record.name,
        text=record.text,
        attributes=dict(record.attributes),
        visible=record.visible,
        children=tuple(to_snapshot_node(child) for child in record.children),
    )


def open_fixture(name: str) -> tuple[tuple[SnapshotNode, ...], PageInstance, BrowserState]:
    """Load one DOM fixture and open it as the current page."""
    dom: DomSnapshot = load_dom(name)
    state = BrowserState()
    page = state.open_page(
        page_visit_id=f"page_{name}",
        url=dom.url,
        final_url=dom.url,
        title=dom.title,
        snapshot=dom,
    )
    return tuple(to_snapshot_node(node) for node in dom.nodes), page, state


def project(name: str, **overrides: Any) -> list[Element]:
    """Project one fixture page with the fields each test does not override."""
    nodes, page, state = open_fixture(name)
    payload: dict[str, Any] = {
        "page": page,
        "state": state,
        "page_url": page.url,
    }
    payload.update(overrides)
    return ElementMap().project(nodes, **payload)


def by_id(elements: list[Element]) -> dict[str, Element]:
    return {element.element_id: element for element in elements}


def node(tag: str, **fields: Any) -> SnapshotNode:
    return SnapshotNode(tag=tag, **fields)


def project_nodes(
    nodes: list[SnapshotNode],
    url: str = "https://example.test/",
    settings: ProjectElementSettings | None = None,
) -> list[Element]:
    state = BrowserState()
    page = state.open_page(page_visit_id="page_1", url=url, final_url=url, snapshot=nodes)
    return ElementMap().project(
        tuple(nodes), page=page, state=state, page_url=url, settings=settings
    )


def test_the_home_snapshot_projects_its_same_origin_and_external_links():
    elements = by_id(project("home"))

    assert elements["e1"].element_type is ElementType.LINK
    assert elements["e1"].channel is Channel.OFFER
    assert elements["e1"].href == "/"
    assert elements["e2"].element_type is ElementType.EXTERNAL_LINK
    assert elements["e2"].channel is Channel.IGNORE


def test_the_home_snapshot_maps_forms_buttons_disclosures_and_roles():
    elements = by_id(project("home"))

    # An anchor with a widget role is that widget: the fixture's nav entries are
    # menu items, not plain links.
    assert elements["e3"].element_type is ElementType.MENU_ITEM
    assert elements["e3"].channel is Channel.OFFER
    assert elements["e4"].element_type is ElementType.MENU_ITEM

    assert elements["e5"].element_type is ElementType.FORM
    assert elements["e5"].channel is Channel.OFFER
    assert elements["e5"].action == "/search"
    # A submit control is the form's submit surface, not a separate button.
    assert elements["e8"].element_type is ElementType.FORM
    assert elements["e8"].channel is Channel.OFFER

    assert elements["e9"].element_type is ElementType.BUTTON
    assert elements["e12"].element_type is ElementType.BUTTON
    assert elements["e18"].element_type is ElementType.DISCLOSURE
    assert elements["e18"].channel is Channel.OFFER


def test_the_home_snapshot_drops_the_exclusion_set_and_keeps_its_signal_free_customs():
    elements = by_id(project("home"))

    # Form fields are the form's, not candidates; structural containers are not
    # candidates; the hidden, aria-hidden, and display:none subtrees are gone
    # with their descendants.
    for excluded in ("e6", "e7", "e11", "e13", "e14", "e15"):
        assert excluded not in elements

    # An open dialog is an ignored state fact; its controls stay candidates.
    assert elements["e10"].element_type is ElementType.DIALOG_STATE
    assert elements["e10"].channel is Channel.IGNORE

    # A custom element with a role or handler is offered; a signal-free one is
    # still modelled, but only as an ignored custom type.
    assert elements["e16"].element_type is ElementType.CUSTOM
    assert elements["e16"].channel is Channel.OFFER
    assert elements["e17"].element_type is ElementType.CUSTOM
    assert elements["e17"].channel is Channel.IGNORE


def test_downloads_are_collected_and_non_http_schemes_are_dropped():
    elements = by_id(
        project_nodes(
            [
                node("a", ref="a1", attributes={"href": "/files/report.pdf"}),
                node("a", ref="a2", attributes={"href": "/export", "download": ""}),
                node("a", ref="a3", attributes={"href": "javascript:void(0)"}),
                node("a", ref="a4", attributes={"href": "mailto:qa@example.test"}),
                node("a", ref="a5", attributes={"href": "tel:+10000000000"}),
                node("a", ref="a6", attributes={"href": "data:text/html,x"}),
                node("a", ref="a7", attributes={"href": "blob:https://example.test/x"}),
                node(
                    "a",
                    ref="a8",
                    attributes={"href": "javascript:void(0)"},
                    children=[node("button", ref="a8b", attributes={"type": "button"})],
                ),
            ]
        )
    )

    assert elements["a1"].element_type is ElementType.DOWNLOAD
    assert elements["a1"].channel is Channel.COLLECT
    assert elements["a1"].impact == "download"
    assert elements["a1"].capture == "none"
    assert elements["a2"].element_type is ElementType.DOWNLOAD
    # The whole non-HTTP subtree is gone, including a nested control.
    assert not {"a3", "a4", "a5", "a6", "a7", "a8b"} & set(elements)


def test_roles_and_raw_signals_map_to_the_closed_types():
    elements = by_id(
        project_nodes(
            [
                node("div", ref="r1", role="button"),
                node("span", ref="r2", role="link"),
                node("div", ref="r3", role="tab"),
                node("div", ref="r4", role="menuitemcheckbox"),
                node("div", ref="r5", role="treeitem"),
                node("div", ref="r6", attributes={"onclick": "go()"}),
                node("svg", ref="r7", attributes={"onclick": "go()"}),
                node("svg", ref="r8", role="button"),
                node("canvas", ref="r9", attributes={"onclick": "go()"}),
                node("div", ref="r10", attributes={"draggable": "true"}),
                node("div", ref="r11", role="region", attributes={"tabindex": "0"}),
                node("x-panel", ref="r12", role="button"),
                node("x-empty", ref="r13"),
                node("plainwidget", ref="r14"),
                node("gadget", ref="r15", role="switch"),
                node(
                    "a",
                    ref="r16",
                    role="tab",
                    attributes={"href": "https://other.test/tab"},
                ),
            ]
        )
    )

    assert elements["r1"].element_type is ElementType.ROLE_BUTTON
    assert elements["r2"].element_type is ElementType.ROLE_LINK
    assert elements["r3"].element_type is ElementType.TAB
    assert elements["r4"].element_type is ElementType.MENU_ITEM
    assert elements["r5"].element_type is ElementType.TREE_ITEM
    assert elements["r6"].element_type is ElementType.CLICKABLE
    assert elements["r7"].element_type is ElementType.CLICKABLE
    assert elements["r8"].element_type is ElementType.CLICKABLE
    assert elements["r9"].element_type is ElementType.CLICKABLE
    assert elements["r10"].element_type is ElementType.DRAGGABLE
    assert elements["r11"].element_type is ElementType.CUSTOM
    assert elements["r11"].channel is Channel.OFFER
    assert elements["r12"].element_type is ElementType.CUSTOM
    assert elements["r12"].channel is Channel.OFFER
    assert elements["r13"].element_type is ElementType.CUSTOM
    assert elements["r13"].channel is Channel.IGNORE
    assert "r14" not in elements
    assert elements["r15"].element_type is ElementType.CUSTOM
    assert elements["r15"].channel is Channel.OFFER
    assert elements["r16"].element_type is ElementType.EXTERNAL_LINK
    assert elements["r16"].channel is Channel.IGNORE
    for element_id in (
        "r1",
        "r2",
        "r3",
        "r4",
        "r5",
        "r6",
        "r7",
        "r8",
        "r9",
        "r10",
        "r15",
    ):
        assert elements[element_id].channel is Channel.OFFER


def test_iframes_and_frames_split_on_origin():
    elements = by_id(
        project_nodes(
            [
                node("iframe", ref="f1", attributes={"src": "/reviews"}),
                node("iframe", ref="f2", attributes={"src": "https://other.test/x"}),
                node("frame", ref="f3", attributes={"src": "/legacy"}),
                node("frame", ref="f4", attributes={"src": "https://other.test/y"}),
            ]
        )
    )

    assert elements["f1"].element_type is ElementType.IFRAME
    assert elements["f1"].channel is Channel.OFFER
    assert elements["f1"].impact == "navigate"
    assert elements["f1"].capture == "navigation"
    assert elements["f2"].element_type is ElementType.EXTERNAL_IFRAME
    assert elements["f2"].channel is Channel.IGNORE
    assert elements["f3"].element_type is ElementType.FRAME
    assert elements["f3"].channel is Channel.OFFER
    assert elements["f4"].element_type is ElementType.FRAME
    assert elements["f4"].channel is Channel.IGNORE


def test_external_areas_and_forms_are_ignored_while_same_origin_ones_are_offered():
    elements = by_id(
        project_nodes(
            [
                node("area", ref="m1", attributes={"href": "/local"}),
                node("area", ref="m2", attributes={"href": "https://other.test/"}),
                node("form", ref="m3", attributes={"action": "/search"}),
                node("form", ref="m4", attributes={"action": "https://other.test/post"}),
                node("form", ref="m5"),
                node(
                    "form",
                    ref="m6",
                    attributes={"action": "/submit", "method": "post"},
                    children=[
                        node("button", ref="m7", attributes={"type": "submit"}),
                        node("button", ref="m8", attributes={"type": "button"}),
                    ],
                ),
            ]
        )
    )

    assert elements["m1"].element_type is ElementType.AREA
    assert elements["m1"].impact == "navigate"
    assert elements["m2"].element_type is ElementType.EXTERNAL_AREA
    assert elements["m2"].channel is Channel.IGNORE
    assert elements["m3"].element_type is ElementType.FORM
    assert elements["m3"].channel is Channel.OFFER
    assert elements["m4"].element_type is ElementType.EXTERNAL_FORM
    assert elements["m4"].channel is Channel.IGNORE
    assert elements["m5"].element_type is ElementType.FORM
    assert elements["m5"].impact == "write"
    assert elements["m5"].capture == "network"
    assert elements["m6"].element_type is ElementType.FORM
    assert elements["m7"].element_type is ElementType.FORM
    assert elements["m7"].synthetic is True
    assert elements["m8"].element_type is ElementType.BUTTON


def test_meta_refresh_is_offered_and_details_offer_their_summary():
    elements = by_id(
        project_nodes(
            [
                node("meta", ref="t1", attributes={"http-equiv": "refresh", "content": "0; url=/next"}),
                node("meta", ref="t2", attributes={"name": "description", "content": "x"}),
                node(
                    "details",
                    ref="t3",
                    children=[node("summary", ref="t4", name="Shipping")],
                ),
            ]
        )
    )

    assert elements["t1"].element_type is ElementType.META_REFRESH
    assert elements["t1"].channel is Channel.OFFER
    assert elements["t1"].impact == "navigate"
    assert elements["t1"].capture == "navigation"
    assert "t2" not in elements
    assert "t3" not in elements
    assert elements["t4"].element_type is ElementType.DISCLOSURE
    assert elements["t4"].channel is Channel.OFFER


def test_the_exclusion_set_drops_fields_structure_metadata_and_hidden_subtrees():
    excluded_tags = [
        "input",
        "select",
        "textarea",
        "option",
        "optgroup",
        "datalist",
        "output",
        "progress",
        "meter",
        "script",
        "style",
        "link",
        "base",
        "title",
        "template",
        "noscript",
        "img",
        "picture",
        "source",
        "track",
        "embed",
        "object",
        "param",
        "map",
        "math",
        "div",
        "span",
        "p",
        "h2",
        "ul",
        "li",
        "table",
        "tr",
        "td",
        "section",
        "article",
        "label",
        "fieldset",
    ]
    nodes = [
        node(tag, ref=f"x{index}") for index, tag in enumerate(excluded_tags)
    ] + [
        node("div", ref="editable", attributes={"contenteditable": "true"}),
        node("section", ref="s1", children=[node("button", ref="s1b", attributes={"type": "button"})]),
        node("div", ref="h1", attributes={"hidden": ""}, children=[node("button", ref="h1b")]),
        node("div", ref="h2", attributes={"inert": ""}, children=[node("button", ref="h2b")]),
        node("div", ref="h3", attributes={"aria-hidden": "true"}, children=[node("button", ref="h3b")]),
        node("div", ref="h4", attributes={"style": "display: none"}, children=[node("button", ref="h4b")]),
        node("div", ref="h5", attributes={"style": "visibility: hidden"}, children=[node("button", ref="h5b")]),
        node("div", ref="h6", visible=False, children=[node("button", ref="h6b")]),
    ]

    elements = by_id(project_nodes(nodes))

    for index in range(len(excluded_tags)):
        assert f"x{index}" not in elements
    assert "editable" not in elements
    # Excluding a container drops the container, not its descendants.
    assert elements["s1b"].element_type is ElementType.BUTTON
    # Hidden and inert hide the whole subtree.
    for hidden_id in ("h1b", "h2b", "h3b", "h4b", "h5b", "h6b"):
        assert hidden_id not in elements


def test_each_type_carries_the_spec_default_impact_and_capture():
    rows = [
        (node("a", ref="c1", attributes={"href": "/x"}), "navigate", "navigation"),
        (node("a", ref="c2", attributes={"href": "/x.pdf"}), "download", "none"),
        (node("form", ref="c3", attributes={"action": "/x"}), "write", "network"),
        (node("button", ref="c4", attributes={"type": "button"}), "local_state", "dom"),
        (node("summary", ref="c5", name="More"), "local_state", "dom"),
        (node("div", ref="c6", role="button"), "local_state", "dom"),
        (node("div", ref="c7", role="link"), "local_state", "dom"),
        (node("div", ref="c8", role="tab"), "local_state", "dom"),
        (node("iframe", ref="c9", attributes={"src": "/f"}), "navigate", "navigation"),
        (
            node("iframe", ref="c10", attributes={"src": "https://other.test/"}),
            "external",
            "none",
        ),
        (
            node("meta", ref="c11", attributes={"http-equiv": "refresh", "content": "0; url=/n"}),
            "navigate",
            "navigation",
        ),
        (node("dialog", ref="c12", attributes={"open": ""}), "observe", "none"),
    ]

    elements = by_id(project_nodes([row[0] for row in rows]))

    for element_id, impact, capture in (
        (row[0].ref, row[1], row[2]) for row in rows
    ):
        assert elements[element_id].impact == impact
        assert elements[element_id].capture == capture
        assert elements[element_id].change.impact == impact
        assert elements[element_id].change.capture == capture


def test_a_fragment_link_is_local_state_and_a_real_link_may_navigate():
    elements = by_id(
        project_nodes(
            [
                node("a", ref="g1", attributes={"href": "#panel"}),
                node("a", ref="g2", attributes={"href": "/products"}),
                node("form", ref="g3", attributes={"action": "/save", "onsubmit": "save()"}),
                node("button", ref="g4", attributes={"type": "button", "onclick": "go()"}),
            ]
        )
    )

    assert elements["g1"].element_type is ElementType.LINK
    assert elements["g1"].impact == "local_state"
    assert elements["g1"].capture == "dom"
    assert elements["g1"].change.may_navigate is False

    assert elements["g2"].change.may_navigate is True
    assert elements["g2"].change.handler == "href"
    assert elements["g3"].change.may_navigate is True
    assert elements["g3"].change.handler == "onsubmit"
    assert elements["g4"].change.may_navigate is False
    assert elements["g4"].change.handler == "onclick"


def test_identity_and_fingerprint_are_stable_across_two_projections():
    nodes = [
        node(
            "div",
            ref="i1",
            children=[node("button", ref="i2", name="Load more", attributes={"type": "button"})],
        )
    ]

    first = project_nodes(nodes)
    second = project_nodes(nodes)

    assert [(e.element_id, e.fingerprint, e.selector) for e in first] == [
        (e.element_id, e.fingerprint, e.selector) for e in second
    ]

    renamed = [
        node(
            "div",
            ref="i1",
            children=[
                node(
                    "button",
                    ref="i2",
                    name="Load even more",
                    attributes={"type": "button"},
                )
            ],
        )
    ]
    changed = project_nodes(renamed)
    assert [e.element_id for e in changed] == [e.element_id for e in first]
    assert changed[0].fingerprint != first[0].fingerprint


def test_a_changed_href_or_dom_path_changes_the_fingerprint():
    base = [node("a", ref="j1", attributes={"href": "/a"})]
    moved = [node("div"), node("a", ref="j1", attributes={"href": "/a"})]
    relinked = [node("a", ref="j1", attributes={"href": "/b"})]

    first = project_nodes(base)[0]
    second = project_nodes(moved)[0]
    third = project_nodes(relinked)[0]

    assert first.fingerprint != second.fingerprint
    assert first.fingerprint != third.fingerprint


def test_a_ref_is_the_selector_and_a_ref_less_node_gets_a_css_path():
    elements = project_nodes(
        [
            node("div", children=[node("button", name="Go", attributes={"type": "button"})]),
        ]
    )

    assert elements[0].element_id == "n1.1"
    assert elements[0].selector == "body > div:nth-child(1) > button:nth-child(1)"


def test_a_project_channel_override_maps_a_form_to_collect_and_never_both():
    nodes = [
        node("form", ref="p1", attributes={"action": "/delete"}),
        node("a", ref="p2", attributes={"href": "/products"}),
    ]
    settings = ProjectElementSettings(
        channels={
            ElementType.FORM: Channel.COLLECT,
            ElementType.LINK: Channel.IGNORE,
        }
    )

    elements = by_id(project_nodes(nodes, settings=settings))

    assert elements["p1"].channel is Channel.COLLECT
    assert elements["p1"].channel is not Channel.OFFER
    assert elements["p2"].channel is Channel.IGNORE


def test_a_raw_selector_rule_types_a_node_and_may_set_its_channel():
    nodes = [
        node("div", ref="q1", role="region"),
        node("a", ref="q2", attributes={"href": "/support"}),
    ]
    settings = ProjectElementSettings(
        rules=(
            RawSelectorRule(
                selector='div[role="region"]', element_type=ElementType.CLICKABLE
            ),
            RawSelectorRule(
                selector='a[href="/support"]',
                element_type=ElementType.LINK,
                channel=Channel.COLLECT,
            ),
        )
    )

    elements = by_id(project_nodes(nodes, settings=settings))

    assert elements["q1"].element_type is ElementType.CLICKABLE
    assert elements["q1"].channel is Channel.OFFER
    assert elements["q2"].element_type is ElementType.LINK
    assert elements["q2"].channel is Channel.COLLECT
    assert elements["q2"].href == "/support"


def test_render_projection_is_one_bounded_deterministic_line_per_element():
    elements = project("home")
    lines = render_projection(elements)

    assert lines[0] == '- link "Home" [ref=e1]'
    assert '- external_link "Partner site" [ref=e2] [ignore]' in lines
    assert '- dialog_state "Newsletter" [ref=e10] [ignore]' in lines
    assert lines == render_projection(elements)

    button = by_id(
        project_nodes([node("button", ref="k1", name="Go", attributes={"type": "button"})])
    )["k1"]
    assert render_projection([button], consumed={button.fingerprint}) == [
        '- button "Go" [ref=k1] [consumed]'
    ]


def test_render_projection_caps_the_line_count_and_the_label_length():
    nodes = [
        node("button", ref=f"b{index}", name=f"Button {index}", attributes={"type": "button"})
        for index in range(5)
    ]
    bounded = render_projection(project_nodes(nodes), limit=3)

    assert len(bounded) == 4
    assert bounded[:3] == [
        '- button "Button 0" [ref=b0]',
        '- button "Button 1" [ref=b1]',
        '- button "Button 2" [ref=b2]',
    ]
    assert bounded[-1] == "- ... (2 more)"

    long_line = render_projection(
        project_nodes([node("button", ref="l1", name="x" * 200, attributes={"type": "button"})])
    )[0]
    assert len(long_line) <= 120
    assert "..." in long_line


def test_parse_snapshot_tree_reads_the_compact_cli_tree_and_projects_it():
    tree = load_cli("snapshot").data["tree"]
    nodes = parse_snapshot_tree(tree)

    assert [parsed.ref for parsed in nodes] == ["e1", "e2", "e5", "e9"]
    assert [child.ref for child in nodes[2].children] == ["e6", "e7", "e8"]
    assert nodes[2].tag == "form"
    assert nodes[2].attributes["ref"] == "e5"

    elements = by_id(project_nodes(list(nodes)))

    assert elements["e1"].element_type is ElementType.ROLE_LINK
    assert elements["e1"].selector == "@e1"
    assert elements["e5"].element_type is ElementType.FORM
    assert elements["e8"].element_type is ElementType.FORM
    assert elements["e9"].element_type is ElementType.BUTTON
    assert "e6" not in elements
    assert "e7" not in elements


PANEL_URL = "https://example.test/panel"


def _open(nodes: list[SnapshotNode]) -> tuple[BrowserState, PageInstance]:
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_1", url=PANEL_URL, final_url=PANEL_URL, snapshot=nodes
    )
    return state, page


def test_control_facts_report_the_targets_projection_and_consumed_count():
    nodes = [
        node(
            "button",
            ref="s1",
            name="Open",
            attributes={"type": "button", "aria-controls": "panel"},
        ),
        node(
            "div",
            ref="panel",
            attributes={"id": "panel"},
            children=[
                node("a", ref="p1", name="One", attributes={"href": "/one"}),
                node("a", ref="p2", name="Two", attributes={"href": "/two"}),
            ],
        ),
    ]
    state, page = _open(nodes)
    element_map = ElementMap()

    first = by_id(element_map.project(nodes, page=page, state=state, page_url=PANEL_URL))
    fact = first["s1"].change.control_facts[0]

    assert first["s1"].change.controls == ("panel",)
    assert fact.target_id == "panel"
    assert fact.hidden is False
    assert fact.target_projection == (
        '- link "One" [ref=p1]',
        '- link "Two" [ref=p2]',
    )
    assert fact.consumed_count == 0

    state.consume(page, first["p1"].fingerprint)
    second = by_id(element_map.project(nodes, page=page, state=state, page_url=PANEL_URL))
    fact = second["s1"].change.control_facts[0]

    assert fact.consumed_count == 1
    assert fact.target_projection[0] == '- link "One" [ref=p1] [consumed]'
    assert fact.target_projection[1] == '- link "Two" [ref=p2]'


def test_a_hidden_control_target_reports_the_surface_a_reveal_would_expose():
    nodes = [
        node(
            "button",
            ref="s2",
            name="More",
            attributes={"type": "button", "aria-controls": "panel"},
        ),
        node(
            "div",
            ref="panel",
            attributes={"id": "panel", "hidden": ""},
            children=[
                node("a", ref="p3", name="Hidden one", attributes={"href": "/one"}),
                node("a", ref="p4", name="Hidden two", attributes={"href": "/two"}),
            ],
        ),
    ]

    elements = by_id(project_nodes(nodes))
    fact = elements["s2"].change.control_facts[0]

    assert fact.hidden is True
    assert fact.target_projection == (
        '- link "Hidden one" [ref=p3]',
        '- link "Hidden two" [ref=p4]',
    )
    assert fact.consumed_count == 0
    assert "p3" not in elements
    assert "p4" not in elements


def test_control_facts_are_built_only_for_idrefs_that_resolve():
    nodes = [
        node(
            "button",
            ref="s3",
            name="Open",
            attributes={"type": "button", "aria-controls": "missing panel"},
        ),
        node(
            "div",
            ref="panel",
            attributes={"id": "panel"},
            children=[node("a", ref="p5", name="One", attributes={"href": "/one"})],
        ),
    ]

    elements = by_id(project_nodes(nodes))

    assert elements["s3"].change.controls == ("missing", "panel")
    assert [fact.target_id for fact in elements["s3"].change.control_facts] == ["panel"]


def test_data_target_and_an_href_fragment_are_control_idrefs():
    nodes = [
        node(
            "a",
            ref="s4",
            attributes={
                "href": "#tabpanel",
                "aria-controls": "extra",
                "data-target": "#modal",
            },
        ),
        node(
            "div",
            ref="tabpanel",
            attributes={"id": "tabpanel"},
            children=[node("button", ref="t1", attributes={"type": "button"})],
        ),
        node(
            "div",
            ref="extra",
            attributes={"id": "extra"},
            children=[node("button", ref="t2", attributes={"type": "button"})],
        ),
        node(
            "div",
            ref="modal",
            attributes={"id": "modal"},
            children=[node("button", ref="t3", attributes={"type": "button"})],
        ),
    ]

    elements = by_id(project_nodes(nodes))
    semantics = elements["s4"].change

    assert semantics.controls == ("extra", "modal", "tabpanel")
    assert [fact.target_id for fact in semantics.control_facts] == [
        "extra",
        "modal",
        "tabpanel",
    ]
