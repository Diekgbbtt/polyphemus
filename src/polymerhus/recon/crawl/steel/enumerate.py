"""Snapshot -> closed element model: the exclusion set, the map, and the channels.

Spec: `docs/design/steel-crawl-spec.md` sections 6.1 to 6.6.

`ElementMap.project` is a pure projection from a cached DOM snapshot to the
closed `ElementType` model. It decides each element's channel (`offer`,
`collect`, or `ignore`), its default impact and capture, and its change
semantics with the control facts the symbolic layer supplies. It never acts on
the DOM, never calls the browser, and never imports a test record: the caller
adapts its own snapshot into `SnapshotNode`.

The exclusion set runs first: fields, text and structure, metadata and
resources, hidden or inert subtrees, and non-HTTP schemes are not candidates.
State containers (`dialog`, `details`) are not candidates themselves, but their
controls are, and an open dialog is recorded as an ignored `DIALOG_STATE` fact.
The three-layer map then classifies the remaining elements by raw signal; an
unknown interactive element is `CUSTOM`, and an unknown inert element is
dropped. No element is ever both offered and collected.

Identity is deterministic: the `ref` is the document-scoped identity when the
snapshot carries one, else the DOM path forms a CSS-ish selector. The
fingerprint hashes the stable semantic fields and the DOM path, so two
projections of one snapshot agree while a changed label, href, action, type, or
path changes the fingerprint. The compact projection (`render_projection`) is
the bounded surface the policy and the control facts read.

A `FORM`-typed element also carries the form's declared contract (spec 8.1). The
contract is the DOM fact, so a form and its submit control carry the same one;
the channel decides whether it is offered, collected, or ignored. The fields are
part of the contract while staying out of the candidate list: the form is the
unit, and the values are network-observed.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.parameters import (
    DEFAULT_ENCTYPE,
    DEFAULT_METHOD,
    FormContract,
    FormField,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance

# The handler vocabulary of the change semantics (spec 6.5).
Handler = Literal["href", "onclick", "onsubmit", "listener", "unknown"]


class ElementType(str, Enum):
    """The closed element model (spec 6.2). A new semantic type is a code change."""

    LINK = "LINK"
    EXTERNAL_LINK = "EXTERNAL_LINK"
    AREA = "AREA"
    EXTERNAL_AREA = "EXTERNAL_AREA"
    FORM = "FORM"
    EXTERNAL_FORM = "EXTERNAL_FORM"
    BUTTON = "BUTTON"
    DISCLOSURE = "DISCLOSURE"
    ROLE_BUTTON = "ROLE_BUTTON"
    ROLE_LINK = "ROLE_LINK"
    TAB = "TAB"
    MENU_ITEM = "MENU_ITEM"
    TREE_ITEM = "TREE_ITEM"
    IFRAME = "IFRAME"
    EXTERNAL_IFRAME = "EXTERNAL_IFRAME"
    FRAME = "FRAME"
    CLICKABLE = "CLICKABLE"
    CUSTOM = "CUSTOM"
    DRAGGABLE = "DRAGGABLE"
    DOWNLOAD = "DOWNLOAD"
    META_REFRESH = "META_REFRESH"
    DIALOG_STATE = "DIALOG_STATE"


class Channel(str, Enum):
    """The three channel decisions (spec 6.3). No element is both offer and collect."""

    OFFER = "offer"
    COLLECT = "collect"
    IGNORE = "ignore"


class RawSelectorRule(BaseModel):
    """A project rule: one raw selector typed as a core element type.

    The selector grammar is the small attribute subset the map can evaluate
    without a CSS engine: `tag`, `tag[attr]`, `tag[attr=value]`, and `*`. The
    first matching rule wins; a rule may fix the channel, else the project's
    type override or the type default decides.
    """

    model_config = ConfigDict(frozen=True)

    selector: str
    element_type: ElementType
    channel: Channel | None = None


class ProjectElementSettings(BaseModel):
    """The project's channel policy over the closed type set (spec 6.2).

    `channels` maps a core type to its channel; the spec defaults apply to the
    types it leaves out. `rules` adds raw-selector classification for elements
    the generic map would ignore.
    """

    model_config = ConfigDict(frozen=True)

    channels: Mapping[ElementType, Channel] = Field(default_factory=dict)
    rules: tuple[RawSelectorRule, ...] = ()


class SnapshotNode(BaseModel):
    """One node of the normalized DOM snapshot the map consumes.

    `attributes` are the raw HTML attributes, because classification reads the
    signals (`hidden`, `aria-*`, `role`, `onclick`, `href`). `visible` is the
    snapshot's own visibility verdict; an attribute-level hide is read here too,
    so a caller cannot lose the exclusion by omitting one of the two.
    """

    model_config = ConfigDict(frozen=True)

    tag: str
    ref: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    attributes: Mapping[str, str] = Field(default_factory=dict)
    visible: bool = True
    children: tuple["SnapshotNode", ...] = ()


class ControlFact(BaseModel):
    """The current state of one IDREF a candidate controls (spec 6.5).

    `target_projection` is the compact projection of the target's candidates,
    with its consumed marker; `consumed_count` comes from the `BrowserState` for
    the page. A hidden target is projected with its own hidden attribute lifted,
    so the policy can see the new surface a reveal would expose.
    """

    model_config = ConfigDict(frozen=True)

    target_id: str
    hidden: bool
    target_projection: tuple[str, ...] = ()
    consumed_count: int = 0


class ChangeSemantics(BaseModel):
    """What exercising one candidate can change (spec 6.5)."""

    model_config = ConfigDict(frozen=True)

    impact: ImpactClass
    capture: CaptureChannel
    method: str | None = None
    action: str | None = None
    target: str | None = None
    may_navigate: bool = False
    controls: tuple[str, ...] = ()
    control_facts: tuple[ControlFact, ...] = ()
    handler: Handler = "unknown"
    confidence: float = 1.0


class Element(BaseModel):
    """One projected candidate: identity, type, channel, and change semantics.

    `selector` is what the command mapper resolves before acting: the
    document-scoped `@ref` when the snapshot carries one, else a deterministic
    CSS-ish path. `fingerprint` is what the consumed set stores; `element_id` is
    the stable identity the decision records cite. `form` is the declared
    contract of a `FORM` candidate (spec 8.1), for the form element and for its
    submit control alike; it is `None` for every other type.
    """

    model_config = ConfigDict(frozen=True)

    element_id: str
    fingerprint: str
    element_type: ElementType
    name: str = ""
    text: str = ""
    href: str | None = None
    action: str | None = None
    selector: str = ""
    channel: Channel = Channel.OFFER
    impact: ImpactClass = "local_state"
    capture: CaptureChannel = "dom"
    change: ChangeSemantics
    form: FormContract | None = None
    synthetic: bool = False
    disabled: bool = False
    visible: bool = True


# The default impact and capture per type (spec 6.4). The instance impact is
# authoritative later; this is only the projection default.
_DEFAULT_IMPACT: dict[ElementType, ImpactClass] = {
    ElementType.LINK: "navigate",
    ElementType.EXTERNAL_LINK: "external",
    ElementType.AREA: "navigate",
    ElementType.EXTERNAL_AREA: "external",
    ElementType.FORM: "write",
    ElementType.EXTERNAL_FORM: "external",
    ElementType.BUTTON: "local_state",
    ElementType.DISCLOSURE: "local_state",
    ElementType.ROLE_BUTTON: "local_state",
    ElementType.ROLE_LINK: "local_state",
    ElementType.TAB: "local_state",
    ElementType.MENU_ITEM: "local_state",
    ElementType.TREE_ITEM: "local_state",
    ElementType.IFRAME: "navigate",
    ElementType.EXTERNAL_IFRAME: "external",
    ElementType.FRAME: "navigate",
    ElementType.CLICKABLE: "local_state",
    ElementType.CUSTOM: "local_state",
    ElementType.DRAGGABLE: "local_state",
    ElementType.DOWNLOAD: "download",
    ElementType.META_REFRESH: "navigate",
    ElementType.DIALOG_STATE: "observe",
}

_DEFAULT_CAPTURE: dict[ElementType, CaptureChannel] = {
    ElementType.LINK: "navigation",
    ElementType.EXTERNAL_LINK: "none",
    ElementType.AREA: "navigation",
    ElementType.EXTERNAL_AREA: "none",
    ElementType.FORM: "network",
    ElementType.EXTERNAL_FORM: "none",
    ElementType.BUTTON: "dom",
    ElementType.DISCLOSURE: "dom",
    ElementType.ROLE_BUTTON: "dom",
    ElementType.ROLE_LINK: "dom",
    ElementType.TAB: "dom",
    ElementType.MENU_ITEM: "dom",
    ElementType.TREE_ITEM: "dom",
    ElementType.IFRAME: "navigation",
    ElementType.EXTERNAL_IFRAME: "none",
    ElementType.FRAME: "navigation",
    ElementType.CLICKABLE: "dom",
    ElementType.CUSTOM: "dom",
    ElementType.DRAGGABLE: "dom",
    ElementType.DOWNLOAD: "none",
    ElementType.META_REFRESH: "navigation",
    ElementType.DIALOG_STATE: "none",
}

# Channels that follow from the type alone (spec 6.3). CUSTOM's offer/ignore
# split depends on an interaction signal, so it is decided per element.
_DEFAULT_CHANNEL: dict[ElementType, Channel] = {
    **dict.fromkeys(ElementType, Channel.OFFER),
    ElementType.EXTERNAL_LINK: Channel.IGNORE,
    ElementType.EXTERNAL_AREA: Channel.IGNORE,
    ElementType.EXTERNAL_FORM: Channel.IGNORE,
    ElementType.EXTERNAL_IFRAME: Channel.IGNORE,
    ElementType.DOWNLOAD: Channel.COLLECT,
    ElementType.DIALOG_STATE: Channel.IGNORE,
}

_NON_HTTP_SCHEMES = frozenset({"javascript", "mailto", "tel", "data", "blob"})

# The exclusion set (spec 6.1). A form field and a structure element are not
# candidates, though the walk still descends into structures for their controls.
_FORM_FIELD_TAGS = frozenset(
    {
        "datalist",
        "input",
        "meter",
        "optgroup",
        "option",
        "output",
        "progress",
        "select",
        "textarea",
    }
)
_STRUCTURE_TAGS = frozenset(
    {
        "abbr",
        "address",
        "article",
        "aside",
        "b",
        "bdi",
        "bdo",
        "blockquote",
        "body",
        "br",
        "caption",
        "cite",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "dfn",
        "div",
        "dl",
        "dt",
        "em",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "header",
        "hr",
        "html",
        "i",
        "ins",
        "kbd",
        "label",
        "legend",
        "li",
        "main",
        "mark",
        "nav",
        "ol",
        "p",
        "pre",
        "q",
        "rp",
        "rt",
        "ruby",
        "s",
        "samp",
        "section",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "time",
        "tr",
        "u",
        "ul",
        "var",
        "wbr",
    }
)
_METADATA_TAGS = frozenset(
    {
        "base",
        "embed",
        "img",
        "link",
        "map",
        "math",
        "noscript",
        "object",
        "param",
        "picture",
        "script",
        "source",
        "style",
        "template",
        "title",
        "track",
    }
)
_STATE_CONTAINER_TAGS = frozenset({"details", "dialog"})

# The role map (spec 6.2). A role types the element only where native HTML
# semantics do not already decide it.
_ROLE_TYPES: dict[str, ElementType] = {
    "button": ElementType.ROLE_BUTTON,
    "link": ElementType.ROLE_LINK,
    "menuitem": ElementType.MENU_ITEM,
    "menuitemcheckbox": ElementType.MENU_ITEM,
    "menuitemradio": ElementType.MENU_ITEM,
    "tab": ElementType.TAB,
    "treeitem": ElementType.TREE_ITEM,
}

# Anchor or button roles that override the tag's own widget semantics.
_WIDGET_ROLES = frozenset(
    {"button", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "treeitem"}
)

# Accessible field roles a compact snapshot may carry without the raw tag.
_FIELD_ROLES = frozenset(
    {
        "checkbox",
        "combobox",
        "listbox",
        "meter",
        "option",
        "progressbar",
        "radio",
        "searchbox",
        "slider",
        "spinbutton",
        "textbox",
    }
)

# A file-extension href is a download, not a navigation (spec 6.2).
_DOWNLOAD_EXTENSIONS = frozenset(
    {
        "7z",
        "apk",
        "csv",
        "dmg",
        "doc",
        "docx",
        "exe",
        "gif",
        "gz",
        "iso",
        "jpeg",
        "jpg",
        "json",
        "mp3",
        "mp4",
        "pdf",
        "png",
        "rar",
        "tar",
        "txt",
        "xls",
        "xlsx",
        "xml",
        "zip",
    }
)


def _tag(node: SnapshotNode) -> str:
    return node.tag.strip().lower()


def _attr(node: SnapshotNode, name: str) -> str | None:
    for key, value in node.attributes.items():
        if key.lower() == name:
            return value
    return None


def _attr_text(node: SnapshotNode, name: str) -> str | None:
    """One attribute as stripped non-empty text, or `None` when absent or empty."""
    value = _attr(node, name)
    if value is None:
        return None
    text = value.strip()
    return text or None


def _has_attr(node: SnapshotNode, name: str) -> bool:
    return _attr(node, name) is not None


def _scheme(value: str) -> str:
    return urlsplit(value.strip()).scheme.lower()


def _non_http_scheme(value: str) -> bool:
    return _scheme(value) in _NON_HTTP_SCHEMES


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else 0
    return scheme, (parts.hostname or "").lower(), parts.port or default_port


def _same_origin(base_url: str, url: str) -> bool:
    return _origin(base_url) == _origin(url)


def _resolve(base_url: str, value: str) -> str:
    return urljoin(base_url, value)


def _is_fragment_only(href: str) -> bool:
    return href.strip().startswith("#")


def _download_href(href: str) -> bool:
    path = urlsplit(href).path
    last = path.rsplit("/", 1)[-1]
    return "." in last and last.rsplit(".", 1)[-1].lower() in _DOWNLOAD_EXTENSIONS


def _fingerprint(
    element_type: ElementType,
    name: str,
    text: str,
    href: str | None,
    action: str | None,
    selector: str,
    dom_path: str,
) -> str:
    """Hash the stable fields: a changed label, href, action, type, or path moves it."""
    payload = "\x1f".join(
        (
            element_type.value,
            name,
            text,
            href or "",
            action or "",
            selector,
            dom_path,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Classified:
    """One classified node, before the element identity and facts are minted."""

    element_type: ElementType
    href: str | None = None
    action: str | None = None
    resolved: str | None = None
    method: str | None = None
    handler: Handler = "unknown"
    channel: Channel | None = None
    explicit_channel: bool = False
    confidence: float = 1.0
    synthetic: bool = False


@dataclass(frozen=True)
class _Draft:
    """One classified node with the DOM identity its element will carry.

    `form` and `form_css` are the nearest enclosing form element, so a submit
    control can carry its form's declared contract.
    """

    node: SnapshotNode
    path: tuple[int, ...]
    css: str
    classified: _Classified
    form: SnapshotNode | None = None
    form_css: str | None = None


@dataclass(frozen=True)
class _NodeFacts:
    """The index entry for one snapshot node, hidden and form context included."""

    path: tuple[int, ...]
    css: str
    hidden: bool
    form: SnapshotNode | None


class ElementMap:
    """Project a cached DOM snapshot into the closed element model."""

    def project(
        self,
        snapshot: SnapshotNode | Sequence[SnapshotNode],
        *,
        page: PageInstance,
        state: BrowserState,
        page_url: str,
        base_url: str | None = None,
        settings: ProjectElementSettings | None = None,
    ) -> list[Element]:
        """Project the snapshot into candidates in document order, pure.

        `page` and `state` are the consumed-set authority; `page_url` is the
        document the snapshot came from and `base_url` the base the relative
        URLs resolve against (the document URL by default). `settings` is the
        project's channel policy and raw-selector rules.
        """
        roots = _roots(snapshot)
        base = base_url or page_url
        drafts: list[_Draft] = []
        for index, node in enumerate(roots):
            _walk(
                node,
                (index,),
                css=f"body > {_tag(node) or '*'}:nth-child({index + 1})",
                base=base,
                form=None,
                settings=settings,
                drafts=drafts,
            )
        index_by_node, by_dom_id = _index_tree(roots)
        elements: list[Element] = []
        for draft in drafts:
            controls = _control_ids(draft.node)
            facts = _control_facts(
                controls,
                index_by_node=index_by_node,
                by_dom_id=by_dom_id,
                base=base,
                settings=settings,
                page=page,
                state=state,
            )
            elements.append(
                _element(
                    draft.node,
                    draft.path,
                    draft.css,
                    draft.classified,
                    settings,
                    form=draft.form,
                    form_css=draft.form_css,
                    controls=controls,
                    control_facts=facts,
                )
            )
        return elements


def _roots(snapshot: SnapshotNode | Sequence[SnapshotNode]) -> tuple[SnapshotNode, ...]:
    if isinstance(snapshot, SnapshotNode):
        return (snapshot,)
    return tuple(snapshot)


def _index_tree(
    roots: Sequence[SnapshotNode],
) -> tuple[dict[int, _NodeFacts], dict[str, SnapshotNode]]:
    """Index every node by object identity and by DOM id, hidden propagation included."""
    index: dict[int, _NodeFacts] = {}
    by_dom_id: dict[str, SnapshotNode] = {}

    def visit(
        node: SnapshotNode,
        path: tuple[int, ...],
        css: str,
        inherited_hidden: bool,
        form: SnapshotNode | None,
    ) -> None:
        hidden = inherited_hidden or _is_hidden(node)
        index[id(node)] = _NodeFacts(path, css, hidden, form)
        dom_id = (_attr(node, "id") or "").strip()
        if dom_id:
            by_dom_id.setdefault(dom_id, node)
        child_form = node if _tag(node) == "form" else form
        for position, child in enumerate(node.children):
            visit(
                child,
                (*path, position),
                f"{css} > {_tag(child) or '*'}:nth-child({position + 1})",
                hidden,
                child_form,
            )

    for position, root in enumerate(roots):
        visit(
            root,
            (position,),
            f"body > {_tag(root) or '*'}:nth-child({position + 1})",
            False,
            None,
        )
    return index, by_dom_id


def _walk(
    node: SnapshotNode,
    path: tuple[int, ...],
    *,
    css: str,
    base: str,
    form: SnapshotNode | None,
    settings: ProjectElementSettings | None,
    drafts: list[_Draft],
    form_css: str | None = None,
    ignore_own_hidden: bool = False,
) -> None:
    """Classify one node, then recurse into its children in document order.

    `ignore_own_hidden` lifts only this node's own hidden state: a control fact
    projects a hidden target's would-be surface, while a separately hidden
    descendant stays excluded.
    """
    if _is_hidden(node) and not ignore_own_hidden:
        return
    if _has_non_http_url(node):
        return
    classified = _classify(node, base, form, settings)
    if classified is not None:
        drafts.append(_Draft(node, path, css, classified, form, form_css))
    child_form = node if _tag(node) == "form" else form
    child_form_css = css if _tag(node) == "form" else form_css
    for index, child in enumerate(node.children):
        _walk(
            child,
            (*path, index),
            css=f"{css} > {_tag(child) or '*'}:nth-child({index + 1})",
            base=base,
            form=child_form,
            settings=settings,
            drafts=drafts,
            form_css=child_form_css,
        )


def _control_ids(node: SnapshotNode) -> tuple[str, ...]:
    """The IDREFs from `aria-controls`, `data-target`, and an href fragment."""
    tokens: list[str] = []
    for name in ("aria-controls", "data-target"):
        value = _attr(node, name)
        if value:
            tokens.extend(value.split())
    href = _attr(node, "href")
    if href and "#" in href:
        tokens.append(href.split("#", 1)[1])
    control_ids: list[str] = []
    for token in tokens:
        target = token.strip().lstrip("#").strip()
        if target and target not in control_ids:
            control_ids.append(target)
    return tuple(control_ids)


def _control_facts(
    control_ids: Sequence[str],
    *,
    index_by_node: Mapping[int, _NodeFacts],
    by_dom_id: Mapping[str, SnapshotNode],
    base: str,
    settings: ProjectElementSettings | None,
    page: PageInstance,
    state: BrowserState,
) -> tuple[ControlFact, ...]:
    """The current state of every IDREF that resolves to a snapshot node."""
    facts: list[ControlFact] = []
    for target_id in control_ids:
        target = by_dom_id.get(target_id)
        if target is None:
            continue
        target_facts = index_by_node[id(target)]
        target_drafts: list[_Draft] = []
        _walk(
            target,
            target_facts.path,
            css=target_facts.css,
            base=base,
            form=target_facts.form,
            settings=settings,
            drafts=target_drafts,
            ignore_own_hidden=True,
        )
        target_elements = [
            _element(
                draft.node,
                draft.path,
                draft.css,
                draft.classified,
                settings,
                form=draft.form,
                form_css=draft.form_css,
            )
            for draft in target_drafts
        ]
        unconsumed = state.unconsumed(page, target_elements)
        unconsumed_fingerprints = {element.fingerprint for element in unconsumed}
        consumed = {
            element.fingerprint
            for element in target_elements
            if element.fingerprint not in unconsumed_fingerprints
        }
        facts.append(
            ControlFact(
                target_id=target_id,
                hidden=target_facts.hidden,
                target_projection=tuple(
                    render_projection(target_elements, consumed=consumed)
                ),
                consumed_count=len(target_elements) - len(unconsumed),
            )
        )
    return tuple(facts)


def _is_hidden(node: SnapshotNode) -> bool:
    if not node.visible:
        return True
    if _has_attr(node, "hidden") or _has_attr(node, "inert"):
        return True
    if (_attr(node, "aria-hidden") or "").strip().lower() == "true":
        return True
    style = (_attr(node, "style") or "").lower().replace(" ", "")
    return "display:none" in style or "visibility:hidden" in style


def _has_non_http_url(node: SnapshotNode) -> bool:
    for name in ("href", "src", "action"):
        value = _attr(node, name)
        if value is not None and _non_http_scheme(value):
            return True
    return False


def _role(node: SnapshotNode) -> str:
    return (node.role or _attr(node, "role") or "").strip().lower()


def _is_custom_element(tag: str) -> bool:
    return "-" in tag


def _has_handler(node: SnapshotNode) -> bool:
    return _has_attr(node, "onclick") or _has_attr(node, "onsubmit")


def _handler(node: SnapshotNode, default: Handler = "unknown") -> Handler:
    if _has_attr(node, "onclick"):
        return "onclick"
    if _has_attr(node, "onsubmit"):
        return "onsubmit"
    return default


def _dialog_state(node: SnapshotNode, tag: str, role: str) -> bool:
    if tag == "dialog" and _has_attr(node, "open"):
        return True
    if role == "dialog":
        return True
    return (_attr(node, "aria-modal") or "").strip().lower() == "true"


def _contenteditable(node: SnapshotNode) -> bool:
    value = _attr(node, "contenteditable")
    return value is not None and value.strip().lower() != "false"


def _form_details(
    node: SnapshotNode, base: str
) -> tuple[str | None, str, str, bool]:
    """The form's action, resolved URL, method, and cross-origin verdict."""
    action = _attr(node, "action")
    resolved = _resolve(base, action) if action else base
    method = (_attr(node, "method") or "get").strip().upper()
    return action, resolved, method, bool(action) and not _same_origin(base, resolved)


def _meta_refresh_url(content: str) -> str:
    lowered = content.lower()
    index = lowered.find("url=")
    if index < 0:
        return ""
    return content[index + 4 :].strip().strip("'\"")


def _classify(
    node: SnapshotNode,
    base: str,
    form: SnapshotNode | None,
    settings: ProjectElementSettings | None,
) -> _Classified | None:
    """Apply a project rule over the generic map, first matching rule winning."""
    rule = _matching_rule(node, settings)
    classified = _classify_raw(node, base, form)
    if rule is None:
        return classified
    if classified is None:
        return _Classified(
            rule.element_type,
            channel=rule.channel,
            explicit_channel=rule.channel is not None,
        )
    return replace(
        classified,
        element_type=rule.element_type,
        channel=rule.channel or classified.channel,
        explicit_channel=rule.channel is not None,
    )


def _matching_rule(
    node: SnapshotNode, settings: ProjectElementSettings | None
) -> RawSelectorRule | None:
    if settings is None:
        return None
    for rule in settings.rules:
        if _selector_matches(rule.selector, node):
            return rule
    return None


_SIMPLE_SELECTOR = re.compile(
    r"^(?:(?P<tag>[A-Za-z][\w-]*|\*))?"
    r"(?:\[(?P<attr>[\w:.-]+)"
    r"(?:=(?P<value>\"[^\"]*\"|'[^']*'|[^\]]*))?\])?$"
)


def _selector_matches(selector: str, node: SnapshotNode) -> bool:
    match = _SIMPLE_SELECTOR.fullmatch(selector.strip())
    if match is None:
        return False
    tag = match.group("tag")
    attr = match.group("attr")
    if tag is None and attr is None:
        return False
    if tag is not None and tag != "*" and tag.lower() != _tag(node):
        return False
    if attr is None:
        return True
    value = _attr(node, attr.lower())
    if value is None and attr.lower() == "role":
        value = node.role
    if value is None:
        return False
    wanted = match.group("value")
    if wanted is None:
        return True
    return value == wanted.strip("'\"")


def _classify_raw(
    node: SnapshotNode, base: str, form: SnapshotNode | None
) -> _Classified | None:
    """The three-layer map (spec 6.2) for one node, or None if excluded."""
    tag = _tag(node)
    role = _role(node)
    href = _attr(node, "href")

    if tag == "meta" and (_attr(node, "http-equiv") or "").strip().lower() == "refresh":
        content = _attr(node, "content") or ""
        url = _meta_refresh_url(content)
        return _Classified(
            ElementType.META_REFRESH,
            resolved=_resolve(base, url) if url else base,
            confidence=1.0,
        )

    if _dialog_state(node, tag, role):
        return _Classified(ElementType.DIALOG_STATE)
    if tag in _STATE_CONTAINER_TAGS:
        return None

    if (
        tag in _FORM_FIELD_TAGS
        or _contenteditable(node)
        or role in _FIELD_ROLES
    ):
        return None

    # Native HTML semantics decide first; an explicit widget role re-types an
    # anchor or button otherwise, and the remaining raw signals follow.
    if tag == "a" and href is not None:
        resolved = _resolve(base, href)
        if _has_attr(node, "download") or _download_href(href):
            return _Classified(
                ElementType.DOWNLOAD,
                href=href,
                resolved=resolved,
                handler="href",
            )
        # An external target is ignored whatever its role says.
        if not _same_origin(base, resolved):
            return _Classified(
                ElementType.EXTERNAL_LINK,
                href=href,
                resolved=resolved,
                handler="href",
            )
        if role in _WIDGET_ROLES:
            return _Classified(
                _ROLE_TYPES[role],
                href=href,
                resolved=resolved,
                handler="href",
            )
        return _Classified(
            ElementType.LINK,
            href=href,
            resolved=resolved,
            handler="href",
        )

    if tag == "area":
        if href is None:
            return None
        resolved = _resolve(base, href)
        external = not _same_origin(base, resolved)
        return _Classified(
            ElementType.EXTERNAL_AREA if external else ElementType.AREA,
            href=href,
            resolved=resolved,
            handler="href",
        )

    if tag == "form":
        action, resolved, method, external = _form_details(node, base)
        return _Classified(
            ElementType.EXTERNAL_FORM if external else ElementType.FORM,
            action=action,
            resolved=resolved,
            method=method,
            handler=_handler(node, default="onsubmit"),
        )

    if tag == "button":
        button_type = _attr(node, "type")
        if button_type is None:
            button_type = "submit" if form is not None else "button"
        if button_type.strip().lower() == "submit" and form is not None:
            action, resolved, method, external = _form_details(form, base)
            return _Classified(
                ElementType.EXTERNAL_FORM if external else ElementType.FORM,
                action=action,
                resolved=resolved,
                method=method,
                handler=_handler(node, default="onsubmit"),
                synthetic=True,
            )
        if role in _WIDGET_ROLES and role != "button":
            return _Classified(_ROLE_TYPES[role], handler=_handler(node))
        return _Classified(ElementType.BUTTON, handler=_handler(node))

    if tag == "summary":
        return _Classified(ElementType.DISCLOSURE, handler=_handler(node))

    if tag in {"iframe", "frame"}:
        src = _attr(node, "src")
        if src is None:
            return None
        resolved = _resolve(base, src)
        same_origin = _same_origin(base, resolved)
        if tag == "iframe":
            element_type = (
                ElementType.IFRAME if same_origin else ElementType.EXTERNAL_IFRAME
            )
            return _Classified(element_type, resolved=resolved)
        return _Classified(
            ElementType.FRAME,
            resolved=resolved,
            channel=None if same_origin else Channel.IGNORE,
        )

    if tag in {"svg", "canvas"}:
        if _has_attr(node, "onclick") or (tag == "svg" and role == "button"):
            return _Classified(ElementType.CLICKABLE, handler=_handler(node))
        return None

    if _is_custom_element(tag):
        signal = bool(role) or _has_handler(node)
        return _Classified(
            ElementType.CUSTOM,
            handler=_handler(node),
            channel=Channel.OFFER if signal else Channel.IGNORE,
            confidence=1.0 if signal else 0.5,
        )

    if role in _ROLE_TYPES:
        return _Classified(_ROLE_TYPES[role], handler=_handler(node))

    if _has_attr(node, "onclick"):
        return _Classified(ElementType.CLICKABLE, handler="onclick")

    if (_attr(node, "draggable") or "").strip().lower() == "true":
        return _Classified(ElementType.DRAGGABLE, handler=_handler(node))

    if _has_attr(node, "tabindex") and (role or _has_handler(node)):
        return _Classified(ElementType.CUSTOM, handler=_handler(node), confidence=0.6)

    if tag in _STRUCTURE_TAGS or tag in _METADATA_TAGS:
        return None

    # An unknown element with an interactive signal is custom; one without a
    # signal is inert and ignored (spec 6.1).
    if role or _has_handler(node) or _has_attr(node, "tabindex"):
        return _Classified(ElementType.CUSTOM, handler=_handler(node), confidence=0.5)
    return None


def _may_navigate(
    element_type: ElementType,
    impact: ImpactClass,
    href: str | None,
) -> bool:
    if element_type is ElementType.DOWNLOAD or element_type is ElementType.DIALOG_STATE:
        return False
    if element_type is ElementType.FORM:
        return impact == "write"
    if impact in {"local_state", "observe"}:
        # A widget role on an anchor still navigates when it carries a real href.
        return bool(href) and not _is_fragment_only(href or "")
    return impact in {"navigate", "external"}


def _element(
    node: SnapshotNode,
    path: tuple[int, ...],
    css: str,
    classified: _Classified,
    settings: ProjectElementSettings | None,
    *,
    form: SnapshotNode | None = None,
    form_css: str | None = None,
    controls: tuple[str, ...] = (),
    control_facts: tuple[ControlFact, ...] = (),
) -> Element:
    element_type = classified.element_type
    name = (node.name or "").strip()
    text = (node.text or "").strip()
    selector = _selector(node, css)
    element_id = node.ref or _path_id(path)
    impact = _DEFAULT_IMPACT[element_type]
    capture = _DEFAULT_CAPTURE[element_type]
    if element_type is ElementType.LINK and classified.href and _is_fragment_only(
        classified.href
    ):
        impact = "local_state"
        capture = "dom"
    channel = _channel_for(
        element_type, classified.channel, classified.explicit_channel, settings
    )
    change = ChangeSemantics(
        impact=impact,
        capture=capture,
        method=classified.method,
        action=classified.resolved,
        target=classified.resolved,
        may_navigate=_may_navigate(element_type, impact, classified.href),
        controls=controls,
        control_facts=control_facts,
        handler=classified.handler,
        confidence=classified.confidence,
    )
    return Element(
        element_id=element_id,
        fingerprint=_fingerprint(
            element_type,
            name,
            text,
            classified.href,
            classified.action,
            selector,
            _path_id(path),
        ),
        element_type=element_type,
        name=name,
        text=text,
        href=classified.href,
        action=classified.action,
        selector=selector,
        channel=channel,
        impact=impact,
        capture=capture,
        change=change,
        form=_declared_contract(node, css, classified, form, form_css),
        synthetic=classified.synthetic,
        disabled=_has_attr(node, "disabled")
        or (_attr(node, "aria-disabled") or "").strip().lower() == "true",
        visible=node.visible,
    )


# The types that describe a form, whether offered, collected, or ignored (spec
# 6.2). The contract is the DOM fact; the channel decides what to do with it.
_FORM_TYPES = frozenset({ElementType.FORM, ElementType.EXTERNAL_FORM})

# The form-field types of spec 8.1, keyed by tag. A submit, reset, or plain
# button is a control, never a field, so it never enters the field list.
_FIELD_TYPES = {
    "input": "text",
    "select": "select-one",
    "textarea": "textarea",
}
_NON_FIELD_INPUT_TYPES = frozenset({"button", "image", "reset", "submit"})


def _declared_contract(
    node: SnapshotNode,
    css: str,
    classified: _Classified,
    form: SnapshotNode | None,
    form_css: str | None,
) -> FormContract | None:
    """The declared form contract a `FORM`-typed element carries (spec 8.1).

    The contract describes the form, so a submit control carries exactly its
    form's contract: `root_selector` is the form element's selector, and the
    submit control is the form's first one. A node typed `FORM` without a form
    element or without a resolved action has no contract to describe.
    """
    if classified.element_type not in _FORM_TYPES:
        return None
    root = node if _tag(node) == "form" else form
    if root is None or not classified.resolved:
        return None
    root_css = css if root is node else (form_css or "")
    submit_selector, submit_text = _submit_control(root, root_css)
    return FormContract(
        root_selector=_selector(root, root_css),
        action=classified.resolved,
        method=classified.method or DEFAULT_METHOD,
        enctype=(_attr_text(root, "enctype") or DEFAULT_ENCTYPE).lower(),
        fields=_form_fields(root, root_css),
        submit_selector=submit_selector,
        submit_text=submit_text,
    )


def _form_fields(root: SnapshotNode, root_css: str) -> tuple[FormField, ...]:
    """The form's field contract, in document order, values excluded (spec 8.1)."""
    fields: list[FormField] = []
    for node, css in _descendants(root, root_css):
        field = _form_field(node, css)
        if field is not None:
            fields.append(field)
    return tuple(fields)


def _form_field(node: SnapshotNode, css: str) -> FormField | None:
    """One field contract, or `None` for a control that is not a field."""
    tag = _tag(node)
    default_type = _FIELD_TYPES.get(tag)
    if default_type is None:
        return None
    field_type = default_type
    if tag == "input":
        field_type = (_attr_text(node, "type") or default_type).lower()
        if field_type in _NON_FIELD_INPUT_TYPES:
            return None
    elif tag == "select" and _has_attr(node, "multiple"):
        field_type = "select-multiple"
    return FormField(
        name=(_attr_text(node, "name") or ""),
        type=field_type,
        label=(node.name or "").strip(),
        options=_option_values(node) if tag == "select" else (),
        pattern=_attr_text(node, "pattern"),
        min=_attr_text(node, "min"),
        max=_attr_text(node, "max"),
        checked=_has_attr(node, "checked"),
        selector=_selector(node, css),
    )


def _option_values(node: SnapshotNode) -> tuple[str, ...]:
    """The option values of a select in document order.

    An option without a `value` attribute submits its own text, so the text is
    the value; the option text itself is not part of the contract.
    """
    values: list[str] = []
    for child, _ in _descendants(node, ""):
        if _tag(child) == "option":
            value = _attr(child, "value")
            values.append(
                value if value is not None else (child.text or child.name or "").strip()
            )
    return tuple(values)


def _submit_control(root: SnapshotNode, root_css: str) -> tuple[str | None, str]:
    """The form's submit control: its selector and its label (spec 8.1).

    The first submit control in document order is the form's submit surface. A
    button with no explicit type is a submit inside a form; a submit or image
    input submits too. A form with no submit control reports none, so the
    executor submits it through `requestSubmit()` instead.
    """
    for node, css in _descendants(root, root_css):
        if _is_submit_control(node):
            return _selector(node, css), _control_text(node)
    return None, ""


def _is_submit_control(node: SnapshotNode) -> bool:
    tag = _tag(node)
    if tag == "button":
        return (_attr_text(node, "type") or "submit").lower() == "submit"
    if tag == "input":
        return (_attr_text(node, "type") or "").lower() in {"image", "submit"}
    return False


def _control_text(node: SnapshotNode) -> str:
    """A submit control's label: its text, its name, else its value attribute."""
    return (
        (node.text or "").strip()
        or (node.name or "").strip()
        or (_attr_text(node, "value") or "")
    )


def _descendants(node: SnapshotNode, css: str) -> Iterator[tuple[SnapshotNode, str]]:
    """Every descendant in document order, with the selector path it would carry."""
    for index, child in enumerate(node.children):
        child_css = f"{css} > {_tag(child) or '*'}:nth-child({index + 1})"
        yield child, child_css
        yield from _descendants(child, child_css)


def _channel_for(
    element_type: ElementType,
    signal_channel: Channel | None,
    explicit: bool,
    settings: ProjectElementSettings | None,
) -> Channel:
    """A rule's channel beats project policy, which beats the type default."""
    if explicit and signal_channel is not None:
        return signal_channel
    if settings is not None and element_type in settings.channels:
        return settings.channels[element_type]
    if signal_channel is not None:
        return signal_channel
    return _DEFAULT_CHANNEL[element_type]


def _selector(node: SnapshotNode, css: str) -> str:
    explicit = _attr(node, "data-selector")
    if explicit:
        return explicit
    if node.ref:
        return f"@{node.ref}"
    return css


def _path_id(path: tuple[int, ...]) -> str:
    return "n" + ".".join(str(index + 1) for index in path)


# A bound on the compact line, the label, and the line count, so one huge page
# can never make the projection grow without bound.
_MAX_LABEL = 60
_MAX_REF = 48
_MAX_PROJECTION_LINES = 40


def _bounded_label(value: str) -> str:
    label = " ".join(value.split()).replace('"', '\\"')
    if len(label) > _MAX_LABEL:
        label = label[: _MAX_LABEL - 3] + "..."
    return label


def _bounded_ref(value: str) -> str:
    if len(value) > _MAX_REF:
        return value[: _MAX_REF - 3] + "..."
    return value


def render_projection(
    elements: Iterable[Element],
    *,
    consumed: Collection[str] = (),
    limit: int = _MAX_PROJECTION_LINES,
) -> list[str]:
    """One short, deterministic line per element, with a consumed marker.

    The format is the browserclaw-compact shape: `- type "label" [ref=id]`, a
    `[collect]` or `[ignore]` marker for a non-offered channel, and a
    `[consumed]` marker when the fingerprint is in the consumed set. The line
    count and the label length are bounded; the tail is summarized.
    """
    ordered = list(elements)
    consumed_set = set(consumed)
    bound = max(0, limit)
    lines: list[str] = []
    for element in ordered[:bound]:
        line = (
            f'- {element.element_type.value.lower()} '
            f'"{_bounded_label(element.name or element.text)}" '
            f"[ref={_bounded_ref(element.element_id)}]"
        )
        if element.channel is not Channel.OFFER:
            line += f" [{element.channel.value}]"
        if element.fingerprint in consumed_set:
            line += " [consumed]"
        lines.append(line)
    remaining = len(ordered) - bound
    if remaining > 0:
        lines.append(f"- ... ({remaining} more)")
    return lines


@dataclass
class _ParsedTree:
    """A mutable parse node; the immutable `SnapshotNode` tree is minted after."""

    tag: str
    ref: str | None
    name: str | None
    attributes: dict[str, str]
    children: list["_ParsedTree"] = field(default_factory=list)


_TREE_LINE = re.compile(
    r'^-\s+(?P<role>[^\s"\[]+)(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?'
    r"(?P<attrs>(?:\s+\[[^\]]+\])*)\s*$"
)
_TREE_ATTR = re.compile(
    r"\[(?P<key>[^\]=]+)(?:=(?P<value>\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\]]*))?\]"
)


def parse_snapshot_tree(text: str) -> tuple[SnapshotNode, ...]:
    """Parse the compact CLI snapshot tree into the normalized node model.

    Each line is `- role "name" [attr=value]`, indented one level per depth. The
    compact tree carries the accessible role and the document-scoped ref; the
    raw tag is not recoverable, so the role doubles as the tag. A malformed line
    raises instead of degrading into an empty candidate set.
    """
    roots: list[_ParsedTree] = []
    stack: list[tuple[int, _ParsedTree]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        parsed = _parse_tree_line(raw_line.strip())
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if stack:
            stack[-1][1].children.append(parsed)
        else:
            roots.append(parsed)
        stack.append((indent, parsed))
    return tuple(_tree_node(parsed) for parsed in roots)


def _parse_tree_line(line: str) -> _ParsedTree:
    match = _TREE_LINE.fullmatch(line)
    if match is None:
        raise ValueError(f"not a compact snapshot line: {line!r}")
    role = match.group("role").lower()
    name = match.group("name")
    if name is not None:
        name = name.replace('\\"', '"').replace("\\\\", "\\")
    attributes: dict[str, str] = {}
    for attribute in _TREE_ATTR.finditer(match.group("attrs") or ""):
        value = attribute.group("value")
        attributes[attribute.group("key").lower()] = (
            "" if value is None else value.strip("'\"")
        )
    return _ParsedTree(
        tag=role,
        ref=attributes.get("ref") or None,
        name=name,
        attributes=attributes,
    )


def _tree_node(parsed: _ParsedTree) -> SnapshotNode:
    return SnapshotNode(
        tag=parsed.tag,
        ref=parsed.ref,
        role=parsed.tag,
        name=parsed.name,
        attributes=parsed.attributes,
        children=tuple(_tree_node(child) for child in parsed.children),
    )


__all__ = [
    "Channel",
    "ChangeSemantics",
    "ControlFact",
    "Element",
    "ElementMap",
    "ElementType",
    "ProjectElementSettings",
    "RawSelectorRule",
    "SnapshotNode",
    "parse_snapshot_tree",
    "render_projection",
]
