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
        "different": 16, "duplicate": 2, "missing": 19, "extra": 22,
        "error responses": 9}                                          # missing 21 -> 20 on
    # 08/nov/2026: "Resource · items" is no longer an official rule; different 23 -> 32 on
    # 09/nov/2026: the 9 not_comparable (no official value to compare) are judged too;
    # 32 -> 24 on 10/nov/2026: the official writes "no body" and {} / {nullable: true}, so
    # 6 x 204 and MoiChange.value / .oldValue are equal (docs/PROBLEMS.md A.3, A.4);
    # then the error responses (default, 4XX, 5XX) of 9 operations / callbacks go in one
    # part each (A.1, A.2): different 24 -> 16, extra 29 -> 22, missing 20 -> 19
    assert len({p.id for p in parts}) == len(parts)
    get200 = next(p for p in parts if p.aspect == "different"
                  and p.owner == "response paths./{className}={id}.get.responses · 200")
    assert get200.hints.clause == "12.1.1.1.3"            # the clause the rule came from
    assert get200.hints.terms == ["getMOIAttributes"]


def test_keys_keep_a_quoted_key_whole():
    assert _keys("callbacks.'$request.body#/x'.post") == ["callbacks", "$request.body#/x", "post"]


def _stub_verdicts(parts, verdict):
    from types import SimpleNamespace

    return [SimpleNamespace(part_id=p.id, answer=SimpleNamespace(verdict=verdict))
            for p in parts]


def test_rulesbank_views_count_every_rule_once():
    """The two views of the bank's final report (as the generated document's): every
    official rule and every bank rule in one row; only a rule equal to the official is
    "same" without the judge, every other row comes from the verdict of its part."""
    from openapi_analysis.judge.parts import rulesbank_views

    bank = json.loads(BANK.read_text(encoding="utf-8"))
    ev = evaluate_rules_bank(bank, OFFICIAL)
    parts = rulesbank_parts(ev, bank, "i20")
    views = {verdict: rulesbank_views(ev, bank, _stub_verdicts(parts, verdict), "i20")
             for verdict in ("error", "improvement", "equivalent", "useful")}
    assert views["error"] == {                       # 106 official rules, 122 bank rules
        "official": {"same": 61, "wrong": 25, "missing": 20},
        "generated": {"same": 61, "wrong": 30, "extra wrong": 31}}
    assert views["improvement"] == {"official": {"same": 61, "better": 45},
                                    "generated": {"same": 61, "better": 61}}
    assert views["equivalent"] == {
        "official": {"same": 61, "different but right": 45},
        "generated": {"same": 61, "different but right": 30, "extra useful": 31}}
    assert views["useful"]["generated"]["extra useful"] == 31   # only an extra is useful
    assert rulesbank_views(ev, bank, [], "i20") == {             # not judged: undecided
        "official": {"same": 61, "undecided": 45},
        "generated": {"same": 61, "undecided": 61}}
