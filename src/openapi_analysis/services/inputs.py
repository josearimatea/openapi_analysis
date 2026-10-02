"""How the services receive documents and where they save reports.

A service takes each input either already parsed (a dict — how the generator
repos hold it in memory) or as a path (CLI, batch runs). Nothing is converted:
a rules bank stays the bank's own JSON, a YAML its own mapping.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from openapi_analysis.config.paths import MANIFEST_PATH, OUTPUTS_DIR, ROOT

Source = Mapping[str, Any] | str | Path


def load(source: Source) -> tuple[dict[str, Any], str]:
    """(parsed document, label). A path is read as YAML — which also parses JSON."""
    if isinstance(source, Mapping):
        return dict(source), "<in memory>"
    path = Path(source)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected a mapping at the top level")
    try:
        label = str(path.resolve().relative_to(ROOT))
    except ValueError:
        label = str(path)
    return data, label


def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_report(report: Any, service: str, name: str, text: str) -> Path:
    """Write a report as <name>.json and <name>.txt under data/outputs/<service>/."""
    out_dir = OUTPUTS_DIR / service
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(report.model_dump_json(indent=2) + "\n",
                                          encoding="utf-8")
    (out_dir / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
    return out_dir / f"{name}.json"
