"""Pure final projection of scanner and structural JS evidence into L0 deltas.

Source contexts are trusted store metadata, never model URL overrides. Outcomes
refer to scanner-output lines or verified structure items. Scanner lines are not
original-code byte offsets; structural outcomes retain their original spans.
This module performs no I/O and makes no execution/reachability or semantic
truth claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.domain.parsers._urls import base_and_path, url_to_deltas
from polymerhus.recon.domain.types import AssetDelta, Edge
from polymerhus.recon.js_intake.redaction import redact_url

PROPOSAL_SCHEMA_VERSION = 1
CANDIDATE_SCHEMA_VERSION = 2
_HTTP_METHODS = {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'CONNECT', 'TRACE'}


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def content_id(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class SourceContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_id: str
    run_id: str
    context_ref: str
    lead_id: str
    source_sha256: str
    scan_key: str
    producer: str = 'jsluice'
    discovery_producer: str = 'unknown'
    source_url: str = ''
    execution_base_url: str | None = None
    execution_base_ref: str | None = None
    module_base_url: str | None = None
    module_base_ref: str | None = None


class StructuralImportEvidence(BaseModel):
    """Trusted ESM import fact read from a verified structure index."""
    model_config = ConfigDict(extra='forbid')
    project_id: str
    run_id: str
    context_ref: str
    lead_id: str
    source_sha256: str
    source_size: int = Field(ge=0)
    index_id: str
    index_integrity: str
    item_id: str
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    specifier: str
    subtype: str
    import_kind: str
    module_base_url: str | None = None
    module_base_ref: str | None = None


class CandidateOutcome(BaseModel):
    candidate_ref: str
    candidate_id: str
    source_context_id: str
    record_locator: str
    status: str
    reason: str | None = None
    asset_refs: list[str] = Field(default_factory=list)
    facts: dict = Field(default_factory=dict)
    decision_refs: list[str] = Field(default_factory=list)
    fact_id: str | None = None


class JsAssetProposal(BaseModel):
    assets: list[AssetDelta] = Field(default_factory=list)
    outcomes: list[CandidateOutcome] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def asset_ref(asset: AssetDelta) -> str:
    return 'asset_' + content_id({'type': asset.type, 'identity': asset.identity})


def candidate_ref(candidate: dict, context: SourceContext) -> str:
    return 'occ_' + content_id({
        'candidate_id': candidate.get('candidate_id'),
        **{k: getattr(context, k) for k in (
            'project_id', 'run_id', 'context_ref', 'lead_id', 'source_sha256', 'scan_key')},
    })


def safe_network_url(value: str) -> str | None:
    """Concrete identity only: discard query values/userinfo, refuse hidden paths."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {'http', 'https'} or not parts.hostname:
            return None
        _ = parts.port
        if re.search(r'[\s\\<>"\x00-\x1f]', value):
            return None
        decoded_path = unquote(unquote(parts.path))
        if re.search(r'\[|\]|TRUNCATED|REDACTED|\$\{|\.\.\.', decoded_path, re.I):
            return None
        safe = urlsplit(redact_url(urlunsplit(parts._replace(path=decoded_path))))
        if safe.path != decoded_path:
            return None
        return urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], parts.path or '/', '', ''))
    except ValueError:
        return None


def _names(values) -> tuple[list[str], bool]:
    if not isinstance(values, list):
        return [], True
    safe = [v for v in values[:100] if isinstance(v, str) and 0 < len(v) <= 120
            and not re.search(r'[\s\[\]<>]|[A-Za-z0-9_-]{24,}', v)]
    return safe, len(safe) != len(values)


def _url_assets(candidate: dict, ctx: SourceContext) -> tuple[list[AssetDelta], dict, str | None, list[str]]:
    if candidate.get('candidate_schema_version') != CANDIDATE_SCHEMA_VERSION:
        return [], {}, 'incompatible_candidate_projection', []
    url = candidate.get('redacted_url')
    meta = candidate.get('safe_metadata') or {}
    if candidate.get('url_truncated'):
        return [], {}, 'url_identity_truncated', []
    if not isinstance(url, str):
        return [], {}, 'url_identity_redacted', []
    decoded = unquote(unquote(urlsplit(url).path))
    if re.search(r'REDACTED|TRUNCATED|\[|\]|\$\{|\.\.\.', decoded, re.I):
        return [], {}, 'url_identity_redacted', []
    method = meta.get('method')
    if meta.get('method_truncated') or method not in _HTTP_METHODS:
        return [], {}, 'method_unresolved', []
    base_ref = None
    if not urlsplit(url).scheme:
        kind = str(meta.get('kind') or '').lower()
        if kind in {'import', 'dynamic-import', 'static-import'}:
            base = safe_network_url(ctx.module_base_url or '')
            base_ref = ctx.module_base_ref
            reason = 'module_base_unproven'
        elif kind in {'fetch', 'xhr', 'xmlhttprequest', 'axios', 'request', 'websocket'}:
            base = safe_network_url(ctx.execution_base_url or '')
            base_ref = ctx.execution_base_ref
            reason = 'execution_base_unproven'
        else:
            return [], {}, 'relative_operation_unknown', []
        if not base or not base_ref:
            return [], {}, reason, []
        url = urljoin(base, url)
    clean_url = safe_network_url(url)
    if not clean_url:
        return [], {}, 'url_identity_invalid', []
    query, q_limited = _names(meta.get('query_param_names') or [])
    body, b_limited = _names(meta.get('body_param_names') or [])
    query_in_url, url_limited = _names([k for k, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)])
    query = list(dict.fromkeys(query_in_url + query))
    # The existing curator uses props.url query *names* for its noise gate.
    # Blank values preserve that evidence without carrying target values.
    projected_url = clean_url
    if query_in_url:
        projected_url += '?' + urlencode([(name, '') for name in query_in_url])
    assets = url_to_deltas(projected_url, method=method, source=ctx.producer,
                           query_params=query, body_params=body)
    gaps = ['parameter_names_limited'] if (q_limited or b_limited or url_limited or meta.get('parameter_names_limited')) else []
    facts = {'url': clean_url, 'method': method, 'context_ref': ctx.context_ref}
    if base_ref:
        facts['resolution_base_ref'] = base_ref
    return assets, facts, None if assets else 'url_helper_excluded', gaps


def _structural_import_assets(
    evidence: StructuralImportEvidence,
    ctx: SourceContext,
) -> tuple[list[AssetDelta], dict, str | None, list[str]]:
    if (
        evidence.project_id != ctx.project_id
        or evidence.run_id != ctx.run_id
        or evidence.context_ref != ctx.context_ref
        or evidence.lead_id != ctx.lead_id
    ):
        return [], {}, 'structure_import_context_mismatch', []
    if evidence.source_sha256 != ctx.source_sha256:
        return [], {}, 'structure_import_source_mismatch', []
    if evidence.end_byte < evidence.start_byte:
        return [], {}, 'invalid_structure_import', []
    raw_specifier = evidence.specifier
    if (
        not raw_specifier
        or len(raw_specifier) > 4096
        or re.search(r'[\s\\<>"\x00-\x1f]', raw_specifier)
        or re.search(r'\[|\]|TRUNCATED|REDACTED|\$\{|\.\.\.', raw_specifier, re.I)
    ):
        return [], {}, 'structure_import_specifier_unresolved', []
    parsed_specifier = urlsplit(raw_specifier)
    if parsed_specifier.scheme:
        resolved = safe_network_url(raw_specifier)
        base_ref = None
    elif raw_specifier.startswith(('/','./','../')):
        base = safe_network_url(evidence.module_base_url or '')
        context_base = safe_network_url(ctx.module_base_url or '')
        if not base or not evidence.module_base_ref:
            return [], {}, 'structure_import_base_unproven', []
        if not context_base or base != context_base:
            return [], {}, 'structure_import_base_mismatch', []
        resolved = safe_network_url(urljoin(base, raw_specifier))
        base_ref = evidence.module_base_ref
    else:
        return [], {}, 'structure_import_specifier_unresolved', []
    if not resolved:
        return [], {}, 'structure_import_url_invalid', []
    assets = url_to_deltas(
        resolved,
        method='GET',
        source='js_structure',
    )
    facts = {
        'url': resolved,
        'method': 'GET',
        'context_ref': ctx.context_ref,
        'module_base_url': safe_network_url(evidence.module_base_url or ''),
        'structure_index_id': evidence.index_id,
        'structure_index_integrity': evidence.index_integrity,
        'structure_item_id': evidence.item_id,
        'source_sha256': evidence.source_sha256,
        'source_span': {
            'start_byte': evidence.start_byte,
            'end_byte': evidence.end_byte,
        },
        'import_subtype': evidence.subtype,
        'import_kind': evidence.import_kind,
    }
    if base_ref:
        facts['resolution_base_ref'] = base_ref
    return assets, facts, None if assets else 'structure_import_url_excluded', []


def _decision_outcome(selected):
    if selected and all(
        item.get('action') == 'exclude'
        and item.get('reason')
        and item.get('evidence_refs')
        and item.get('record_id')
        for item in selected
    ):
        return 'excluded', 'supported_exclusion', sorted(
            item['record_id'] for item in selected
        )
    if selected and all(
        item.get('action') == 'include'
        and item.get('reason')
        and item.get('evidence_refs')
        and item.get('record_id')
        for item in selected
    ):
        return None, None, sorted(item['record_id'] for item in selected)
    return None, None, []


def _secret_assets(candidate: dict, ctx: SourceContext):
    fingerprint = candidate.get('secret_fingerprint') or ''
    if candidate.get('secret_hash_algorithm') != 'sha1' or not re.fullmatch('[0-9a-f]{40}', fingerprint):
        return [], {}, 'incompatible_secret_projection', []
    edges = []
    assets = []
    try:
        parts = urlsplit(ctx.source_url)
        source = safe_network_url(urlunsplit((parts.scheme, parts.netloc, '/', '', '')))
    except ValueError:
        source = None
    if source:
        base, _ = base_and_path(source)
        assets.append(AssetDelta(type='BaseURL', identity={'url': base}))
        edges.append(Edge(rel='HAS_SECRET', dir='in', node_type='BaseURL', node_identity={'url': base}))
    assets.append(AssetDelta(type='Secret', identity={'value_hash': fingerprint},
                             props={'kind': candidate.get('secret_kind'), 'source': ctx.producer, 'redacted': True}, edges=edges))
    return assets, {'context_ref': ctx.context_ref}, None, [] if source else ['secret_anchor_unproven']


def build_js_asset_deltas(
    candidates,
    *,
    source_contexts,
    structural_imports=(),
    decisions=(),
) -> JsAssetProposal:
    """Convert scoped occurrences; unsupported decisions never become facts.

    Only prevalidated structured exclusions are accepted. Corrections to bases
    must already live in trusted source_contexts with an evidence reference.
    """
    result = JsAssetProposal()
    by_asset: dict[str, AssetDelta] = {}
    def add_assets(outcome, assets):
        for asset in assets:
            key = asset_ref(asset)
            previous = by_asset.get(key)
            if previous is None:
                by_asset[key] = asset
            else:
                if asset.type == 'Endpoint':
                    previous_url = previous.props.get('url') or ''
                    names = {
                        name
                        for url in (previous_url, asset.props.get('url') or '')
                        for name, _ in parse_qsl(
                            urlsplit(url).query,
                            keep_blank_values=True,
                        )
                    }
                    parts = urlsplit(previous_url)
                    previous.props['url'] = urlunsplit(parts._replace(
                        query=urlencode([(name, '') for name in sorted(names)])
                    ))
                existing_edges = {
                    canonical_bytes(edge.model_dump())
                    for edge in previous.edges
                }
                for edge in asset.edges:
                    if canonical_bytes(edge.model_dump()) not in existing_edges:
                        previous.edges.append(edge)
                        existing_edges.add(canonical_bytes(edge.model_dump()))
            outcome.asset_refs.append(key)

    decisions_by_ref: dict[str, list[dict]] = {}
    for decision in decisions:
        decisions_by_ref.setdefault(decision.get('candidate_ref', ''), []).append(decision)
    seen_refs = set()
    for occurrence in candidates:
        candidate = occurrence['candidate']
        context_id = occurrence['source_context_id']
        raw_context = source_contexts.get(context_id)
        if raw_context is None:
            result.gaps.append('source_context_missing')
            continue
        ctx = SourceContext.model_validate(raw_context)
        ref = candidate_ref(candidate, ctx)
        seen_refs.add(ref)
        outcome = CandidateOutcome(candidate_ref=ref, candidate_id=candidate['candidate_id'],
                                   source_context_id=context_id, record_locator=candidate['record_locator'], status='unresolved')
        if candidate.get('source_sha256') != ctx.source_sha256:
            outcome.reason = 'candidate_source_mismatch'
        else:
            selected = decisions_by_ref.get(ref, [])
            decision_status, decision_reason, decision_refs = _decision_outcome(selected)
            if decision_status == 'excluded':
                outcome.status, outcome.reason = decision_status, decision_reason
                outcome.decision_refs = decision_refs
                result.outcomes.append(outcome)
                continue
            if decision_refs:
                outcome.decision_refs = decision_refs
            elif selected:
                result.gaps.append('unsupported_decision')
            try:
                if candidate.get('mode') == 'urls':
                    assets, facts, reason, gaps = _url_assets(candidate, ctx)
                elif candidate.get('mode') == 'secrets':
                    assets, facts, reason, gaps = _secret_assets(candidate, ctx)
                else:
                    assets, facts, reason, gaps = [], {}, 'unsupported_candidate_mode', []
            except (ValueError, TypeError):
                assets, facts, reason, gaps = [], {}, 'invalid_candidate_identity', []
            outcome.reason = reason
            outcome.facts = facts
            if facts:
                outcome.fact_id = content_id({"candidate_ref": ref, "facts": facts})
            outcome.status = 'proposed' if assets else 'unresolved'
            result.gaps.extend(gaps)
            add_assets(outcome, assets)
        result.outcomes.append(outcome)
    seen_structural = set()
    for occurrence in sorted(
        structural_imports,
        key=lambda item: (
            item.get('source_context_id') or '',
            item.get('evidence', {}).get('item_id') or '',
        ),
    ):
        context_id = occurrence.get('source_context_id')
        raw_context = source_contexts.get(context_id)
        if raw_context is None:
            result.gaps.append('source_context_missing')
            continue
        try:
            evidence = StructuralImportEvidence.model_validate(
                occurrence.get('evidence') or {}
            )
        except (ValueError, TypeError):
            result.gaps.append('invalid_structure_import')
            continue
        identity = (
            context_id,
            evidence.index_id,
            evidence.item_id,
        )
        if identity in seen_structural:
            continue
        seen_structural.add(identity)
        ctx = SourceContext.model_validate(raw_context)
        ref = 'occ_' + content_id({
            'evidence_kind': 'structure_import',
            'source_context_id': context_id,
            'project_id': evidence.project_id,
            'run_id': evidence.run_id,
            'context_ref': evidence.context_ref,
            'lead_id': evidence.lead_id,
            'source_sha256': evidence.source_sha256,
            'index_id': evidence.index_id,
            'item_id': evidence.item_id,
        })
        seen_refs.add(ref)
        outcome = CandidateOutcome(
            candidate_ref=ref,
            candidate_id=evidence.item_id,
            source_context_id=context_id,
            record_locator=(
                f'structure:{evidence.index_id}:{evidence.item_id}:'
                f'bytes:{evidence.start_byte}-{evidence.end_byte}'
            ),
            status='unresolved',
        )
        selected = decisions_by_ref.get(ref, [])
        decision_status, decision_reason, decision_refs = _decision_outcome(
            selected
        )
        if decision_status == 'excluded':
            outcome.status, outcome.reason = decision_status, decision_reason
            outcome.decision_refs = decision_refs
            result.outcomes.append(outcome)
            continue
        if decision_refs:
            outcome.decision_refs = decision_refs
        elif selected:
            result.gaps.append('unsupported_decision')
        assets, facts, reason, gaps = _structural_import_assets(evidence, ctx)
        outcome.reason = reason
        outcome.facts = facts
        if reason:
            result.gaps.append(reason)
        if facts:
            outcome.fact_id = content_id({
                'candidate_ref': ref,
                'facts': facts,
            })
        outcome.status = 'proposed' if assets else 'unresolved'
        result.gaps.extend(gaps)
        add_assets(outcome, assets)
        result.outcomes.append(outcome)
    if set(decisions_by_ref) - seen_refs:
        result.gaps.append('decision_candidate_missing')
    result.assets = list(by_asset.values())
    result.gaps = sorted(set(result.gaps))
    return result
