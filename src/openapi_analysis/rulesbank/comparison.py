"""Compare the rules extracted from the official YAML with a generated rules bank.

Rule by rule, both sides in the rules-bank format and keyed by rule_types.rule_key.
Bank rules sharing a key are grouped in lists, never overwritten in a dict, so a
duplicate stays visible (the "0 rules vanished" mis-measurement was that overwrite).

ADDRESS — an official rule is covered when at least one bank rule has its key.
VALUE   — for a covered rule, the first bank rule's value is checked against the
          official one, by what the value IS for that rule type:
            $ref-valued    the SET of referenced schemas (file + name), taken from
                           references[] and from any $ref written in openapi_value.
                           A ref whose name matches but whose file was dropped is
                           the §3.23 defect (external ref turned internal).
            enum/required  the set of items (order ignored).
            a type         the JSON type the bank value starts with.
            path_operation the method; callback the runtime expression.
            request_body   the media type is the address itself — equal by match.
          Where the official YAML has nothing to compare against (a body-less
          response, a property with no type), the value is "not_comparable".
"""

from __future__ import annotations

import re
from collections import defaultdict

from openapi_analysis.rulesbank.rule_types import KNOWN_RULE_TYPES, RuleKey, rule_key
from openapi_analysis.schemas.rulesbank import (
    BankRuleRef,
    Counts,
    ExtraRule,
    RuleMatch,
    RulesBankEvaluation,
    SourceInfo,
    ValueStatus,
)

_REF = re.compile(r"([A-Za-z0-9_.\-]+\.ya?ml)?#/components/[A-Za-z]+/([A-Za-z0-9_.\-]+)")
_JSON_TYPES = ("string", "integer", "number", "boolean", "array", "object")


# ── value comparison ─────────────────────────────────────────────────────────

def _mapping(rule: dict) -> dict:
    return rule.get("openapi_mapping") or {}


def _ref_set(rule: dict) -> set[tuple[str, str]]:
    """{(file, schema_name)} from references[] and from $refs written in the value."""
    m = _mapping(rule)
    refs = {(r.get("file", "") or "", r.get("schema_name", "") or "")
            for r in (m.get("references") or []) if isinstance(r, dict)}
    refs |= {(f or "", n) for f, n in _REF.findall(str(m.get("openapi_value", "")))}
    return {r for r in refs if r[1]}


def _items(value: str) -> list[str]:
    """'[a, "b", c]' → ['a', 'b', 'c'] (each chunk between commas, unquoted)."""
    inner = value.strip().strip("[]")
    return [i.strip().strip("'\"") for i in inner.split(",") if i.strip()]


def _compare_items(exp_value: str, act_value: str) -> tuple[ValueStatus, str]:
    """enum / required: the same set of items, order ignored.

    A bank sometimes writes each item with its description ("A — meaning, ...").
    Then the chunks are not items, so only presence is checked: every official item
    must appear as a whole word; items the bank adds cannot be told from prose.
    """
    expected = set(_items(exp_value))
    chunks = _items(act_value)
    if all(re.fullmatch(r"[\w.\-]+", c) for c in chunks):
        actual = set(chunks)
        if actual == expected:
            return "equal", ""
        return "different", (f"missing {sorted(expected - actual)} "
                             f"extra {sorted(actual - expected)}")
    absent = sorted(i for i in expected if not re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])",
                                                          act_value))
    if not absent:
        return "equal", "items written with prose; extras not checkable"
    return "different", f"missing {absent} (items written with prose)"


def _first_type(value: str) -> str:
    words = re.findall(r"[A-Za-z]+", value.lower())
    return words[0] if words and words[0] in _JSON_TYPES else ""


def _expression(value: str) -> str:
    return value.strip().strip("{}").lstrip("$").strip()


def compare_value(expected: dict, actual: dict) -> tuple[ValueStatus, str]:
    """Judge a bank rule's value against the official rule on the same address."""
    rule_type = expected["rule_type"]
    field = _mapping(expected).get("openapi_field", "")
    exp_value = str(_mapping(expected).get("openapi_value", ""))
    act_value = str(_mapping(actual).get("openapi_value", ""))

    if rule_type == "request_body":
        return "equal", ""
    if rule_type == "path_operation":
        same = act_value.strip().upper() == exp_value.upper()
        return ("equal", "") if same else ("different", f"method {act_value!r}")
    if rule_type == "callback":
        same = _expression(act_value) == _expression(exp_value)
        return ("equal", "") if same else ("different", f"expression {act_value!r}")
    if field in ("enum", "required"):
        return _compare_items(exp_value, act_value)

    exp_refs, act_refs = _ref_set(expected), _ref_set(actual)
    if exp_refs:
        if act_refs == exp_refs:
            return "equal", ""
        lost_file = {n for f, n in exp_refs if f} & {n for f, n in act_refs if not f}
        if lost_file:
            return "different", f"§3.23 external $ref lost its file: {sorted(lost_file)}"
        return "different", (f"refs missing {sorted(exp_refs - act_refs)} "
                             f"extra {sorted(act_refs - exp_refs)}")
    if act_refs:
        return "different", f"bank has $ref {sorted(act_refs)} where the YAML has none"
    if exp_value in _JSON_TYPES:
        act_type = _first_type(act_value)
        return ("equal", "") if act_type == exp_value else ("different", f"type {act_value!r}")
    return "not_comparable", "the official YAML has no value to compare here"


# ── rule-by-rule comparison ──────────────────────────────────────────────────

def _bank_ref(index: int, rule: dict) -> BankRuleRef:
    m = _mapping(rule)
    return BankRuleRef(
        index=index, rule_type=rule.get("rule_type", ""),
        openapi_object=m.get("openapi_object", ""), openapi_field=m.get("openapi_field", ""),
        openapi_value=str(m.get("openapi_value", "")),
        references=[r for r in (m.get("references") or []) if isinstance(r, dict)],
        validation_passed=rule.get("validation_passed"),
    )


def compare_rules(official_rules: list[dict], bank: dict, *,
                  official: SourceInfo | None = None,
                  bank_info: SourceInfo | None = None) -> RulesBankEvaluation:
    """Compare official rules (from extraction.rules_from_yaml) with a rules bank JSON."""
    bank_rules = [r for r in (bank.get("rules") or []) if isinstance(r, dict)]
    by_key: dict[RuleKey, list[int]] = defaultdict(list)
    for i, rule in enumerate(bank_rules):
        by_key[rule_key(rule)].append(i)

    counts: dict[str, Counts] = defaultdict(Counts)
    matches: list[RuleMatch] = []
    missing: list[dict] = []
    official_keys: set[RuleKey] = set()
    for rule in official_rules:
        key = rule_key(rule)
        official_keys.add(key)
        c = counts[rule["rule_type"]]
        c.expected += 1
        hits = by_key.get(key)
        if not hits:
            missing.append(rule)
            continue
        c.covered += 1
        status, note = compare_value(rule, bank_rules[hits[0]])
        setattr(c, f"value_{status}", getattr(c, f"value_{status}") + 1)
        matches.append(RuleMatch(expected=rule, bank=[_bank_ref(i, bank_rules[i]) for i in hits],
                                 value_status=status, note=note))

    extra: list[ExtraRule] = []
    for i, rule in enumerate(bank_rules):
        c = counts[rule.get("rule_type", "")]
        c.bank_rules += 1
        if rule_key(rule) in official_keys:
            continue
        c.bank_extra += 1
        reason = ("unknown_rule_type" if rule.get("rule_type") not in KNOWN_RULE_TYPES
                  else "not_in_official_yaml")
        extra.append(ExtraRule(rule=_bank_ref(i, rule), reason=reason))

    totals = Counts()
    for c in counts.values():
        for name in Counts.model_fields:
            setattr(totals, name, getattr(totals, name) + getattr(c, name))

    meta = bank.get("metadata") or {}
    return RulesBankEvaluation(
        official=official or SourceInfo(),
        bank=bank_info or SourceInfo(model=str(meta.get("model", "")),
                                     generated_at=str(meta.get("generated_at", ""))),
        bank_invalid_rules=sum(1 for r in bank_rules if r.get("validation_passed") is False),
        totals=totals,
        by_rule_type=dict(sorted(counts.items())),
        matches=matches, missing=missing, extra=extra,
    )
