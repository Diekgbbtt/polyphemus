"""Per-dataset helpers (spec #301).

`helper_for` returns the dataset's own helper module when one exists
(`orchestrator/datasets/<id>.py` exposing `helper(dataset)`), else the generic
compose-derived helper.
"""
from __future__ import annotations

from orchestrator.datasets.base import (
    BuiltImage,
    DatasetHelper,
    canonical_tag,
    helper_for,
    parse_built_images,
)

__all__ = [
    "BuiltImage",
    "DatasetHelper",
    "canonical_tag",
    "helper_for",
    "parse_built_images",
]
