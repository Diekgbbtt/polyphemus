"""The TargetConfiguration loader and per-runner validation (spec #301)."""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.target_config import (
    TargetConfigError,
    load_target_configuration,
    parse_target_configuration,
)


def test_parse_targetctl_config():
    config = parse_target_configuration(
        {"target": "comfyui", "runner": "targetctl", "compose": "docker-compose.cage.yml"}
    )
    assert config.target == "comfyui"
    assert config.runner == "targetctl"
    assert config.compose == "docker-compose.cage.yml"
    assert config.images == ()
    assert config.reclaimable is False


def test_parse_compose_config_requires_port():
    with pytest.raises(TargetConfigError, match="port"):
        parse_target_configuration(
            {"target": "x", "runner": "compose", "compose": "c.yml"}
        )


def test_parse_image_config_requires_image_and_port():
    with pytest.raises(TargetConfigError, match="image"):
        parse_target_configuration({"target": "x", "runner": "image", "port": 80})
    config = parse_target_configuration(
        {"target": "x", "runner": "image", "image": "nginx:alpine", "port": 18080}
    )
    assert config.image == "nginx:alpine"
    assert config.port == 18080


def test_runner_defaults_to_compose_and_needs_compose_and_port():
    with pytest.raises(TargetConfigError):
        parse_target_configuration({"target": "x"})


def test_unknown_runner_fails_loud():
    with pytest.raises(TargetConfigError, match="runner"):
        parse_target_configuration({"target": "x", "runner": "ssh"})


def test_unknown_field_fails_loud():
    with pytest.raises(TargetConfigError, match="unknown field"):
        parse_target_configuration(
            {"target": "x", "runner": "targetctl", "compose": "c.yml", "nope": 1}
        )


def test_missing_target_fails_loud():
    with pytest.raises(TargetConfigError, match="target"):
        parse_target_configuration({"runner": "targetctl", "compose": "c.yml"})


def test_images_and_pull_and_checker_and_reclaimable():
    config = parse_target_configuration(
        {
            "target": "wordpress",
            "runner": "targetctl",
            "compose": "docker-compose.cage.yml",
            "images": ["ph/webench/wordpress", "ph/webench/wordpress/wpcli"],
            "pull": {"ph/webench/wordpress": "ghcr.io/x/wordpress:1"},
            "checker": "wordpress",
            "reclaimable": True,
        }
    )
    assert config.images == ("ph/webench/wordpress", "ph/webench/wordpress/wpcli")
    assert config.pull == {"ph/webench/wordpress": "ghcr.io/x/wordpress:1"}
    assert config.checker == "wordpress"
    assert config.reclaimable is True


def test_readiness_window_overrides_parse():
    config = parse_target_configuration(
        {
            "target": "openmetadata",
            "runner": "targetctl",
            "compose": "docker-compose.cage.yml",
            "ready_retries": 180,
            "ready_interval_s": 10,
        }
    )
    assert config.ready_retries == 180
    assert config.ready_interval_s == 10.0


def test_readiness_window_defaults_to_none():
    config = parse_target_configuration(
        {"target": "x", "runner": "targetctl", "compose": "c.yml"}
    )
    assert config.ready_retries is None
    assert config.ready_interval_s is None


def test_readiness_window_rejects_a_bad_type():
    with pytest.raises(TargetConfigError, match="ready_retries"):
        parse_target_configuration(
            {
                "target": "x",
                "runner": "targetctl",
                "compose": "c.yml",
                "ready_retries": "many",
            }
        )


def test_pull_map_rejects_bad_entries():
    with pytest.raises(TargetConfigError, match="pull"):
        parse_target_configuration(
            {
                "target": "x",
                "runner": "targetctl",
                "compose": "c.yml",
                "pull": {"tag": ""},
            }
        )


def test_load_reports_invalid_yaml(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text("target: [unclosed\n", encoding="utf-8")
    with pytest.raises(TargetConfigError, match="invalid YAML"):
        load_target_configuration(path)
