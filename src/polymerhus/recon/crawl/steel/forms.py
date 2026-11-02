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

from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.parameters import (
    DeclaredEndpoint,
    DeclaredField,
    FormContract,
    declared_endpoint,
    declared_fields,
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
        if any(known.endpoint_id == endpoint.endpoint_id for known in self.endpoints):
            return
        fields = declared_fields(form, endpoint)
        self.endpoints.append(endpoint)
        self.fields.extend(fields)
        if self._sink is not None:
            self._sink(endpoint, fields)


__all__ = [
    "DeclaredCollector",
    "DeclaredSink",
    "FormLedger",
]
