"""Service for evaluation 1: a generated rules bank against the official YAML.

    official YAML ──extract_official_rules──▶ rules (rules-bank format) ─┐
                                                                         ├─▶ evaluate_rules_bank
    generated rules bank (JSON) ─────────────────────────────────────────┘
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.config.settings import OFFICIAL_REFERENCE, SPEC_VERSIONS
from openapi_analysis.reporting.text import render_rulesbank
from openapi_analysis.rulesbank.comparison import compare_rules
from openapi_analysis.rulesbank.extraction import rules_from_yaml, summarize
from openapi_analysis.schemas.rulesbank import RulesBankEvaluation, SourceInfo
from openapi_analysis.services.inputs import Source, load, manifest, save_report

_BANK_SPEC = re.compile(r"rules_bank_\d+-(i\d\d)_")


def _official_info(doc: dict, label: str) -> SourceInfo:
    return SourceInfo(label=label, version=str((doc.get("info") or {}).get("version", "")))


def _bank_info(bank: dict, label: str) -> SourceInfo:
    meta = bank.get("metadata") or {}
    code = _BANK_SPEC.search(label)
    version = code.group(1) if code else ""
    if version in SPEC_VERSIONS:
        version = f"{version} = TS 28.532 V{SPEC_VERSIONS[version]}"
    return SourceInfo(label=label, version=version, model=str(meta.get("model", "")),
                      generated_at=str(meta.get("generated_at", "")))


def extract_official_rules(official_yaml: Source) -> dict[str, Any]:
    """The official YAML's rules as a rules-bank-shaped document ({metadata, summary, rules})."""
    doc, label = load(official_yaml)
    rules = rules_from_yaml(doc)
    return {
        "metadata": {"source": label,
                     "openapi_version": str((doc.get("info") or {}).get("version", "")),
                     "extracted_by": "openapi_analysis.rulesbank.extraction"},
        "summary": summarize(rules),
        "rules": rules,
    }


def evaluate_rules_bank(rules_bank: Source, official_yaml: Source, *,
                        save_as: tuple[str, str] | None = None) -> RulesBankEvaluation:
    """Evaluate a generated rules bank against the official YAML, rule by rule.

    rules_bank / official_yaml: a parsed dict or a path. save_as=(service, name)
    also writes the report to data/outputs/<service>/<name>.json|.txt.
    """
    bank, bank_label = load(rules_bank)
    doc, doc_label = load(official_yaml)
    report = compare_rules(rules_from_yaml(doc), bank,
                           official=_official_info(doc, doc_label),
                           bank_info=_bank_info(bank, bank_label))
    if save_as:
        save_report(report, *save_as, text=render_rulesbank(report, max_items=10_000))
    return report


def evaluate_all_rules_banks(save: bool = True) -> list[RulesBankEvaluation]:
    """Every bank in data/inputs (per the manifest), against its service's official YAML."""
    reports = []
    for entry in manifest()["rulesbank"]:
        service = entry["service"]
        if service not in OFFICIAL_REFERENCE:
            continue
        official = reference_yaml(service, OFFICIAL_REFERENCE[service])
        name = f"rulesbank__{Path(entry['path']).stem}"
        reports.append(evaluate_rules_bank(ROOT / entry["path"], official,
                                           save_as=(service, name) if save else None))
    return reports
