"""The parameter records: the form contract, the declared records, and the extractor.

Spec: `docs/design/steel-crawl-spec.md` sections 2.6, 8.1, 8.3, and 8.4.

Two provenances, two record sets, one vocabulary. The declared side is the DOM
contract a form offers (`FormContract` and `FormField`) and the records the
collector writes from it (`DeclaredEndpoint`, `DeclaredField`). The observed side
is the extractor over network flows (`ObservedParameter`), which records only the
shape of a parameter and never its value (spec P2). The two never merge: each
record's `provenance` is a literal of its own source, so one record can neither
claim both provenances nor be written by the other's builder.

A record carries the fields the graph needs (spec 8.4). The graph `Parameter`
identity is `name`, `position`, `endpoint_path`, and `baseurl`; `ParameterIdentity`
is that tuple, and `location` here is the crawl's name for the graph's `position`.
The graph `Endpoint` identity is `path`, `method`, and `baseurl`, all three of
which the endpoint records carry.

Nothing here performs I/O or reads a clock: a flow is a plain mapping, and an
identity is a hash of its own content, so the same flow always mints the same
record (CODING_STANDARD sections 6 and 9).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, computed_field

from polymerhus.recon.crawl.steel.state import normalize_url
from polymerhus.recon.domain.noise_filter import (
    CACHE_BUST_KEYS,
    is_static_file_path,
)

# A parameter name is a route word, a query key, or a field name, never a data
# payload. A base64 blob used as a path segment would otherwise become a
# 162 KiB "name" repeated on every flow; longer names are not parameter names.
MAX_PARAMETER_NAME = 256

# A static-file URL has no path parameters: the directory segments are not a
# route (`/uploads/20181226/<hash>.png`, `/static/plugins/.../select2.js`).
# The endpoint stays (uploads and JS are real surfaces); only the false
# identifier is dropped.

# The value shape types (spec 8.3). A shape is a type and a length band: `uuid`,
# `hex`, and `token` are the identifier shapes the path detector recognises;
# `number` is an all-digit value; anything else is a `string`, and an empty or
# untyped value is `unknown`.
ValueType = Literal[
    "string",
    "number",
    "boolean",
    "null",
    "uuid",
    "hex",
    "token",
    "array",
    "object",
    "unknown",
]

# Where a parameter sits in the request (spec 8.3). The graph calls the same
# value `position`; `ParameterIdentity` is the one place the two names meet.
ParameterLocation = Literal["query", "path", "body"]

# The HTML defaults of an offered form (spec 8.1): a form without an explicit
# method submits a GET, and a form without an enctype posts URL-encoded.
DEFAULT_METHOD = "GET"
DEFAULT_ENCTYPE = "application/x-www-form-urlencoded"

# A length band is eight characters wide and capped, so it says how long a value
# was without saying what it was.
_BAND_SIZE = 8
_MAX_LENGTH_BAND = 12


class FormField(BaseModel):
    """One field of a form contract (spec 8.1), never its value.

    `options` are the option values in document order; `min` and `max` are the
    DOM attribute text, so a numeric or date bound keeps its own shape. There is
    deliberately no `required`: the DOM attribute may exist and the executor
    fills every field it can (spec 8.1), but it is not part of the model.
    """

    model_config = ConfigDict(frozen=True)

    name: str = ""
    type: str = ""
    label: str = ""
    options: tuple[str, ...] = ()
    pattern: str | None = None
    min: str | None = None
    max: str | None = None
    checked: bool = False
    selector: str = ""

    def to_policy_field(self) -> dict[str, Any]:
        """The field contract mapping the value selector consumes, value-free."""
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "options": list(self.options),
            "pattern": self.pattern,
            "min": self.min,
            "max": self.max,
            "checked": self.checked,
            "selector": self.selector,
        }


class FormContract(BaseModel):
    """The declared shape of one offered form (spec 8.1).

    `action` is absolute against the page, `method` is upper-cased with the HTML
    default, and `enctype` is the form's own value with the HTML default. The
    `fingerprint` names the submission the form produces: it is stable over the
    method, action, enctype, and each field's name, type, options, pattern, min,
    and max, and over nothing else. Relabelling a field, changing a DOM selector,
    or opening two identical forms does not mint a second submission (spec P4).
    """

    model_config = ConfigDict(frozen=True)

    root_selector: str
    action: str
    method: str = DEFAULT_METHOD
    enctype: str = DEFAULT_ENCTYPE
    fields: tuple[FormField, ...] = ()
    submit_selector: str | None = None
    submit_text: str = ""

    @computed_field
    @property
    def fingerprint(self) -> str:
        """The stable name of the submission this contract produces (spec P4).

        It is stable over the form's semantic identity - method, action, enctype,
        and each field's name, type, options, pattern, min, and max - and not
        over DOM detail: a re-rendered form with new refs or a different submit
        selector is the same submission, so it must not mint a second one.
        """
        payload = "\x1f".join(
            (
                self.method,
                self.action,
                self.enctype,
                "\x1e".join(
                    "\x1d".join(
                        (
                            field.name,
                            field.type,
                            "|".join(field.options),
                            field.pattern or "",
                            field.min or "",
                            field.max or "",
                        )
                    )
                    for field in self.fields
                ),
            )
        )
        return _sha(payload)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _band(length: int) -> int:
    """The eight-character length band of a value, capped (spec 8.3)."""
    return min(length // _BAND_SIZE, _MAX_LENGTH_BAND)


class ValueShape(BaseModel):
    """The shape of one value: its type and its length band, never the value.

    The band is eight characters wide and capped, so it says how long a value was
    without saying what it was (spec P2: the graph has no parameter value).
    """

    model_config = ConfigDict(frozen=True)

    type: ValueType
    length_band: int = Field(default=0, ge=0, le=_MAX_LENGTH_BAND)


# The value shapes of spec 8.3. A numeric id is all digits; a uuid is
# uuid-shaped; a long hex is sixteen or more hex characters; a token is six or
# more alphanumerics that mix letters and digits, so a plain route word such as
# `products` is never an identifier; anything else is a string.
_NUMBER = re.compile(r"\d+")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_HEX = re.compile(r"[0-9a-f]{16,}", re.IGNORECASE)
_ALNUM = re.compile(r"[A-Za-z0-9]{6,}")


def value_shape(value: str) -> ValueShape:
    """The shape of one value: its type and its length band, never the value."""
    return ValueShape(type=_value_type(value), length_band=_band(len(value)))


def shape_of(value: Any) -> ValueShape:
    """The shape of one decoded value, never the value itself (spec 8.3).

    JSON bodies carry typed values, so the shape keeps the JSON type; a string
    keeps the richer string kinds (`uuid`, `hex`, `token`, `number`). A list or
    an object records the item count as its band and is not flattened: only an
    object's leaf attributes become parameters, because that is what the name of
    a request attribute means.
    """
    if value is None:
        return ValueShape(type="null", length_band=0)
    if isinstance(value, bool):
        return ValueShape(type="boolean", length_band=0)
    if isinstance(value, (int, float)):
        return ValueShape(type="number", length_band=_band(len(str(value))))
    if isinstance(value, str):
        return value_shape(value)
    if isinstance(value, (list, tuple)):
        return ValueShape(type="array", length_band=_band(len(value)))
    if isinstance(value, Mapping):
        return ValueShape(type="object", length_band=_band(len(value)))
    return ValueShape(type="unknown", length_band=0)


def _value_type(value: str) -> ValueType:
    if not value:
        return "unknown"
    if _NUMBER.fullmatch(value):
        return "number"
    if _UUID.fullmatch(value):
        return "uuid"
    if _HEX.fullmatch(value):
        return "hex"
    if _identifier_token(value):
        return "token"
    return "string"


def _identifier_token(value: str) -> bool:
    """Whether a value looks like a generated token rather than a word."""
    return (
        _ALNUM.fullmatch(value) is not None
        and any(character.isdigit() for character in value)
        and any(character.isalpha() for character in value)
    )


class ObservedParameter(BaseModel):
    """One parameter observed in a network flow (spec 8.3), never its value.

    `endpoint_key` names the endpoint the flow called; `location` is the crawl's
    name for the graph's `position`, and `endpoint_path` and `baseurl` are the
    other two graph identity values (spec 8.4), so the record carries everything
    the graph needs to anchor the parameter. `content_type` is the body content
    type the parameter came from: a query or path parameter has none.

    There is no rank and no secret-value drop: every observed parameter is
    recorded with its shape only (spec 8.3).
    """

    model_config = ConfigDict(frozen=True)

    endpoint_key: str
    method: str
    location: ParameterLocation
    name: str
    value_shape: ValueShape
    source_flow_id: str
    content_type: str | None = None
    endpoint_path: str
    baseurl: str
    provenance: Literal["observed"] = "observed"

    @property
    def identity(self) -> ParameterIdentity:
        """The graph `Parameter` identity of this observed parameter (spec 8.4)."""
        return ParameterIdentity(
            name=self.name,
            position=self.location,
            endpoint_path=self.endpoint_path,
            baseurl=self.baseurl,
        )

    @property
    def dedup_key(self) -> tuple[str, str, str, str]:
        """The dedup identity of spec 8.3: endpoint key, location, name, kind."""
        return (
            self.endpoint_key,
            self.location,
            self.name,
            self.value_shape.type,
        )


def endpoint_key(method: str, path: str, baseurl: str) -> str:
    """The stable endpoint key over the method, the path, and the baseurl (8.3).

    The path is templated (`/orders/{id}`), so every id of one route is the same
    endpoint; two endpoints never share a key and one endpoint never has two.
    """
    return f"{method.upper()} {baseurl}{path}"


def extract_parameters(flow: Mapping[str, Any]) -> tuple[ObservedParameter, ...]:
    """Every parameter one flow carries, deduplicated inside the flow (spec 8.3).

    The flow mapping carries `flow_id`, `method`, `url`, `request_body`, and
    `content_type`; a missing field is empty, never a guess. The network is the
    only source: URL query parameters, identifier-looking path segments, and body
    attributes. Deduplication is by endpoint key, location, name, and kind, so a
    parameter seen twice in one flow is one record.
    """
    method = _flow_text(flow, "method").upper()
    url = _flow_text(flow, "url")
    split = split_url(url)
    if split is None:
        return ()
    path, baseurl = split
    identifiers = _path_identifiers(path)
    key = endpoint_key(method, path, baseurl)
    source_flow_id = _flow_text(flow, "flow_id")
    records = [
        _observed(
            key=key,
            method=method,
            path=path,
            baseurl=baseurl,
            location="query",
            name=name,
            shape=value_shape(value),
            source_flow_id=source_flow_id,
        )
        for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
        if name.lower() not in CACHE_BUST_KEYS
    ]
    records.extend(
        _observed(
            key=key,
            method=method,
            path=path,
            baseurl=baseurl,
            location="path",
            name=identifier.name,
            shape=identifier.shape,
            source_flow_id=source_flow_id,
        )
        for identifier in identifiers
    )
    records.extend(
        _body_parameters(
            flow,
            key=key,
            method=method,
            path=path,
            baseurl=baseurl,
            source_flow_id=source_flow_id,
        )
    )
    return _dedupe(
        [record for record in records if len(record.name) <= MAX_PARAMETER_NAME]
    )


# A numeric identifier path segment is three or more digits; a short number is
# an ordinary route token, not an id (spec 8.3).
_PATH_NUMBER = re.compile(r"\d{3,}")


@dataclass(frozen=True)
class _PathIdentifier:
    """One identifier-looking path segment: the name it mints and its shape."""

    name: str
    shape: ValueShape


def _path_identifiers(path: str) -> tuple[_PathIdentifier, ...]:
    """The identifier-looking path segments, without changing the path identity.

    The observed endpoint stays the actual path that answered (spec 8.4's
    `{path, method, baseurl}` identity); the parameter records the segment and
    the name it mints, so the graph anchors the parameter to the endpoint the
    flow actually called.

    A static-file path is exempt: its directory segments (`/uploads/20181226/`)
    and its filename stem (`select2`) are not route parameters, even when they
    look like a date or a token.
    """
    if is_static_file_path(path):
        return ()
    segments = path.split("/")
    identifiers: list[_PathIdentifier] = []
    for position, segment in enumerate(segments):
        kind = _path_identifier_type(segment) if segment else None
        if kind is None:
            continue
        identifiers.append(
            _PathIdentifier(
                name=_path_identifier_name(segments, position),
                shape=ValueShape(type=kind, length_band=_band(len(segment))),
            )
        )
    return tuple(identifiers)


def _path_identifier_type(segment: str) -> ValueType | None:
    """The identifier kind a path segment looks like, or `None` (spec 8.3).

    Numeric ids, uuids, long hex values, and tokens are identifiers; a route
    word is never one, so `/products` stays a route and `/products/42` is that
    route with one id.
    """
    if _PATH_NUMBER.fullmatch(segment):
        return "number"
    if _UUID.fullmatch(segment):
        return "uuid"
    if _HEX.fullmatch(segment):
        return "hex"
    if _identifier_token(segment):
        return "token"
    return None


def _path_identifier_name(segments: Sequence[str], position: int) -> str:
    """`/orders/42` -> `orders_id`; a bare or already-templated id is `id`."""
    previous = segments[position - 1] if position > 0 else ""
    if (
        previous
        and len(previous) <= MAX_PARAMETER_NAME
        and _path_identifier_type(previous) is None
    ):
        slug = re.sub(r"[^a-z0-9]+", "_", previous.lower()).strip("_")
        if slug:
            return f"{slug}_id"
    return "id"


_JSON = "application/json"
_FORM = "application/x-www-form-urlencoded"
_MULTIPART = "multipart/form-data"


def _body_parameters(
    flow: Mapping[str, Any],
    *,
    key: str,
    method: str,
    path: str,
    baseurl: str,
    source_flow_id: str,
) -> list[ObservedParameter]:
    """The body attributes of one flow, as shapes only (spec 8.3).

    JSON bodies contribute their leaf attributes (nested objects are dotted);
    form-urlencoded bodies contribute their pairs; multipart bodies contribute
    each part's declared name. A body with no recognized content type, or a body
    that does not parse, contributes nothing: the extractor never guesses.
    """
    content_type = _base_content_type(_flow_text(flow, "content_type"))
    body = _flow_text(flow, "request_body")
    if not body or not content_type:
        return []
    if content_type == _JSON:
        pairs = _json_leaves(body)
    elif content_type == _FORM:
        pairs = list(parse_qsl(body, keep_blank_values=True))
    elif content_type == _MULTIPART:
        boundary = _multipart_boundary(_flow_text(flow, "content_type"))
        pairs = _multipart_fields(body, boundary)
    else:
        return []
    return [
        _observed(
            key=key,
            method=method,
            path=path,
            baseurl=baseurl,
            location="body",
            name=name,
            shape=shape_of(value),
            source_flow_id=source_flow_id,
            content_type=content_type,
        )
        for name, value in pairs
        if name
    ]


def _base_content_type(content_type: str) -> str:
    """The media type without its parameters (`application/json; charset=...`)."""
    return content_type.split(";", 1)[0].strip().lower()


def _json_leaves(body: str) -> list[tuple[str, Any]]:
    """Every leaf attribute of a JSON body, dotted through nested objects."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return []
    leaves: list[tuple[str, Any]] = []
    _collect_json(payload, "", leaves)
    return leaves


def _collect_json(value: Any, prefix: str, leaves: list[tuple[str, Any]]) -> None:
    if isinstance(value, Mapping):
        for name, child in value.items():
            child_prefix = f"{prefix}.{name}" if prefix else str(name)
            _collect_json(child, child_prefix, leaves)
        return
    if prefix:
        leaves.append((prefix, value))


def _multipart_boundary(content_type: str) -> str:
    match = re.search(r'boundary="?([^";]+)"?', content_type, re.IGNORECASE)
    return match.group(1) if match else ""


def _multipart_fields(body: str, boundary: str) -> list[tuple[str, str]]:
    """The named parts of a multipart body, with their values left unrecorded."""
    if not boundary:
        return []
    fields: list[tuple[str, str]] = []
    for part in body.split("--" + boundary):
        part = part.strip("\r\n")
        if not part or part == "--":
            continue
        headers, _, value = part.partition("\r\n\r\n")
        match = re.search(
            r'Content-Disposition:[^\r\n]*\bname="([^"]+)"', headers, re.IGNORECASE
        )
        if match:
            fields.append((match.group(1), value.rstrip("\r\n")))
    return fields


def _observed(
    *,
    key: str,
    method: str,
    path: str,
    baseurl: str,
    location: ParameterLocation,
    name: str,
    shape: ValueShape,
    source_flow_id: str,
    content_type: str | None = None,
) -> ObservedParameter:
    return ObservedParameter(
        endpoint_key=key,
        method=method,
        location=location,
        name=name,
        value_shape=shape,
        source_flow_id=source_flow_id,
        content_type=content_type,
        endpoint_path=path,
        baseurl=baseurl,
    )


def _flow_text(flow: Mapping[str, Any], name: str) -> str:
    value = flow.get(name)
    return "" if value is None else str(value)


def _dedupe(
    records: Iterable[ObservedParameter],
) -> tuple[ObservedParameter, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ObservedParameter] = []
    for record in records:
        if record.dedup_key in seen:
            continue
        seen.add(record.dedup_key)
        unique.append(record)
    return tuple(unique)


def split_url(url: str) -> tuple[str, str] | None:
    """The URL path without its query, and the baseurl `scheme://netloc`.

    Both halves come from `state.normalize_url`, so a trailing slash, a duplicate
    slash, or a differently cased host never mints a second endpoint identity.
    Only an absolute HTTP(S) URL has a graph endpoint: a `data:` URI, a
    `javascript:` URI, or any other scheme returns `None` and never mints one.
    This deliberately reuses `_urls.base_and_path`'s absolute-URL CONTRACT but
    not its normaliser: Steel's `state.normalize_url` folds the host casing,
    default port, duplicate slashes, and trailing slash that the crawl's state
    keys already use, so both sides of the manifest agree on one endpoint key.
    """
    parts = urlsplit(normalize_url(url))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return parts.path or "/", f"{parts.scheme}://{parts.netloc}"


class ParameterIdentity(BaseModel):
    """The graph `Parameter` identity: name, position, endpoint path, baseurl.

    Spec 8.4 keys a graph parameter on these four values and nothing else, so
    the same name at the same position of the same endpoint is one node however
    many flows or forms mentioned it.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    position: str
    endpoint_path: str
    baseurl: str


class DeclaredEndpoint(BaseModel):
    """One form endpoint the DOM declared (spec 8.4), never submitted.

    A declared endpoint has no flow, so it has no status, no HTTP artifact, and
    no action: `action_id` is `None` because the removal stage collected the form
    in place (spec S3). The graph `Endpoint` identity is `path`, `method`, and
    `baseurl`; the record's own `provenance` is the declared literal, so it can
    never be mistaken for an observed endpoint.
    """

    model_config = ConfigDict(frozen=True)

    endpoint_id: str
    provenance: Literal["declared"] = "declared"
    method: str
    url: str
    path: str
    baseurl: str
    status_code: None = None
    source: Literal["dom"] = "dom"
    resource_type: Literal["document"] = "document"
    http_artifact_id: None = None
    source_page_id: str
    action_id: str | None = None
    enctype: str
    field_names: tuple[str, ...] = ()


class DeclaredField(BaseModel):
    """One form field as the DOM declared it (spec 8.4), never its value.

    The field carries its contract - type, label, options, pattern, min, max -
    and no value shape at all: `value_shape` is `None` because no flow ever
    produced a value for a form that was never submitted (spec P2, P3). A form
    field always declares the body position, whatever the method.
    """

    model_config = ConfigDict(frozen=True)

    parameter_id: str
    endpoint_id: str
    provenance: Literal["declared"] = "declared"
    endpoint_path: str
    baseurl: str
    position: Literal["body"] = "body"
    name: str
    value_shape: None = None
    http_artifact_id: None = None
    content_type: str | None = None
    field_type: str = ""
    label: str = ""
    options: tuple[str, ...] = ()
    pattern: str | None = None
    min: str | None = None
    max: str | None = None

    @property
    def identity(self) -> ParameterIdentity:
        """The graph `Parameter` identity of this declared field (spec 8.4)."""
        return ParameterIdentity(
            name=self.name,
            position=self.position,
            endpoint_path=self.endpoint_path,
            baseurl=self.baseurl,
        )


def declared_endpoint(
    form: FormContract, *, source_page_id: str, action_id: str | None = None
) -> DeclaredEndpoint | None:
    """The declared endpoint one collected form contract produces (spec 8.4).

    The endpoint id is the contract's own fingerprint prefix, so two collections
    of one form are the same record and two different forms never collide.
    A form action that is not an absolute HTTP(S) URL has no graph endpoint and
    returns `None` (a `data:` or `javascript:` action never becomes a node).
    """
    split = split_url(form.action)
    if split is None:
        return None
    path, baseurl = split
    return DeclaredEndpoint(
        endpoint_id=f"ep_declared_{form.fingerprint[:16]}",
        method=form.method,
        url=form.action,
        path=path,
        baseurl=baseurl,
        source_page_id=source_page_id,
        action_id=action_id,
        enctype=form.enctype,
        field_names=_field_names(form),
    )


def declared_fields(
    form: FormContract, endpoint: DeclaredEndpoint
) -> tuple[DeclaredField, ...]:
    """One declared field per named field of the contract, in document order.

    A control with no name has no parameter name, so it stays in the contract for
    the executor and contributes no graph record.
    """
    fields: list[DeclaredField] = []
    for index, field in enumerate(form.fields):
        if not field.name:
            continue
        fields.append(
            DeclaredField(
                parameter_id=_declared_parameter_id(
                    endpoint.endpoint_id, index, field.name
                ),
                endpoint_id=endpoint.endpoint_id,
                endpoint_path=endpoint.path,
                baseurl=endpoint.baseurl,
                name=field.name,
                content_type=endpoint.enctype,
                field_type=field.type,
                label=field.label,
                options=field.options,
                pattern=field.pattern,
                min=field.min,
                max=field.max,
            )
        )
    return tuple(fields)


def _declared_parameter_id(endpoint_id: str, index: int, name: str) -> str:
    """A stable id per field: two controls of one radio group share a name."""
    return "param_declared_" + _sha(f"{endpoint_id}|body|{name}|{index}")[:16]


def _field_names(form: FormContract) -> tuple[str, ...]:
    """The form's field names in document order, without a repeated group name."""
    return tuple(
        dict.fromkeys(field.name for field in form.fields if field.name)
    )


__all__ = [
    "DEFAULT_ENCTYPE",
    "DEFAULT_METHOD",
    "DeclaredEndpoint",
    "DeclaredField",
    "FormContract",
    "FormField",
    "ParameterIdentity",
    "ParameterLocation",
    "ValueType",
    "declared_endpoint",
    "declared_fields",
    "split_url",
]
