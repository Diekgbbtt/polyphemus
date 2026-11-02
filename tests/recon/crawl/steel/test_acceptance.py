"""The P1 to P5 acceptance matrix for the steel crawl implementation.

Spec: `docs/design/steel-crawl-spec.md` sections 14.3 and 14.4.

The deterministic contract suite is the real gate; this test pins the module
tree and the public seam each phase depends on, so a missing module or a renamed
entry point fails as an acceptance failure rather than as a late live-run error.
P1: session, auth, state, command. P2: element map and frontier. P3: capture,
normalization, history client and edge, manifest. P4: Jev policy, removal,
value selection. P5: job lifecycle and the bounded session boundary.
"""
from __future__ import annotations


def test_the_p1_to_p5_module_tree_and_public_seams_are_present():
    from polymerhus.recon.crawl.steel.auth import AuthOracle
    from polymerhus.recon.crawl.steel.capture.history import (
        HistoryClient,
        normalize_cdp_flow,
    )
    from polymerhus.recon.crawl.steel.capture.sidecar import CaptureSidecar
    from polymerhus.recon.crawl.steel.command import CommandMapper
    from polymerhus.recon.crawl.steel.enumerate import ElementMap
    from polymerhus.recon.crawl.steel.forms import DeclaredCollector, FormLedger
    from polymerhus.recon.crawl.steel.frontier import Frontier
    from polymerhus.recon.crawl.steel.job import CrawlJob, run_with_session_boundary
    from polymerhus.recon.crawl.steel.ledger import RunLedger, finalize
    from polymerhus.recon.crawl.steel.manifest import Manifest, write_manifest
    from polymerhus.recon.crawl.steel.parameters import (
        ObservedParameter,
        extract_parameters,
    )
    from polymerhus.recon.crawl.steel.policy.jev import JevPolicy
    from polymerhus.recon.crawl.steel.policy.select import choose_field_value
    from polymerhus.recon.crawl.steel.run import CrawlRun
    from polymerhus.recon.crawl.steel.safety import remove_forbidden
    from polymerhus.recon.crawl.steel.session import SteelSessionClient
    from polymerhus.recon.crawl.steel.state import BrowserState

    p1 = (SteelSessionClient, AuthOracle, BrowserState, CommandMapper)
    p2 = (ElementMap, Frontier)
    p3 = (
        CaptureSidecar,
        normalize_cdp_flow,
        HistoryClient,
        Manifest,
        write_manifest,
        RunLedger,
        finalize,
        ObservedParameter,
        extract_parameters,
    )
    p4 = (JevPolicy, remove_forbidden, choose_field_value, FormLedger)
    p5 = (CrawlJob, CrawlRun, run_with_session_boundary, DeclaredCollector)

    for seam in (*p1, *p2, *p3, *p4, *p5):
        assert seam is not None


def test_the_kali_http_history_edge_is_a_separate_service_seam():
    from kali.http_history.edge import create_edge_server

    assert callable(create_edge_server)
