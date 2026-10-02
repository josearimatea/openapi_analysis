"""The entry points callers use — sibling repos, chat UI, CLI (and the HTTP API later).

Each takes its inputs already parsed (dict) or as paths, runs the evaluation and
returns the report from schemas/ — optionally saving it under data/outputs.

    from openapi_analysis.services import evaluate_rules_bank, evaluate_openapi
    report = evaluate_rules_bank(bank_dict, "path/to/official.yaml")
    report.totals.coverage, report.model_dump_json()
"""

from openapi_analysis.services.openapi_service import evaluate_all_generated, evaluate_openapi
from openapi_analysis.services.rulesbank_service import (
    evaluate_all_rules_banks,
    evaluate_rules_bank,
    extract_official_rules,
)

__all__ = [
    "evaluate_all_generated", "evaluate_all_rules_banks", "evaluate_openapi",
    "evaluate_rules_bank", "extract_official_rules",
]
