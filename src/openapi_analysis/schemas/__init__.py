"""The reports each evaluation returns (Pydantic models).

The contract with every caller — sibling repos, chat UI, CLI. The JSON shape of a
report is versioned by config.settings.REPORT_SCHEMA_VERSION.
"""

from openapi_analysis.schemas.openapi import GroupScore, LeafDifference, OpenAPIEvaluation
from openapi_analysis.schemas.rulesbank import (
    BankRuleRef,
    Counts,
    ExtraRule,
    RuleMatch,
    RulesBankEvaluation,
    SourceInfo,
)

__all__ = [
    "BankRuleRef", "Counts", "ExtraRule", "GroupScore", "LeafDifference",
    "OpenAPIEvaluation", "RuleMatch", "RulesBankEvaluation", "SourceInfo",
]
