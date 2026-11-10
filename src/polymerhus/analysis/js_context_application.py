"""Run-scoped proof that both Analysis proposers integrated one JS input."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from langchain_core.messages import ToolMessage

from polymerhus.analysis.messages import StepReceipt
from polymerhus.app.js_context.selection import JsContextInput

_ROLES = ("assigner", "mechanism_typist")
_BLOCKING_CONTEXT_GAPS = frozenset(
    {
        "contradiction_unresolved",
        "semantic_contradiction",
        "source_conflict",
        "unsupported_behavior_claim",
    }
)
_READ_GAP = {
    "missing": "js_context_read_missing",
    "corrupt": "js_context_read_corrupt",
    "run_mismatch": "js_context_read_foreign",
}


def _tool_payload(message: ToolMessage) -> dict | None:
    content = message.content
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


@dataclass
class _RoleApplication:
    delivered_reads: int = 0
    metadata_reads: int = 0
    failed_reads: int = 0
    receipts: int = 0
    failed: bool = False
    seen_tool_calls: set[str] = field(default_factory=set)


@dataclass
class JsContextApplicationTracker:
    """Observe actual proposer outcomes and delivered `js_context` ToolMessages."""

    selection: JsContextInput
    roles: dict[str, _RoleApplication] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.roles = {role: _RoleApplication() for role in _ROLES}

    def observe_turn(self, role_id: str, messages: Iterable[object]) -> None:
        if role_id not in self.roles:
            return
        state = self.roles[role_id]
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            if tool_call_id and tool_call_id in state.seen_tool_calls:
                continue
            payload = _tool_payload(message)
            if payload is None:
                continue
            binding = payload.get("js_context_binding")
            if (
                not isinstance(binding, dict)
                or binding.get("input_id") != self.selection.input_id
            ):
                continue
            if tool_call_id:
                state.seen_tool_calls.add(tool_call_id)
            if payload.get("ok") is True:
                if (
                    payload.get("command") == "read"
                    and payload.get("section") in {"behaviors", "evidence"}
                    and isinstance(payload.get("items"), list)
                    and bool(payload["items"])
                ):
                    state.delivered_reads += 1
                else:
                    state.metadata_reads += 1
            else:
                state.failed_reads += 1

    def observe_receipts(self, receipts: Iterable[StepReceipt]) -> None:
        for receipt in receipts:
            if receipt.role not in self.roles:
                continue
            state = self.roles[receipt.role]
            state.receipts += 1
            if receipt.status == "degraded":
                state.failed = True

    def _binding(self, status: str, gaps: list[str]) -> dict:
        return {
            "schema_version": 1,
            "input_id": self.selection.input_id,
            "project_id": self.selection.project_id,
            "producing_run_id": self.selection.producing_run_id,
            "context_id": self.selection.context_id,
            "document_id": self.selection.document_id,
            "document_sha256": self.selection.document_sha256,
            "selection": self.selection.as_dict(),
            "status": status,
            "gaps": sorted(set(gaps)),
            "roles": {
                role: {
                    "delivered_reads": state.delivered_reads,
                    "metadata_reads": state.metadata_reads,
                    "failed_reads": state.failed_reads,
                    "receipts": state.receipts,
                }
                for role, state in self.roles.items()
            },
        }

    def pending(self) -> dict:
        return self._binding("pending", [])

    def settle(self) -> dict:
        if self.selection.status == "not_applicable":
            return self._binding("not_applicable", list(self.selection.gaps))
        gaps = list(self.selection.gaps)
        if self.selection.status != "published":
            gaps.append("js_context_not_published")
            return self._binding("settled_gap", gaps)

        integration_gaps = [
            gap for gap in gaps if gap in _BLOCKING_CONTEXT_GAPS
        ]
        for role in _ROLES:
            state = self.roles[role]
            if state.receipts == 0:
                integration_gaps.append("js_context_role_not_concluded")
                continue
            if state.failed:
                integration_gaps.append("js_context_role_failed")
            if state.failed_reads:
                integration_gaps.append("js_context_read_failed")
            elif state.delivered_reads == 0:
                integration_gaps.append(
                    "js_context_read_content_missing"
                    if state.metadata_reads
                    else "js_context_read_missing"
                )
        status = (
            "settled_success" if not integration_gaps else "settled_gap"
        )
        return self._binding(status, [*gaps, *integration_gaps])


__all__ = ["JsContextApplicationTracker"]
