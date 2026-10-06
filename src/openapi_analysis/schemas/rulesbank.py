"""Report of evaluation 1 — rules extracted from the official YAML × generated rules bank.

Two questions, answered apart because one does not imply the other (§3.19b):
  address  is there a bank rule on each official rule's address?   (coverage)
  value    where there is, does its value say what the YAML says?  (fidelity)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from openapi_analysis.config.settings import REPORT_SCHEMA_VERSION


def now() -> str:
    """The moment a report is produced, local time with offset, to the second."""
    return datetime.now().astimezone().isoformat(timespec="seconds")

ValueStatus = Literal["equal", "different", "not_comparable"]


class BankRuleRef(BaseModel):
    """A rule of the generated bank, pointed at by its position in rules[]."""
    index: int
    rule_type: str
    openapi_object: str
    openapi_field: str
    openapi_value: str
    references: list[dict[str, str]] = Field(default_factory=list)
    validation_passed: bool | None = None


class RuleMatch(BaseModel):
    """An official rule found in the bank, and how its value compares."""
    expected: dict[str, Any]                 # the official rule (rules-bank format)
    bank: list[BankRuleRef]                  # every bank rule on that address
    value_status: ValueStatus                # judged on bank[0]
    note: str = ""                           # why, when not "equal"


class ExtraRule(BaseModel):
    """A bank rule whose address is not in the official YAML."""
    rule: BankRuleRef
    reason: Literal["unknown_rule_type", "not_in_official_yaml"]


class Counts(BaseModel):
    """Counts for one rule_type (or for all of them)."""
    expected: int = 0            # rules in the official YAML
    covered: int = 0             # … with at least one bank rule on their address
    value_equal: int = 0
    value_different: int = 0
    value_not_comparable: int = 0
    bank_rules: int = 0          # rules in the bank = covered + bank_duplicates + bank_extra
    bank_duplicates: int = 0     # … on an official address another bank rule already holds
    bank_extra: int = 0          # … on no official address

    @computed_field
    @property
    def missing(self) -> int:
        return self.expected - self.covered

    @computed_field
    @property
    def coverage(self) -> float:
        """covered / expected — is the address there?"""
        return round(self.covered / self.expected, 4) if self.expected else 0.0

    @computed_field
    @property
    def fidelity(self) -> float:
        """value_equal / (covered − not_comparable) — is the value right where it is checkable?"""
        checkable = self.value_equal + self.value_different
        return round(self.value_equal / checkable, 4) if checkable else 0.0


class SourceInfo(BaseModel):
    label: str = ""              # path, or what the caller called it
    version: str = ""            # info.version of a YAML / spec of a bank
    model: str = ""              # LLM that generated it, when known
    generated_at: str = ""


class RulesBankEvaluation(BaseModel):
    schema_version: int = REPORT_SCHEMA_VERSION
    kind: Literal["rulesbank"] = "rulesbank"
    evaluated_at: str = Field(default_factory=now)   # when THIS report was produced
    official: SourceInfo
    bank: SourceInfo
    bank_invalid_rules: int = 0               # validation_passed == False (§2.1)
    totals: Counts
    by_rule_type: dict[str, Counts]
    matches: list[RuleMatch]
    missing: list[dict[str, Any]]             # official rules with no bank rule
    extra: list[ExtraRule]

    @computed_field
    @property
    def shared_addresses(self) -> list[RuleMatch]:
        """Official addresses held by more than one bank rule (§3.24 / §3.27)."""
        return [m for m in self.matches if len(m.bank) > 1]
