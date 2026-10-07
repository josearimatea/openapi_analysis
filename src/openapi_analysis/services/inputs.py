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

from openapi_analysis.config.paths import MANIFEST_PATH, ROOT

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


def save_report(report: Any, service: str, evaluation: str, name: str, text: str) -> Path:
    """Write ONE report of one run under data/outputs/reports/<service>/<evaluation>/,
    named by when it was made — YYYY-MM-DD_HH-MM-SS.txt (to read) and .json (its data);
    a second report in the same second gets _2, _3 ... A run never overwrites an earlier
    one. Which input it evaluates (`name`) is stated inside the report."""
    from datetime import datetime

    from openapi_analysis.config.paths import report_dir

    out_dir = report_dir(service, evaluation)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.fromisoformat(report.evaluated_at):%Y-%m-%d_%H-%M-%S}"
    stem, n = base, 1
    while (out_dir / f"{stem}.txt").exists() or (out_dir / f"{stem}.json").exists():
        n += 1
        stem = f"{base}_{n}"
    (out_dir / f"{stem}.json").write_text(report.model_dump_json(indent=2) + "\n",
                                          encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return out_dir / f"{stem}.txt"
