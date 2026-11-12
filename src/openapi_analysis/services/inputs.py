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

from openapi_analysis.config.paths import MANIFEST_PATH, ROOT, SPECS_DIR, reference_yaml
from openapi_analysis.config.settings import OFFICIAL_BY_SPEC

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


def spec_code_of(entry: dict[str, Any]) -> str:
    """The spec version ("i00") a manifest entry comes from: a bank's own, or that of the
    bank a generated document was built from."""
    if "spec" in entry:
        return entry["spec"]
    return next(b["spec"] for b in manifest()["rulesbank"] if b["path"] == entry["rules_bank"])


def official_of(entry: dict[str, Any]) -> Path | None:
    """The official YAML a manifest entry is evaluated against: its service's, of the
    spec version it came from. None for a service with no official here; an error for
    a known service with none of that version — never another version's."""
    code = spec_code_of(entry)
    services = {s for versions in OFFICIAL_BY_SPEC.values() for s in versions}
    if entry["service"] not in services:
        return None
    version = OFFICIAL_BY_SPEC.get(code, {}).get(entry["service"])
    if version is None:
        raise ValueError(f"{entry['path']}: no official {entry['service']} YAML for spec "
                         f"version {code} (OFFICIAL_BY_SPEC)")
    return reference_yaml(entry["service"], version)


class VersionMismatch(ValueError):
    """An input is not of the spec version the analysis is based on."""


def spec_document(spec: str | Path) -> Path:
    """The spec an analysis is based on, by name ("28532-i00") or path."""
    path = Path(spec)
    found = path if path.suffix else SPECS_DIR / f"{spec}.md"
    if not found.is_file():
        raise FileNotFoundError(f"spec {spec}: no such document ({found})")
    return found


def check_versions(spec: Path, label: str, kind: str, official: dict[str, Any],
                   official_label: str, *, service: str | None = None,
                   allow_other_version: bool = False) -> list[str]:
    """Check an analysis against the spec version it is based on: the input must come
    from it, and the official YAML must be the one that spec holds. A difference is an
    error, unless allow_other_version says it is what is wanted; then it is returned,
    to be stated in the report. What cannot be told (an input outside data/inputs) is
    returned as a warning."""
    code = spec.stem.partition("-")[2]
    entry = next((e for e in manifest()[kind] if e["path"] == label), None)
    problems, unknown = [], []
    if entry is None:
        unknown.append(f"{label}: not in the manifest, its spec version cannot be checked")
    else:
        service = service or entry["service"]
        if spec_code_of(entry) != code:
            problems.append(f"{label} comes from spec {spec_code_of(entry)}, and the analysis "
                            f"is based on {spec.stem}")
    expected = OFFICIAL_BY_SPEC.get(code, {}).get(service or "")
    found = str((official.get("info") or {}).get("version", ""))
    if expected is None:
        unknown.append(f"{official_label}: the official {service or 'YAML'} of {spec.stem} "
                       "is not known, its version cannot be checked")
    elif found != expected:
        problems.append(f"{official_label} is v{found}, and the official of {spec.stem} is "
                        f"v{expected}")
    if problems and not allow_other_version:
        raise VersionMismatch("; ".join(problems) + " (allow_other_version / "
                              "--allow-other-version to compare them anyway)")
    return problems + unknown


def save_report(report: Any, service: str, evaluation: str, name: str, text: str) -> Path:
    """Write ONE report of one run under data/outputs/reports/<service>/<evaluation>/,
    named by when it was made — YYYY-MM-DD_HH-MM-SS.txt (to read), .pdf (the same text,
    laid out: reporting/pdf.py) and .json (its data); a second report in the same second
    gets _2, _3 ... A run never overwrites an earlier one. Which input it evaluates
    (`name`) is stated inside the report."""
    from datetime import datetime

    from openapi_analysis.config.paths import report_dir
    from openapi_analysis.reporting.pdf import write_pdf

    out_dir = report_dir(service, evaluation)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{datetime.fromisoformat(report.evaluated_at):%Y-%m-%d_%H-%M-%S}"
    stem, n = base, 1
    while any((out_dir / f"{stem}.{ext}").exists() for ext in ("txt", "json", "pdf")):
        n += 1
        stem = f"{base}_{n}"
    text = text.rstrip("\n") + "\n"
    (out_dir / f"{stem}.json").write_text(report.model_dump_json(indent=2) + "\n",
                                          encoding="utf-8")
    (out_dir / f"{stem}.txt").write_text(text, encoding="utf-8")
    write_pdf(text, out_dir / f"{stem}.pdf", title=f"{service} {evaluation} — {name}")
    return out_dir / f"{stem}.txt"
