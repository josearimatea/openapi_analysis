"""The rules bank's parts and the diff the generator's parts are built on
(judge/parts.py) — deterministic, no LLM. The generator's parts themselves come from
the alignment: tests/judge/test_group_parts.py."""

import json
from collections import Counter

import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.judge.parts import _keys, diff_documents, rulesbank_parts
from openapi_analysis.openapi.comparison import join
from openapi_analysis.services import evaluate_rules_bank

OFFICIAL = yaml.safe_load(reference_yaml("ProvMnS", "18.2.0").read_text(encoding="utf-8"))
BANK = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20260915_214107.json"


def test_the_diff_reads_leaves_as_layer_1_does():
    """Parameters by (in, name), enum as a set, a one-sided subtree as one entry."""
    off = {"paths": {"/a": {"get": {"parameters": [{"in": "query", "name": "x"},
                                                   {"in": "query", "name": "y"}]}}},
           "components": {"schemas": {"E": {"enum": ["a", "b"]}, "S": {"type": "string"}}}}
    gen = {"paths": {"/a": {"get": {"parameters": [{"in": "query", "name": "y"}]}}},
           "components": {"schemas": {"E": {"enum": ["b", "a"]}}}}
    assert [(k, join(p)) for k, p, _, _ in diff_documents(off, gen)] == [
        ("absent", "paths./a.get.parameters[in=query,name=x]"),
        ("absent", "components.schemas.S")]


def test_rulesbank_parts():
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    parts = rulesbank_parts(evaluate_rules_bank(bank, OFFICIAL), bank, "i20")
    assert dict(Counter(p.aspect for p in parts)) == {
        "different": 24, "duplicate": 2, "missing": 20, "extra": 28}
    assert len({p.id for p in parts}) == len(parts)
    get200 = next(p for p in parts if p.aspect == "different"
                  and p.owner == "response paths./{className}={id}.get.responses · 200")
    assert get200.hints.clause == "12.1.1.1.3"            # the clause the rule came from
    assert get200.hints.terms == ["getMOIAttributes"]


def test_keys_keep_a_quoted_key_whole():
    assert _keys("callbacks.'$request.body#/x'.post") == ["callbacks", "$request.body#/x", "post"]
