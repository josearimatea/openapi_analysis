"""The parts the judge receives (docs/JUDGE_PLAN.md §3) — deterministic, no LLM.

Pinned on the real inputs: what is equal never becomes a part, ids are unique (the
verdict cache is keyed on them), each callback is its own part, and every layer-2
issue lands in a part.
"""

import json
from collections import Counter

import pytest
import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.judge.parts import _keys, generator_parts, rulesbank_parts
from openapi_analysis.services import evaluate_openapi, evaluate_rules_bank

OFFICIAL = yaml.safe_load(reference_yaml("ProvMnS", "18.2.0").read_text(encoding="utf-8"))
GENERATED = ROOT / "data/inputs/generated/ProvMnS"
BANK = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20260915_214107.json"


def _generator(name):
    gen = yaml.safe_load((GENERATED / f"{name}.yaml").read_text(encoding="utf-8"))
    report = evaluate_openapi(gen, OFFICIAL)
    return generator_parts(report, gen, OFFICIAL, name), report


@pytest.fixture(scope="module")
def latest():
    return _generator("provmns_20260920_194130")


def test_a_document_equal_to_the_official_has_no_part():
    assert generator_parts(evaluate_openapi(OFFICIAL, OFFICIAL), OFFICIAL, OFFICIAL, "x") == []


@pytest.mark.parametrize("name, total, by_aspect", [
    ("provmns_20260920_194130", 37,
     {"callback": 9, "definition": 8, "extra": 5, "operation": 1, "parameters": 5, "path": 1,
      "placement": 2, "request_body": 1, "responses": 4, "unexpected_keys": 1}),
    ("provmns_20260828_232853", 36,
     {"callback": 5, "definition": 10, "extra": 4, "missing": 2, "operation": 5,
      "parameters": 5, "request_body": 1, "responses": 4}),
])
def test_generator_parts_per_aspect(name, total, by_aspect):
    parts, _ = _generator(name)
    assert len(parts) == total
    assert dict(Counter(p.aspect.split()[0] for p in parts)) == by_aspect


def test_ids_are_unique(latest):
    parts, _ = latest
    assert len({p.id for p in parts}) == len(parts)


def test_each_callback_is_its_own_part(latest):
    parts, _ = latest
    callbacks = {p.aspect for p in parts if p.owner == "PUT /{className}={id}"
                 and p.aspect.startswith("callback ")}
    assert {"callback notifyMOICreation", "callback notifyEvent",
            "callback $request.body#/notificationTarget"} <= callbacks


def test_every_layer2_issue_lands_in_a_part(latest):
    parts, report = latest
    attached = {i for p in parts for i in p.invalid_issues}
    assert len(attached) == len(report.validity_generated.issues) == 18


def test_an_issue_naming_several_schemas_goes_to_each(latest):
    """'components: MoiChange, NotifyMoiAttributeValueChanges, ... unexpected'."""
    parts, _ = latest
    for name in ("MoiChange", "NotifyMoiAttributeValueChanges"):
        part = next(p for p in parts if p.owner == f"SCHEMA {name}")
        assert part.aspect == "placement"
        assert any(i.startswith("components: ") for i in part.invalid_issues)


def test_the_patch_responses_part_carries_both_sides_and_hints(latest):
    parts, _ = latest
    p = next(p for p in parts if p.owner == "PATCH /{className}={id}" and p.aspect == "responses")
    assert set(p.official) == {"200", "204", "default"}
    assert set(p.generated) == {"400", "4XX", "5XX"}
    assert (p.hints.path, p.hints.method) == ("/{className}={id}", "patch")
    assert "TS28623_ComDefs.yaml#/components/schemas/ErrorResponseDefault" in p.hints.external_refs


def test_rulesbank_parts():
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    parts = rulesbank_parts(evaluate_rules_bank(bank, OFFICIAL), bank, "i20")
    assert dict(Counter(p.aspect for p in parts)) == {
        "different": 18, "duplicate": 2, "missing": 32, "extra": 39}
    assert len({p.id for p in parts}) == len(parts)
    get200 = next(p for p in parts if p.aspect == "different"
                  and p.owner == "response paths./{className}={id}.get.responses · 200")
    assert get200.hints.clause == "12.1.1.1.3"            # the clause the rule came from
    assert get200.hints.terms == ["getMOIAttributes"]


def test_keys_keep_a_quoted_key_whole():
    assert _keys("callbacks.'$request.body#/x'.post") == ["callbacks", "$request.body#/x", "post"]
