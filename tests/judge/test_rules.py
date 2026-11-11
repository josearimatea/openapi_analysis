"""Verdicts decided by a rule (judge/rules.py): only from a fact of the structure, never
from a name of the spec — synthetic banks, then the bank of 09/nov/2026 pinned."""

import json

import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.judge.judge import rule_verdict
from openapi_analysis.judge.parts import rulesbank_parts
from openapi_analysis.judge.rules import BankFacts, decide, local_refs
from openapi_analysis.services import evaluate_rules_bank

OBJ = "components/schemas/N"


def bank_rule(obj, field, value, refs=()):
    return {"rule_type": "schema_property",
            "openapi_mapping": {"openapi_object": obj, "openapi_field": field,
                                "openapi_value": value,
                                "references": [{"file": f, "schema_name": n} for f, n in refs]}}


def never_completed(obj, field, name):
    return {"openapi_object": obj, "openapi_field": field,
            "reason": f"$ref to '{name}' not completed: no section stated whether '{name}' is "
                      "local or imported; the $ref target was left as written."}


def parts_of(bank, official_rules):
    from openapi_analysis.rulesbank.comparison import compare_rules

    return rulesbank_parts(compare_rules(official_rules, bank), bank, "t")


REF_X = "$ref: '#/components/schemas/X'"


def test_local_refs_are_those_with_no_file():
    rule = bank_rule(OBJ, "properties.p", "oneOf [$ref: '#/components/schemas/A', "
                     "$ref: 'B.yaml#/components/schemas/B']", refs=[("", "A"), ("B.yaml", "B")])
    assert local_refs(rule) == ["A"]


def test_a_ref_to_nothing_reported_never_completed_is_an_error():
    rule = bank_rule(OBJ, "properties.p", REF_X, refs=[("", "X")])
    bank = {"rules": [rule], "metadata": {"rules_never_completed": [
        never_completed(OBJ, "properties.p", "X")]}}
    (part,) = parts_of(bank, [])
    decided = decide(part, BankFacts(bank))
    assert decided is not None and decided.verdict == "error"
    assert "resolves to nothing" in decided.reason
    assert "reports the $ref to X as never completed" in part.summary


def test_with_one_fact_only_the_judge_decides_with_the_fact():
    """No rule on X, but not reported never completed: X may be a plain type the bank
    format cannot declare — the judge's, told the fact."""
    rule = bank_rule(OBJ, "properties.p", REF_X, refs=[("", "X")])
    bank = {"rules": [rule]}
    (part,) = parts_of(bank, [])
    assert decide(part, BankFacts(bank)) is None
    assert "the bank defines no X" in part.summary


def test_a_ref_to_a_schema_the_bank_defines_is_no_fact():
    rule = bank_rule(OBJ, "properties.p", REF_X, refs=[("", "X")])
    bank = {"rules": [rule, bank_rule("components/schemas/X", "properties.q", "string")],
            "metadata": {"rules_never_completed": [never_completed(OBJ, "properties.p", "X")]}}
    parts = parts_of(bank, [])
    assert all(decide(p, BankFacts(bank)) is None for p in parts)
    assert not any("defines no" in p.summary for p in parts)


def test_a_rule_verdict_has_no_llm_and_says_its_reason():
    rule = bank_rule(OBJ, "properties.p", REF_X, refs=[("", "X")])
    bank = {"rules": [rule], "metadata": {"rules_never_completed": [
        never_completed(OBJ, "properties.p", "X")]}}
    (part,) = parts_of(bank, [])
    decided = decide(part, BankFacts(bank))
    v = rule_verdict(part, decided.verdict, decided.reason)
    assert (v.decided_by, v.answer.verdict, v.evidence, v.model) == ("rule", "error", [], "")
    assert v.answer.why_different == decided.reason


def _param(obj, value):
    rule = bank_rule(obj, "parameters[in=path,name=id]", value)
    return {**rule, "rule_type": "path_parameter"}


def test_a_path_parameter_repeated_at_an_operation_is_redundant():
    bank = {"rules": [_param("paths./a/{id}", "string"), _param("paths./a/{id}.delete", "string")]}
    official = [_param("paths./a/{id}", "string")]
    (part,) = parts_of(bank, official)                  # the operation's: an extra
    decided = decide(part, BankFacts(bank))
    assert decided is not None and decided.verdict == "error"
    assert "Path Item Object" in decided.reason


def test_a_parameter_with_another_value_at_the_operation_overrides_it_the_judge_decides():
    bank = {"rules": [_param("paths./a/{id}", "string"), _param("paths./a/{id}.delete", "integer")]}
    (part,) = parts_of(bank, [_param("paths./a/{id}", "string")])
    assert decide(part, BankFacts(bank)) is None


def test_the_bank_of_09_nov_2026():
    """What a rule decides in the bank of 09/nov/2026 (docs/PROBLEMS.md): the local $refs
    that resolve to nothing (A.5), the path parameters repeated at the DELETE (A.6) and the
    form of the error responses of each operation (A.1, A.2). Only the ranges of PUT and
    PATCH — default and ranges with different values — are left to the judge."""
    path = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20261109_102214.json"
    bank = json.loads(path.read_text(encoding="utf-8"))
    official = yaml.safe_load(reference_yaml("ProvMnS", "18.2.0").read_text(encoding="utf-8"))
    facts = BankFacts(bank)
    decided = {}
    for p in rulesbank_parts(evaluate_rules_bank(bank, official), bank, "i20"):
        d = decide(p, facts)
        if d is not None:
            decided[p.owner] = (d.per_rule or d.verdict, d.complete,
                                [x.location for x in p.differences])
    ops = "response paths./{className}={id}"
    cb = f"{ops}.put.callbacks.NAME.post.responses · error responses"
    improvement = "improvement"
    assert decided == {
        f"{ops}.get.responses · error responses": (    # the same value in the three: by form,
            {"13": "error", "38": "error", "39": "error"}, True, []),   # all $ref to nothing
        f"{ops}.put.responses · error responses": (
            {"7": "error"}, False, ["4XX (rule #36)", "5XX (rule #37)"]),
        f"{ops}.patch.responses · error responses": (
            {"18": "error"}, False, ["4XX (rule #41)", "5XX (rule #42)"]),
        **{cb.replace("NAME", n): ({str(a): improvement, str(a + 1): improvement}, True, [])
           for n, a in (("notifyMOICreation", 51), ("notifyMOIDeletion", 53),
                        ("notifyMOIAttributeValueChanges", 55), ("notifyMOIChanges", 57),
                        ("notifyEvent", 59))},
        f"{ops}.delete.responses · default": ("error", True, []),   # default only: as any rule
        "schema_property components/schemas/NotifyEvent · properties.specificProblem":
            ("error", True, []),
        "schema_property components/schemas/NotifyMoiAttributeValueChanges · "
        "properties.additionalText": ("error", True, []),
        "path_parameter paths./{className}={id}.delete · "
        "parameters[in=path,name=className]": ("error", True, []),
        "path_parameter paths./{className}={id}.delete · parameters[in=path,name=id]":
            ("error", True, []),
    }


# ── the error responses of one operation: each situation of the criterion ───────

OP = "paths./a.get.responses"
A = ("$ref: 'C.yaml#/components/schemas/A'", [("C.yaml", "A")])
B = ("$ref: 'C.yaml#/components/schemas/B'", [("C.yaml", "B")])


def resp(field, value=A):
    rule = bank_rule(OP, field, value[0], refs=value[1])
    return {**rule, "rule_type": "response"}


def plan(official, *bank):
    from openapi_analysis.judge.rules import error_plan

    return error_plan(official, dict(enumerate(bank)), BankFacts({"rules": list(bank)}))


def test_ranges_alone_with_the_official_value_are_an_improvement():
    p = plan(resp("default"), resp("4XX"), resp("5XX"))
    assert (p.case, p.fixed, p.asked) == ("4XX + 5XX only",
                                          {"0": "improvement", "1": "improvement"}, [])


def test_ranges_alone_with_another_value_ask_only_the_value():
    p = plan(resp("default", B), resp("4XX"), resp("5XX"))
    assert (p.fixed, p.asked) == ({}, ["0", "1"]) and "VALUE" in p.question


def test_default_with_the_same_value_as_the_ranges_is_left_over():
    p = plan(resp("default"), resp("default"), resp("4XX"), resp("5XX"))
    assert p.case == "4XX + 5XX + default, the same value"
    assert p.fixed == {"0": "error", "1": "improvement", "2": "improvement"}


def test_default_and_ranges_with_different_values_ask_the_question():
    p = plan(resp("default", B), resp("default", B), resp("4XX"), resp("5XX"))
    assert (p.case, p.fixed, p.asked) == ("4XX + 5XX + default, different values", {},
                                          ["0", "1", "2"])
    assert "restricts to this operation" in p.question


def test_one_range_next_to_default_is_wrong():
    p = plan(resp("default"), resp("default"), resp("4XX"))
    assert (p.case, p.fixed, p.asked) == ("default + one range",
                                          {"1": "error", "0": "same"}, [])


def test_one_range_alone_is_wrong_and_the_default_missing():
    p = plan(resp("default"), resp("5XX"))
    assert (p.case, p.fixed) == ("one range, no default", {"0": "error", "official": "error"})


def test_ranges_with_different_values_fall_outside_the_cases():
    p = plan(resp("default"), resp("4XX", B), resp("5XX"))
    assert (p.case, p.asked) == ("other", ["0", "1"])


def test_the_views_take_each_rule_s_own_verdict():
    """In an "error responses" part each rule takes its own verdict (rule_verdicts); every
    official rule and every bank rule is still counted once."""
    from types import SimpleNamespace

    from openapi_analysis.judge.parts import rulesbank_views
    from openapi_analysis.rulesbank.comparison import compare_rules

    official = [resp("default")]
    bank = {"rules": [resp("default", B), resp("4XX"), resp("5XX")]}
    ev = compare_rules(official, bank)
    (part,) = rulesbank_parts(ev, bank, "t")
    verdict = SimpleNamespace(part_id=part.id, answer=SimpleNamespace(verdict="error"),
                              rule_verdicts={"0": "error", "1": "improvement",
                                             "2": "improvement"})
    assert rulesbank_views(ev, bank, [verdict], "t") == {
        "official": {"wrong": 1},                      # the bank's default stands for it
        "generated": {"wrong": 1, "better": 2}}
