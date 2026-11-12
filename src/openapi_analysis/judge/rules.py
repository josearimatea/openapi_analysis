"""Verdicts decided by a rule, not by the LLM (docs/FIX_PLAN.md) — layer 3, reported apart
from the judge's (`Verdict.decided_by == "rule"`).

A rule decides only what follows from a FACT of the structure of the rules, never from what
a type or a text means: no name of the spec is written here, and what needs reading stays
with the judge. A rule gives the same verdict for the same input; it is as right as the fact
it reads, and the fact is shown with the verdict.

Rules (one function each):
  unresolved_local_ref — a bank rule whose $ref to `#/components/schemas/X` resolves to
      nothing: the bank has no rule on `components/schemas/X` AND it reports that $ref as
      never completed (`metadata.rules_never_completed`). OpenAPI 3.0.1, Reference Object:
      the $ref must point to a definition; one that points to nothing is an error.
      The second fact is required: the bank format cannot declare a schema of a plain type
      (`schema_property` takes only `properties.<n>` and the keywords), so "no rule on X"
      alone would also condemn a right $ref to such a schema. With the first fact only,
      the part goes to the judge, with that fact in its summary.
  repeated_path_parameter — an extra bank rule declaring, at an operation, a parameter the
      bank already declares at the level of its path with the same `in`, name and value.
      OpenAPI 3.0.1, Path Item Object: the path's parameters apply to all its operations;
      the same one repeated adds nothing (redundant): extra wrong. With another value it
      overrides the path's (Operation Object): the judge's.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from openapi_analysis.rulesbank.comparison import compare_value
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS
from openapi_analysis.schemas.judge import Part

# a local $ref in a value: "#/components/schemas/X" not preceded by a file name
_LOCAL_REF = re.compile(r"(?<![\w.\-])#/components/schemas/([A-Za-z0-9_.\-]+)")
# how the generator reports a $ref it never completed (rules_never_completed[].reason)
_NOT_COMPLETED = re.compile(r"\$ref to '([^']+)' not completed")
_SCHEMAS = "components/schemas/"
# the keys of a Responses Object that cover a set of codes (OpenAPI 3.0.1): default, a range
_ERROR_FIELD = re.compile(r"^(default|[1-5]XX)$", re.IGNORECASE)
# most serious first (judge/judge.py _SEVERITY); "same": equal to the official, no verdict
SEVERITY = ("error", "uncertain", "improvement", "useful", "equivalent")


@dataclass(frozen=True)
class RuleVerdict:
    verdict: str        # error | improvement | equivalent | useful (the judge's labels)
    reason: str         # the fact it follows from, said to the reader
    per_rule: dict[str, str] = field(default_factory=dict)   # "error responses" part: the
                        # verdict of each rule (bank rule index, or "official"), "same" when
                        # equal to the official
    complete: bool = True   # False: the judge rules on the rest (the part's differences)


def worst(verdicts) -> str:
    """The most serious verdict, "same" left out ("" when there is none)."""
    given = [v for v in verdicts if v and v != "same"]
    return next((v for v in SEVERITY if v in given), "")


def _mapping(rule: dict) -> dict:
    return rule.get("openapi_mapping") or {}


def local_refs(rule: dict) -> list[str]:
    """The schemas a bank rule refers to locally: references[] with no file, and
    `#/components/schemas/X` written in the value."""
    m = _mapping(rule)
    names = [r.get("schema_name", "") for r in (m.get("references") or [])
             if isinstance(r, dict) and not (r.get("file") or "")]
    names += _LOCAL_REF.findall(str(m.get("openapi_value", "")))
    return [n for n in dict.fromkeys(names) if n]


def _declaration(rule: dict) -> tuple[str, str, str, str]:
    """(rule_type, openapi_object, openapi_field, value) — the value as written, trimmed."""
    m = _mapping(rule)
    return (rule.get("rule_type", ""), m.get("openapi_object", ""), m.get("openapi_field", ""),
            str(m.get("openapi_value", "")).strip())


class BankFacts:
    """What of a bank the rules read: the schemas it defines, the $refs it never completed."""

    def __init__(self, bank: dict):
        rules = [r for r in (bank.get("rules") or []) if isinstance(r, dict)]
        self.defined = {_mapping(r).get("openapi_object", "")[len(_SCHEMAS):]
                        for r in rules
                        if str(_mapping(r).get("openapi_object", "")).startswith(_SCHEMAS)}
        self.declared = {_declaration(r) for r in rules}
        self.never_completed: dict[tuple[str, str], set[str]] = {}
        for e in (bank.get("metadata") or {}).get("rules_never_completed") or []:
            if isinstance(e, dict):
                key = (e.get("openapi_object", ""), e.get("openapi_field", ""))
                self.never_completed.setdefault(key, set()).update(
                    _NOT_COMPLETED.findall(str(e.get("reason", ""))))

    def undefined_refs(self, rule: dict) -> list[str]:
        """The local $refs of a rule to a schema the bank does not define."""
        return [n for n in local_refs(rule) if n not in self.defined]

    def not_completed(self, rule: dict) -> set[str]:
        m = _mapping(rule)
        return self.never_completed.get((m.get("openapi_object", ""),
                                         m.get("openapi_field", "")), set())


def ref_fact(rule: dict, facts: BankFacts) -> str:
    """The fact said to the judge (and to the reader) about the rule's local $refs."""
    undefined = facts.undefined_refs(rule)
    if not undefined:
        return ""
    unresolved = [n for n in undefined if n in facts.not_completed(rule)]
    text = f"the bank defines no {', '.join(undefined)} (no rule on {_SCHEMAS}<name>)"
    if unresolved:
        text += (f"; it reports the $ref to {', '.join(unresolved)} as never completed "
                 "(metadata.rules_never_completed)")
    return text


def _bank_rules(part: Part) -> list[dict]:
    side = part.generated
    if isinstance(side, dict):
        return [side]
    return [r for r in side or [] if isinstance(r, dict)]


def unresolved_local_ref(part: Part, facts: BankFacts) -> RuleVerdict | None:
    rules = _bank_rules(part)
    if len(rules) != 1:                 # several rules on one address: the judge's
        return None
    unresolved = [n for n in facts.undefined_refs(rules[0])
                  if n in facts.not_completed(rules[0])]
    if not unresolved:
        return None
    return RuleVerdict("error", (
        f"the $ref to #/components/schemas/{', '.join(unresolved)} resolves to nothing: the "
        f"bank defines no {', '.join(unresolved)} and reports this $ref as never completed "
        "(metadata.rules_never_completed). OpenAPI 3.0.1, Reference Object: a $ref must point "
        "to a definition."))


def repeated_path_parameter(part: Part, facts: BankFacts) -> RuleVerdict | None:
    rules = _bank_rules(part)
    if part.aspect != "extra" or len(rules) != 1:
        return None
    rule_type, obj, field, value = _declaration(rules[0])
    path, _, method = obj.rpartition(".")
    if not field.startswith("parameters[") or method not in HTTP_METHODS \
            or (rule_type, path, field, value) not in facts.declared:
        return None
    return RuleVerdict("error", (
        f"{field} is declared at {path} with the same value ({value}): OpenAPI 3.0.1, Path "
        f"Item Object — the path's parameters apply to all its operations, so declaring it "
        f"again at {method} adds nothing (redundant)."))


RULES = (unresolved_local_ref, repeated_path_parameter)


# ── the error responses of one operation (docs/PROBLEMS.md, A.1 and A.7) ──────────

ERROR_RESPONSES = "error responses"     # the aspect of the part that holds them
DISCARDABLE = "discardable"     # a rule the user may drop: default AND 4XX + 5XX declared,
                                # which configuration to keep is the user's choice (A.7)

_RANGES = {"4XX", "5XX"}
# default and 4XX + 5XX declared: nothing is ruled on the choice; the judge recommends one
QUESTION_RECOMMEND = (
    "The bank declares default AND 4XX + 5XX: which configuration to keep is the user's "
    "choice, so the ranges are not ruled (they are listed as discardable). RECOMMEND, in "
    "`recommendation`, the configuration the spec indicates for this operation, citing the S "
    "passages: '4XX + 5XX' if the spec gives the error only as 4xx/5xx codes; 'default' if it "
    "gives only an error type with no code, or gives both but the type with no code carries a "
    "condition (on the media type, on the request...) that the ranges' type loses; 'both' if "
    "it gives both forms and the ranges lose nothing.")
QUESTION_VALUE = (
    "The form is decided (see above). Judge only the VALUE of each listed rule against the "
    "official default: an error if it loses or contradicts the official's type; otherwise "
    "the verdict the form gave ({form}).")
QUESTION_OPEN = (
    "The bank's error responses here fall outside the cases decided by their form (e.g. 4XX "
    "and 5XX with different values, or a default that may not be an error response). Judge "
    "each listed rule against the spec and the official default.")


def is_error_response(rule: dict) -> bool:
    return (rule.get("rule_type") == "response"
            and bool(_ERROR_FIELD.match(str(_mapping(rule).get("openapi_field", "")))))


def error_field(rule: dict) -> str:
    f = str(_mapping(rule).get("openapi_field", ""))
    return "default" if f.lower() == "default" else f.upper()


def _same_value(a: dict, b: dict) -> bool:
    ma, mb = _mapping(a), _mapping(b)
    refs = [{(r.get("file") or "", r.get("schema_name") or "")
             for r in (m.get("references") or []) if isinstance(r, dict)} for m in (ma, mb)]
    return (str(ma.get("openapi_value", "")).strip() == str(mb.get("openapi_value", "")).strip()
            and refs[0] == refs[1])


def _equal_to_official(official: dict | None, rule: dict) -> bool:
    return official is not None and compare_value(official, rule)[0] == "equal"


@dataclass
class ErrorPlan:
    """What is decided by the form of one operation's error responses, and what is asked."""
    case: str
    fixed: dict[str, str] = field(default_factory=dict)    # key -> verdict ("same" too)
    reasons: dict[str, str] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)         # keys the judge rules on
    question: str = ""
    recommend: bool = False     # the judge recommends a configuration (A.7)


def error_plan(official: dict | None, bank: dict[int, dict], facts: BankFacts) -> ErrorPlan:
    """The criterion of 10/nov/2026, revised on 12/nov (A.7), by the STRUCTURE only (which
    keys the bank declares on the operation, and whether their values are the same); a key
    is a bank rule's index, or "official" for the official default. What needs reading is
    asked of the judge."""
    keys = {str(i): r for i, r in bank.items()}
    fields = Counter(error_field(r) for r in keys.values())
    default = next((k for k, r in keys.items() if error_field(r) == "default"), None)
    ranges = {k: r for k, r in keys.items() if error_field(r) in _RANGES}
    plan = ErrorPlan(case="other")

    def fix(key: str, verdict: str, reason: str) -> None:
        plan.fixed[key], plan.reasons[key] = verdict, reason

    def range_values_or_ask(form: str, why: str) -> None:
        for k, r in ranges.items():
            if official is None or _equal_to_official(official, r):
                fix(k, form, why)
            else:
                plan.asked.append(k)
        plan.question = QUESTION_VALUE.format(form=form)

    # each key once, and only default / 4XX / 5XX (any other range: the open question)
    single = all(n == 1 for n in fields.values()) and set(fields) <= _RANGES | {"default"}
    same_ranges = len(ranges) == 2 and _same_value(*ranges.values())
    take = ("OpenAPI 3.0.1, Responses Object: default covers only the codes not declared "
            "individually, so 4XX and 5XX together take its place")
    if single and len(ranges) == 2 and same_ranges and default is None:
        plan.case = "4XX + 5XX only"
        range_values_or_ask("improvement", f"{take} — the decided form: improvement")
    elif single and len(ranges) == 2 and same_ranges and default is not None:
        plan.case = "4XX + 5XX + default"
        for k in ranges:
            fix(k, DISCARDABLE, "default and 4XX + 5XX are two configurations of the same "
                "errors (OpenAPI 3.0.1, Responses Object): which one to keep is the user's "
                "choice")
        if _equal_to_official(official, keys[default]):
            fix(default, "same", "equal to the official default")
        else:
            plan.asked.append(default)
            plan.question = QUESTION_VALUE.format(form="the default is judged as any rule")
        plan.recommend = True
    elif single and len(ranges) == 1 and default is not None:
        plan.case = "default + one range"
        (k,) = ranges
        fix(k, "error", "one range next to default: default already covers every error, and "
            "the range lacks its pair (decided form: extra, wrong)")
        if _equal_to_official(official, keys[default]):
            fix(default, "same", "equal to the official default")
        else:
            plan.asked.append(default)
            plan.question = QUESTION_VALUE.format(form="the default is right")
    elif single and len(ranges) == 1 and default is None:
        plan.case = "one range, no default"
        (k,) = ranges
        fix(k, "error", "one range alone covers only its own codes (decided form: wrong)")
        if official is not None:
            fix("official", "error", "the official default is missing: one range does not "
                "take its place")
    else:
        plan.asked = list(keys)
        plan.question = QUESTION_OPEN
    for k, r in keys.items():                   # a $ref that resolves to nothing, first
        unresolved = [n for n in facts.undefined_refs(r) if n in facts.not_completed(r)]
        if unresolved:
            fix(k, "error", f"the $ref to #/components/schemas/{', '.join(unresolved)} "
                "resolves to nothing (the bank defines it nowhere and reports it never "
                "completed; OpenAPI 3.0.1, Reference Object)")
            if k in plan.asked:
                plan.asked.remove(k)
    if not plan.asked:
        plan.question = ""
    if plan.recommend:
        plan.question = " ".join(q for q in (plan.question, QUESTION_RECOMMEND) if q)
    return plan


def group_bank(part: Part) -> dict[int, dict]:
    """The bank rules of an "error responses" part, by index (its generated side)."""
    return {r["rule_index"]: r for r in _bank_rules(part) if "rule_index" in r}


def error_responses(part: Part, facts: BankFacts) -> RuleVerdict | None:
    if part.aspect != ERROR_RESPONSES:
        return None
    plan = error_plan(part.official, group_bank(part), facts)
    reason = f"CASE: {plan.case}. " + " ".join(
        f"{'official default' if k == 'official' else 'rule #' + k}: {v} — {plan.reasons[k]}."
        for k, v in plan.fixed.items())
    return RuleVerdict(worst(plan.fixed.values()) or "equivalent", reason.strip(),
                       per_rule=dict(plan.fixed),
                       complete=not plan.asked and not plan.recommend)


def decide(part: Part, facts: BankFacts) -> RuleVerdict | None:
    """The verdict of the first rule that decides this part, or None: the judge's.
    For an "error responses" part, what the form decides (complete or not)."""
    if part.evaluation != "rulesbank":
        return None
    if part.aspect == ERROR_RESPONSES:
        return error_responses(part, facts)
    for rule in RULES:
        decided = rule(part, facts)
        if decided is not None:
            return decided
    return None
