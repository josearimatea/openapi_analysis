"""Service for evaluation 2: a generated OpenAPI document against the official one.

    generated YAML ──┐
                     ├─▶ evaluate_openapi (document against document)
    official YAML  ──┘
"""

from __future__ import annotations

from pathlib import Path

from openapi_analysis.config.paths import OUTPUTS_GENERATOR_DIR, ROOT, reference_yaml
from openapi_analysis.config.settings import OFFICIAL_REFERENCE
from openapi_analysis.openapi.comparison import compare_documents
from openapi_analysis.reporting.text import render_openapi
from openapi_analysis.schemas.openapi import OpenAPIEvaluation
from openapi_analysis.schemas.rulesbank import SourceInfo
from openapi_analysis.services.inputs import Source, load, manifest, save_report


def _generated_info(doc: dict, label: str) -> SourceInfo:
    gen = doc.get("x-ai-generation") or (doc.get("info") or {}).get("x-openapi-generator") or {}
    return SourceInfo(label=label, version=str((doc.get("info") or {}).get("version", "")),
                      model=str(gen.get("model", "")),
                      generated_at=str(gen.get("generated-at", "")))


def evaluate_openapi(generated_yaml: Source, official_yaml: Source, *,
                     save_as: tuple[str, str] | None = None) -> OpenAPIEvaluation:
    """Evaluate a generated OpenAPI document against the official YAML.

    generated_yaml / official_yaml: a parsed dict or a path. save_as=(service, name)
    also writes the report to data/outputs/generator/<service>/<name>.json|.txt.
    """
    gen, gen_label = load(generated_yaml)
    off, off_label = load(official_yaml)
    report = compare_documents(
        gen, off, generated_info=_generated_info(gen, gen_label),
        official_info=SourceInfo(label=off_label,
                                 version=str((off.get("info") or {}).get("version", ""))))
    if save_as:
        save_report(report, OUTPUTS_GENERATOR_DIR, *save_as,
                    text=render_openapi(report, max_items=10_000))
    return report


def evaluate_all_generated(save: bool = True) -> list[OpenAPIEvaluation]:
    """Every generated document in data/inputs (per the manifest), against its service's
    official YAML."""
    reports = []
    for entry in manifest()["generated"]:
        service = entry["service"]
        if service not in OFFICIAL_REFERENCE:
            continue
        official = reference_yaml(service, OFFICIAL_REFERENCE[service])
        name = Path(entry["path"]).stem
        reports.append(evaluate_openapi(ROOT / entry["path"], official,
                                        save_as=(service, name) if save else None))
    return reports
