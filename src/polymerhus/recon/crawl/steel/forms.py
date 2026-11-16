"""The form ledger and the declared collector: the DOM side of the parameter model.

Spec: `docs/design/steel-crawl-spec.md` sections 2.4, 2.6 (P3, P4), 6.3, 7, and 8.3.

`FormLedger` is spec P4's rule: a form is submitted once per state. The
prototype keyed its submitted set on the form fingerprint alone, so a search form
that reappeared on a freshly loaded page was never submitted again; the ledger
keys the record on `(state key, fingerprint)`, so one form submits once on each
state it appears in, and a form that was removed never submits at all.

`DeclaredCollector` implements `safety.Collector`. The removal stage hands it the
candidate it just removed, and the collector writes the declared contract -
endpoint and fields - in place, so a removed login form reaches the graph while
it is never submitted (spec 6.3, S3, P3). It never submits, fetches, or executes,
and it never records a value: a declared field carries the field contract only.

Both are plain in-memory bookkeeping. The sink and the page are injected, so
importing this module performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from polymerhus.recon.crawl.steel.command import Action, CommandMapper
from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.parameters import (
    DeclaredEndpoint,
    DeclaredField,
    FormContract,
    FormField,
    declared_endpoint,
    declared_fields,
)
from polymerhus.recon.crawl.steel.policy.port import Policy
from polymerhus.recon.crawl.steel.policy.select import (
    ValueCatalogue,
    choose_field_value,
    validate_value,
)
from polymerhus.recon.crawl.steel.state import PageInstance

# The record sink a run hands the collector: one collected form's endpoint and
# its fields, ready to append to the manifest.
DeclaredSink = Callable[[DeclaredEndpoint, tuple[DeclaredField, ...]], None]


class FormLedger:
    """The submission ledger of spec P4: one submit per form per state.

    A successful submission closes the `(state, fingerprint)` pair; a failed one
    records nothing, so the next visit to the state offers the form again. The
    actual submission is the executor's (SC-19): the ledger only answers whether
    it may happen.
    """

    def __init__(self) -> None:
        self._submitted: set[tuple[str, str]] = set()

    def should_submit(self, form: FormContract, state_key: str) -> bool:
        """Whether this form may still be submitted in this state (spec P4)."""
        return (state_key, form.fingerprint) not in self._submitted

    def mark_submitted(self, form: FormContract, state_key: str) -> None:
        """Record a successful submission of this form in this state.

        The removal set is not consulted here: a removed form is collected in
        place and never reaches the executor, so it never marks anything.
        """
        self.record(form, state_key, succeeded=True)

    def record(
        self, form: FormContract, state_key: str, *, succeeded: bool
    ) -> None:
        """Record one submission attempt; only a success closes the form (P4).

        A failed submission is not evidence that the form's surface was seen, so
        it leaves the form open in the state and the executor may try again.
        """
        if succeeded:
            self._submitted.add((state_key, form.fingerprint))

    @property
    def submitted(self) -> frozenset[tuple[str, str]]:
        """The `(state key, fingerprint)` pairs a successful submission closed."""
        return frozenset(self._submitted)


class DeclaredCollector:
    """The in-place DOM collector: declared endpoints and fields, never a value.

    Implements `safety.Collector`. Construct it with the page the candidate came
    from (or just its page visit id) and an optional sink; the records accumulate
    on `endpoints` and `fields` either way. `collect` is the only entry point: it
    writes one endpoint and one field per field of the candidate's form contract,
    and nothing at all for a candidate that carries no contract, such as a
    removed button or a download.

    Collecting the same form twice - the form element and its submit control are
    both candidates - writes it once: the endpoint id is the contract's own
    fingerprint, so the second collection is the same record (idempotent, spec 9).
    """

    def __init__(
        self,
        page: PageInstance | str,
        sink: DeclaredSink | None = None,
    ) -> None:
        self._page_id = (
            page.page_visit_id if isinstance(page, PageInstance) else str(page)
        )
        self._sink = sink
        self.endpoints: list[DeclaredEndpoint] = []
        self.fields: list[DeclaredField] = []

    def collect(self, element: Element) -> None:
        """Record the declared contract of one removed candidate, if it has one."""
        form = element.form
        if form is None:
            return
        endpoint = declared_endpoint(form, source_page_id=self._page_id)
        if endpoint is None:
            return
        if any(known.endpoint_id == endpoint.endpoint_id for known in self.endpoints):
            return
        fields = declared_fields(form, endpoint)
        self.endpoints.append(endpoint)
        self.fields.extend(fields)
        if self._sink is not None:
            self._sink(endpoint, fields)


@dataclass(frozen=True)
class FormSubmission:
    """One form attempt: submitted once, skipped, or refused before any field."""

    form: FormContract | None
    submitted: bool
    skipped: str | None = None
    value_keys: tuple[str, ...] = ()
    result: Any = None


class FormExecutor:
    """Fill and submit one live form through the real command mapper.

    The field choice comes from `choose_field_value` (the single-match shortcut
    or Jev), the value is validated against the field contract, and the command
    mapper types it locally. A successful submit marks the form in the ledger;
    a duplicate is skipped before any command. The executor never records a
    value in the manifest: only the chosen keys ride the submission.
    """

    def __init__(
        self,
        *,
        mapper: CommandMapper,
        policy: Policy,
        catalogue: ValueCatalogue,
        ledger: FormLedger | None = None,
        submit_check: Callable[[FormContract], bool] | None = None,
    ) -> None:
        self._mapper = mapper
        self._policy = policy
        self._catalogue = catalogue
        self.ledger = ledger or FormLedger()
        self._submit_check = submit_check

    def submit(
        self, page: PageInstance, element: Element, generation: int
    ) -> FormSubmission:
        """Fill the fields and submit the form once in the page's state."""
        form = element.form
        if form is None:
            return FormSubmission(form=None, submitted=False, skipped="no_contract")
        if not self.ledger.should_submit(form, page.state_key):
            return FormSubmission(form=form, submitted=False, skipped="duplicate")
        keys: list[str] = []
        for field in form.fields:
            contract = field.to_policy_field()
            choice = choose_field_value(contract, self._catalogue, self._policy)
            if choice.skip_form:
                return FormSubmission(
                    form=form, submitted=False, skipped="required"
                )
            if choice.skip_field:
                continue
            validation = validate_value(choice.value or "", contract)
            if not validation.ok:
                continue
            self._fill(page, field, choice.value or "", generation)
            if choice.key:
                keys.append(choice.key)
        result = self._mapper.execute(
            Action(
                verb="submit",
                impact="write",
                capture="network",
                document_generation=generation,
                selector=form.root_selector,
            ),
            page,
        )
        failed = result is not None and getattr(result, "error", None) is not None
        checked = True if self._submit_check is None else self._submit_check(form)
        if failed or not checked:
            return FormSubmission(
                form=form,
                submitted=False,
                skipped="submit_failed",
                value_keys=tuple(keys),
                result=result,
            )
        self.ledger.mark_submitted(form, page.state_key)
        return FormSubmission(
            form=form, submitted=True, value_keys=tuple(keys), result=result
        )

    def _fill(
        self,
        page: PageInstance,
        field: FormField,
        value: str,
        generation: int,
    ) -> None:
        """Type one resolved value with the verb its field type needs."""
        if field.type in {"select-one", "select-multiple"}:
            self._mapper.execute(
                Action(
                    verb="select",
                    impact="local_state",
                    capture="dom",
                    document_generation=generation,
                    selector=field.selector,
                    value=value,
                ),
                page,
            )
        elif field.type in {"checkbox", "radio"}:
            if value:
                self._mapper.execute(
                    Action(
                        verb="check",
                        impact="local_state",
                        capture="dom",
                        document_generation=generation,
                        selector=field.selector,
                    ),
                    page,
                )
        elif field.type == "file":
            self._mapper.execute(
                Action(
                    verb="upload",
                    impact="local_state",
                    capture="dom",
                    document_generation=generation,
                    selector=field.selector,
                    value=value,
                ),
                page,
            )
        else:
            self._mapper.execute(
                Action(
                    verb="fill",
                    impact="local_state",
                    capture="dom",
                    document_generation=generation,
                    selector=field.selector,
                    value=value,
                ),
                page,
            )


__all__ = [
    "DeclaredCollector",
    "DeclaredSink",
    "FormExecutor",
    "FormLedger",
    "FormSubmission",
]
