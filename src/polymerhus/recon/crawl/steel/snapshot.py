"""The compact CLI snapshot parser and the JS form projection merge.

Spec: `docs/design/steel-crawl-spec.md` sections 2.3 (I2), 5, and 8.1.

The Steel CLI's `snapshot -i -c -u` output is the candidate surface: one
indented line per accessibility node, carrying the document ref the action
verbs accept, the role, the accessible name, a link's URL, and the control
states. It deliberately does not carry raw HTML attributes (a form's action and
method, a field's name and type), so the page factory also runs one JS form
projection and merges each projected form into the tree as a synthetic form
node. A synthetic node names its CSS selector explicitly; a snapshot node keeps
its `@ref`.

The parser is pure: the text in, a tuple of `SnapshotNode` roots out. The JS
projection is returned by `form_projection_script` and parsed by
`parse_form_projections`; the merge appends the synthetic forms at the root.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from polymerhus.recon.crawl.steel.enumerate import SnapshotNode

# The compact line grammar: indentation, the `- ` marker, and the rest.
_LINE_RE = re.compile(r"^(?P<indent> *)- (?P<body>.*)$")
_ROLE_RE = re.compile(r"^(?P<role>[A-Za-z][A-Za-z0-9_-]*)(?:\s+|$)")
_DOUBLE_QUOTED_RE = re.compile(r'"(?P<value>(?:\\.|[^"\\])*)"')
_SINGLE_QUOTED_RE = re.compile(r"'(?P<value>(?:\\.|[^'\\])*)'")
_BRACKET_RE = re.compile(r"\[(?P<body>[^\]]*)\]")

# Roles whose tag is decided before the generic structure fallback.
_ROLE_TAGS: dict[str, str] = {
    "link": "a",
    "button": "button",
    "textbox": "input",
    "searchbox": "input",
    "checkbox": "input",
    "radio": "input",
    "slider": "input",
    "spinbutton": "input",
    "switch": "input",
    "combobox": "select",
    "listbox": "select",
    "option": "option",
    "textarea": "textarea",
    "form": "form",
    "iframe": "iframe",
    "frame": "iframe",
    "img": "img",
    "image": "img",
    "canvas": "canvas",
    "list": "ul",
    "menu": "ul",
    "menubar": "ul",
    "tablist": "ul",
    "tree": "ul",
    "listitem": "li",
    "menuitem": "div",
    "menuitemcheckbox": "div",
    "menuitemradio": "div",
    "tab": "div",
    "treeitem": "div",
    "table": "table",
    "grid": "table",
    "treegrid": "table",
    "row": "tr",
    "cell": "td",
    "gridcell": "td",
    "columnheader": "th",
    "rowheader": "th",
    "paragraph": "p",
    "statictext": "span",
    "inlinetextbox": "span",
    "generic": "div",
    "none": "div",
    "presentation": "div",
    "group": "div",
    "region": "section",
    "banner": "header",
    "navigation": "nav",
    "main": "main",
    "contentinfo": "footer",
    "complementary": "aside",
    "article": "article",
    "section": "section",
    "figure": "figure",
}

# The input type a role implies when the line carries no explicit type.
_ROLE_INPUT_TYPES: dict[str, str] = {
    "textbox": "text",
    "searchbox": "search",
    "checkbox": "checkbox",
    "radio": "radio",
    "slider": "range",
    "spinbutton": "number",
    "switch": "checkbox",
}

_FIELD_TYPES = frozenset(
    {
        "select-one",
        "select-multiple",
        "textarea",
        "checkbox",
        "radio",
        "file",
        "range",
    }
)


@dataclass
class ProjectedField:
    """One field the JS form projection returned, with its CSS selector."""

    name: str
    type: str
    label: str = ""
    selector: str = ""
    options: tuple[str, ...] = ()
    pattern: str | None = None
    min: str | None = None
    max: str | None = None
    checked: bool = False


@dataclass
class FormProjection:
    """One live form and the contract facts the snapshot does not carry."""

    selector: str
    action: str
    method: str = "GET"
    enctype: str = "application/x-www-form-urlencoded"
    fields: tuple[ProjectedField, ...] = ()
    submit_selector: str | None = None
    submit_text: str = ""


@dataclass
class _Draft:
    """A mutable tree node used while the indentation is being consumed."""

    tag: str
    ref: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    visible: bool = True
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["_Draft"] = field(default_factory=list)


def _parse_attributes(body: str) -> dict[str, str]:
    """Parse every `[a=b, c]` group into the raw attribute map.

    A bare token is a state (`clickable`, `focusable`, `onclick`, `disabled`);
    a `cursor:pointer` token is a pointer state. Both are represented as
    attributes because the element map reads the raw signals.
    """
    attributes: dict[str, str] = {}
    for match in _BRACKET_RE.finditer(body):
        for token in match.group("body").split(", "):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                name, value = token.split("=", 1)
                attributes[name.strip()] = value.strip()
            elif ":" in token:
                attributes[token.strip()] = ""
            else:
                attributes[token.strip()] = ""
    for state in ("clickable", "focusable", "disabled", "expanded", "selected", "checked"):
        if state in body and state not in attributes:
            attributes[state] = "true"
    return attributes


def _quoted_name(body: str) -> str | None:
    """The first quoted accessible name, unescaped; `None` when absent."""
    match = _DOUBLE_QUOTED_RE.search(body) or _SINGLE_QUOTED_RE.search(body)
    if match is None:
        return None
    value = match.group("value")
    return value.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")


def _tag_and_attributes(
    role: str, attributes: dict[str, str]
) -> tuple[str, str, dict[str, str]]:
    """The tag, the normalized role, and the raw attributes for one node."""
    role_l = role.lower()
    tag = _ROLE_TAGS.get(role_l, "div")
    if role_l == "heading":
        level = attributes.get("level", "2")
        tag = f"h{level}" if level.isdigit() else "h2"
    if role_l in _ROLE_INPUT_TYPES:
        attributes.setdefault("type", _ROLE_INPUT_TYPES[role_l])
    if role_l in {"checkbox", "radio", "switch"} and attributes.get("checked") == "false":
        attributes.pop("checked", None)
    if "url" in attributes:
        attributes.setdefault("href", attributes["url"])
    if "clickable" in attributes or "cursor:pointer" in attributes:
        attributes.setdefault("onclick", "")
    if "focusable" in attributes:
        attributes.setdefault("tabindex", "0")
    if "onclick" in attributes:
        attributes.setdefault("onclick", "")
    return tag, role, attributes


def _draft_from_line(body: str) -> _Draft | None:
    match = _ROLE_RE.match(body.strip())
    if match is None:
        return None
    role = match.group("role")
    attributes = _parse_attributes(body)
    tag, role, attributes = _tag_and_attributes(role, attributes)
    name = _quoted_name(body)
    return _Draft(
        tag=tag,
        ref=attributes.pop("ref", None),
        role=role,
        name=name,
        text=name,
        visible="hidden" not in attributes,
        attributes=attributes,
    )


def _convert(draft: _Draft) -> SnapshotNode:
    return SnapshotNode(
        tag=draft.tag,
        ref=draft.ref,
        role=draft.role,
        name=draft.name,
        text=draft.text,
        visible=draft.visible,
        attributes=draft.attributes,
        children=tuple(_convert(child) for child in draft.children),
    )


def parse_compact_snapshot(text: str, *, base_url: str) -> tuple[SnapshotNode, ...]:
    """Parse `snapshot -i -c -u` output into the normalized tree roots.

    `base_url` is accepted for the caller's symmetry with the form projection;
    the parser itself never resolves a URL. An empty or unknown line is skipped,
    never a hard failure: the CLI can add a new role without breaking the crawl.
    """
    del base_url
    roots: list[_Draft] = []
    stack: list[tuple[int, _Draft]] = []
    for raw in text.splitlines():
        match = _LINE_RE.match(raw.rstrip())
        if match is None:
            continue
        draft = _draft_from_line(match.group("body"))
        if draft is None:
            continue
        indent = len(match.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1].children.append(draft)
        else:
            roots.append(draft)
        stack.append((indent, draft))
    return tuple(_convert(root) for root in roots)


def _field_node(field: ProjectedField) -> SnapshotNode:
    """One synthetic field node carrying the raw contract and its CSS selector."""
    if field.type in {"select-one", "select-multiple"}:
        tag = "select"
    elif field.type == "textarea":
        tag = "textarea"
    else:
        tag = "input"
    attributes: dict[str, str] = {"data-selector": field.selector}
    if field.name:
        attributes["name"] = field.name
    if field.type:
        attributes["type"] = field.type
    if field.pattern:
        attributes["pattern"] = field.pattern
    if field.min is not None:
        attributes["min"] = field.min
    if field.max is not None:
        attributes["max"] = field.max
    if field.checked:
        attributes["checked"] = "true"
    children: tuple[SnapshotNode, ...] = ()
    if tag == "select":
        children = tuple(
            SnapshotNode(
                tag="option",
                name=option,
                text=option,
                attributes={"value": option},
            )
            for option in field.options
        )
    return SnapshotNode(
        tag=tag,
        name=field.label or field.name,
        text=field.label or field.name,
        attributes=attributes,
        children=children,
    )


def _form_node(form: FormProjection) -> SnapshotNode:
    """One synthetic form node with its fields and submit control."""
    children = tuple(_field_node(field) for field in form.fields)
    if form.submit_selector:
        children = children + (
            SnapshotNode(
                tag="button",
                name=form.submit_text,
                text=form.submit_text,
                attributes={
                    "type": "submit",
                    "data-selector": form.submit_selector,
                },
            ),
        )
    return SnapshotNode(
        tag="form",
        attributes={
            "action": form.action,
            "method": form.method.upper(),
            "enctype": form.enctype.lower(),
            "data-selector": form.selector,
        },
        children=children,
    )


def merge_form_projections(
    roots: tuple[SnapshotNode, ...],
    forms: list[FormProjection] | tuple[FormProjection, ...],
) -> tuple[SnapshotNode, ...]:
    """Append one synthetic form node per projected form.

    The snapshot's own field nodes stay in the tree; the element map ignores
    them as fields, so only the synthetic form contract is offered.
    """
    return tuple(roots) + tuple(_form_node(form) for form in forms)


def form_projection_script() -> str:
    """The one JS expression that returns the live page's forms as JSON.

    The selector is a CSS path, because the CLI's `fill`, `select`, `check`,
    and `eval` verbs accept either a ref or a CSS selector. The form root and
    its fields therefore survive the compact snapshot's missing raw attributes.
    """
    return _FORM_PROJECTION_JS


def parse_form_projections(raw: Any) -> list[FormProjection]:
    """Parse the JS projection payload; a malformed payload is empty, not fatal."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    forms: list[FormProjection] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        selector = entry.get("selector")
        action = entry.get("action")
        if not isinstance(selector, str) or not selector:
            continue
        if not isinstance(action, str) or not action:
            continue
        fields: list[ProjectedField] = []
        for item in entry.get("fields") or []:
            if not isinstance(item, dict):
                continue
            field_type = item.get("type")
            field_selector = item.get("selector")
            if not isinstance(field_type, str) or not isinstance(field_selector, str):
                continue
            options = item.get("options")
            fields.append(
                ProjectedField(
                    name=str(item.get("name") or ""),
                    type=field_type,
                    label=str(item.get("label") or ""),
                    selector=field_selector,
                    options=tuple(
                        str(option) for option in options
                    )
                    if isinstance(options, list)
                    else (),
                    pattern=_opt_text(item.get("pattern")),
                    min=_opt_text(item.get("min")),
                    max=_opt_text(item.get("max")),
                    checked=bool(item.get("checked")),
                )
            )
        forms.append(
            FormProjection(
                selector=selector,
                action=action,
                method=str(entry.get("method") or "GET").upper(),
                enctype=str(
                    entry.get("enctype")
                    or "application/x-www-form-urlencoded"
                ).lower(),
                fields=tuple(fields),
                submit_selector=_opt_text(entry.get("submit_selector")),
                submit_text=str(entry.get("submit_text") or ""),
            )
        )
    return forms


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


_FORM_PROJECTION_JS = r"""
(() => {
  const cssPath = (el) => {
    if (!el || el.nodeType !== 1) return "";
    if (el.id) return "#" + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      let part = node.tagName.toLowerCase();
      if (node.name) {
        part += "[name=\"" + CSS.escape(node.name) + "\"]";
      } else {
        let index = 1;
        let sibling = node;
        while ((sibling = sibling.previousElementSibling)) {
          if (sibling.tagName === node.tagName) index += 1;
        }
        part += ":nth-of-type(" + index + ")";
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const labelOf = (el) => {
    const labels = el.labels ? Array.from(el.labels) : [];
    if (labels.length) return (labels[0].innerText || labels[0].textContent || "").trim();
    return String(
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      el.getAttribute("title") ||
      el.name ||
      el.id ||
      ""
    ).trim();
  };
  const fieldType = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === "select") return el.multiple ? "select-multiple" : "select-one";
    if (tag === "textarea") return "textarea";
    return String(el.type || "text").toLowerCase();
  };
  const forms = Array.from(document.forms).map((form) => {
    const fields = Array.from(form.elements)
      .filter((el) => ["input", "select", "textarea"].includes(el.tagName.toLowerCase()))
      .filter((el) => fieldType(el) !== "hidden")
      .map((el) => ({
        name: String(el.name || ""),
        type: fieldType(el),
        label: labelOf(el),
        selector: cssPath(el),
        options: el.tagName.toLowerCase() === "select"
          ? Array.from(el.options).map((o) => String(o.value))
          : [],
        pattern: el.getAttribute("pattern") || null,
        min: el.getAttribute("min"),
        max: el.getAttribute("max"),
        checked: Boolean(el.checked),
      }));
    const submit = form.querySelector(
      'button[type="submit"], input[type="submit"], input[type="image"], button:not([type])'
    );
    return {
      selector: cssPath(form),
      action: form.action || location.href,
      method: String(form.method || "GET").toUpperCase(),
      enctype: String(form.enctype || "application/x-www-form-urlencoded").toLowerCase(),
      fields,
      submit_selector: submit ? cssPath(submit) : null,
      submit_text: submit ? String(submit.innerText || submit.value || "").trim() : "",
    };
  });
  return JSON.stringify(forms);
})()
"""


__all__ = [
    "FormProjection",
    "ProjectedField",
    "form_projection_script",
    "merge_form_projections",
    "parse_compact_snapshot",
    "parse_form_projections",
]
