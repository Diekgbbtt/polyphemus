"""Installing an operator-provided upstream CA into the container trust store.

Measured live 2026-09-17 (C.13): mitmdump verifies the upstream certificate, so
a lab target with a self-signed cert answers the client with 502 and the artifact
records `Certificate verify failed: self-signed certificate`. The targeted fix is
to trust THAT CA - not to disable verification globally.
"""
from __future__ import annotations

from kali.http_history.trust import build_upstream_bundle, install_upstream_ca


def _ca_file(tmp_path, body: str = "-----BEGIN CERTIFICATE-----\nLAB\n-----END CERTIFICATE-----\n"):
    path = tmp_path / "lab-ca.crt"
    path.write_text(body, encoding="utf-8")
    return path


def test_installs_the_ca_and_refreshes_the_trust_store(tmp_path):
    calls: list[str] = []
    result = install_upstream_ca(
        str(_ca_file(tmp_path)),
        dest_dir=str(tmp_path / "ca-certificates"),
        update=lambda: calls.append("update") or (True, "1 added, 0 removed"),
    )
    assert result["installed"] is True
    assert result["updated"] is True
    assert calls == ["update"], "the store must be refreshed, not just copied"
    installed = tmp_path / "ca-certificates" / "polymerhus-upstream-ca.crt"
    assert installed.read_text(encoding="utf-8").startswith("-----BEGIN CERTIFICATE-----")


def test_is_a_noop_without_a_configured_ca(tmp_path):
    calls: list[str] = []
    update = lambda: calls.append("update") or (True, "")

    assert install_upstream_ca("", dest_dir=str(tmp_path), update=update)["installed"] is False
    missing = install_upstream_ca(
        str(tmp_path / "nope.crt"), dest_dir=str(tmp_path), update=update
    )
    assert missing["installed"] is False and "nope.crt" in missing["reason"]
    assert calls == [], "nothing to install must not touch the trust store"


def test_a_failing_trust_store_refresh_is_reported_not_raised(tmp_path):
    def boom():
        raise OSError("update-ca-certificates missing")

    result = install_upstream_ca(str(_ca_file(tmp_path)), dest_dir=str(tmp_path), update=boom)
    assert result["installed"] is True
    assert result["updated"] is False
    assert "update-ca-certificates missing" in result["detail"]


def _base_bundle(tmp_path):
    path = tmp_path / "certifi.pem"
    path.write_text("-----BEGIN CERTIFICATE-----\nPUBLIC-CAS\n-----END CERTIFICATE-----\n")
    return path


def test_bundle_appends_the_operator_ca_to_the_default_trust_store(tmp_path):
    """mitmproxy verifies the upstream against ITS OWN trust source (certifi),
    not the system store: installing the CA there alone left the lab target
    failing with `Certificate verify failed` (measured live). The bundle must
    keep the public CAs AND add the operator's."""
    result = build_upstream_bundle(
        str(_ca_file(tmp_path)),
        dest_dir=str(tmp_path / "mitm"),
        base=str(_base_bundle(tmp_path)),
    )
    body = (tmp_path / "mitm" / "upstream-ca-bundle.pem").read_text(encoding="utf-8")
    assert "PUBLIC-CAS" in body, "public CAs must survive, or every normal target breaks"
    assert "LAB" in body
    assert body.index("PUBLIC-CAS") < body.index("\nLAB"), "the default store comes first"
    assert result["bundle"].endswith("upstream-ca-bundle.pem")


def test_bundle_does_not_duplicate_a_ca_the_base_already_carries(tmp_path):
    source = _ca_file(tmp_path)
    base = tmp_path / "certifi.pem"
    base.write_text(
        "-----BEGIN CERTIFICATE-----\nPUBLIC-CAS\n-----END CERTIFICATE-----\n"
        + source.read_text(encoding="utf-8")
    )
    result = build_upstream_bundle(str(source), dest_dir=str(tmp_path / "mitm"), base=str(base))
    body = (tmp_path / "mitm" / "upstream-ca-bundle.pem").read_text(encoding="utf-8")
    assert body.count("LAB") == 1, "an already-trusted CA must not be appended twice"
    assert result["added"] is False


def test_bundle_is_a_noop_without_a_configured_ca(tmp_path):
    assert build_upstream_bundle("", dest_dir=str(tmp_path), base=str(_base_bundle(tmp_path)))[
        "bundle"
    ] is None
    assert not (tmp_path / "upstream-ca-bundle.pem").exists()
