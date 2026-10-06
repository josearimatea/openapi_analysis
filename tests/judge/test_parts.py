"""The parts the judge receives (docs/JUDGE_PLAN.md §3) — deterministic, no LLM.

Pinned on the real inputs: what is equal never becomes a part, ids are unique (the
verdict cache is keyed on them), each callback is its own part, every layer-2 issue
lands in a part — and NO difference is left out: every leaf that differs between the
two documents, contract, metadata or prose, is in the focus of exactly one part,
while the part carries its whole owner as context.
"""

import json
from collections import Counter

import pytest
import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.judge.parts import _keys, diff_documents, generator_parts, rulesbank_parts
from openapi_analysis.openapi.comparison import flatten_parts, join
from openapi_analysis.services import evaluate_openapi, evaluate_rules_bank

OFFICIAL = yaml.safe_load(reference_yaml("ProvMnS", "18.2.0").read_text(encoding="utf-8"))
GENERATED = ROOT / "data/inputs/generated"
BANK = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20260915_214107.json"
INPUTS = [("ProvMnS", "provmns_20260920_194130", "18.2.0"),
          ("ProvMnS", "provmns_20260828_232853", "18.2.0"),
          ("PerfMnS", "perfmns_20260823_031421", "18.1.0")]


def _load(service, name, version):
    gen = yaml.safe_load((GENERATED / service / f"{name}.yaml").read_text(encoding="utf-8"))
    off = yaml.safe_load(reference_yaml(service, version).read_text(encoding="utf-8"))
    return gen, off


def _generator(name, service="ProvMnS", version="18.2.0"):
    gen, off = _load(service, name, version)
    report = evaluate_openapi(gen, off)
    return generator_parts(report, gen, off, name), report


@pytest.fixture(scope="module")
def latest():
    return _generator("provmns_20260920_194130")


def test_a_document_equal_to_the_official_has_no_part():
    assert generator_parts(evaluate_openapi(OFFICIAL, OFFICIAL), OFFICIAL, OFFICIAL, "x") == []


@pytest.mark.parametrize("service, name, version", INPUTS)
def test_no_differing_leaf_is_left_out(service, name, version):
    """Every leaf present on one side only, or with another value, is under exactly one
    difference of exactly one part — the leaves as layer 1 counts them."""
    gen, off = _load(service, name, version)
    parts = generator_parts(evaluate_openapi(gen, off), gen, off, name)
    o, g = flatten_parts(off), flatten_parts(gen)
    differing = [join(p) for p in {*o, *g} if o.get(p, o) != g.get(p, g)]
    located = [d.location for p in parts for d in p.differences]
    assert len(located) == len(set(located))                  # no difference in two parts

    def under(leaf, loc):
        return leaf == loc or leaf.startswith((loc + ".", loc + "["))

    uncovered = [leaf for leaf in differing if not any(under(leaf, loc) for loc in located)]
    assert uncovered == []
    assert all(any(under(leaf, d.location) for leaf in differing) or d.kind == "differing"
               for p in parts for d in p.differences)          # nothing invented


@pytest.mark.parametrize("name, total, by_aspect", [
    ("provmns_20260920_194130", 49,
     {"block": 1, "callback": 9, "definition": 11, "extra": 5, "metadata": 3, "operation": 4,
      "parameters": 2, "path": 1, "placement": 7, "request_body": 1, "responses": 4,
      "unexpected_keys": 1}),
    ("provmns_20260828_232853", 41,
     {"callback": 5, "definition": 10, "extra": 4, "metadata": 2, "missing": 2, "operation": 4,
      "parameters": 5, "path": 4, "request_body": 1, "responses": 4}),
])
def test_generator_parts_per_aspect(name, total, by_aspect):
    parts, _ = _generator(name)
    assert len(parts) == total
    assert dict(sorted(Counter(p.aspect.split()[0] for p in parts).items())) == by_aspect


def test_ids_are_unique(latest):
    parts, _ = latest
    assert len({p.id for p in parts}) == len(parts)


def test_an_operation_part_gets_the_whole_operation_and_its_exact_differences(latest):
    parts, _ = latest
    p = next(p for p in parts if p.owner == "PATCH /{className}={id}" and p.aspect == "responses")
    loc = "paths./{className}={id}.patch"
    assert list(p.official) == [loc] and list(p.generated) == [loc]
    assert {"summary", "requestBody", "responses"} <= set(p.official[loc])   # not just responses
    assert p.focus == [f"{loc}.responses"]
    assert [(d.kind, d.location.rsplit(".", 1)[1]) for d in p.differences] == [
        ("absent", "200"), ("absent", "204"), ("absent", "default"),
        ("extra", "400"), ("extra", "4XX"), ("extra", "5XX")]
    assert {"200", "204", "default", "4XX", "5XX"} <= set(p.diff_terms)
    assert (p.hints.path, p.hints.method) == ("/{className}={id}", "patch")


def test_an_operation_parameters_part_also_shows_the_path_level_ones(latest):
    parts, _ = latest
    p = next(p for p in parts if p.owner == "GET /{className}={id}" and p.aspect == "parameters")
    assert "paths./{className}={id}.parameters" in p.generated   # where §3.22 put them


def test_each_callback_is_its_own_part_with_the_operation_that_registers_it(latest):
    parts, _ = latest
    callbacks = {p.aspect: p for p in parts if p.owner == "PUT /{className}={id}"
                 and p.aspect.startswith("callback ")}
    assert {"callback notifyMOICreation", "callback notifyEvent",
            "callback $request.body#/notificationTarget"} <= set(callbacks)
    p = callbacks["callback notifyEvent"]
    assert p.official["registered by"].startswith("PUT /{className}={id}")
    assert list(p.official)[1] == "paths./{className}={id}.put.callbacks.notifyEvent"
    assert "responses" not in p.official                       # not the whole PUT


def test_metadata_and_blocks_outside_their_place_are_parts(latest):
    parts, _ = latest
    owners = {(p.owner, p.aspect) for p in parts}
    assert {("DOCUMENT info", "metadata"), ("DOCUMENT servers", "metadata"),
            ("COMPONENTS AttributeValueChangeSet", "block")} <= owners


def test_a_copy_of_a_schema_outside_components_schemas_is_its_placement(latest):
    parts, _ = latest
    p = next(p for p in parts if p.owner == "SCHEMA Resource" and p.aspect == "placement")
    assert p.focus == ["components.Resource"]
    assert set(p.generated) == {"components.schemas.Resource", "components.Resource"}


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
        "different": 18, "duplicate": 2, "missing": 32, "extra": 39}
    assert len({p.id for p in parts}) == len(parts)
    get200 = next(p for p in parts if p.aspect == "different"
                  and p.owner == "response paths./{className}={id}.get.responses · 200")
    assert get200.hints.clause == "12.1.1.1.3"            # the clause the rule came from
    assert get200.hints.terms == ["getMOIAttributes"]


def test_keys_keep_a_quoted_key_whole():
    assert _keys("callbacks.'$request.body#/x'.post") == ["callbacks", "$request.body#/x", "post"]


@pytest.mark.parametrize("service, name, version", INPUTS)
def test_every_focus_is_found_in_the_context_of_some_side(service, name, version):
    """What the report shows as 'analysed' is read back out of the part's context."""
    from openapi_analysis.judge.parts import node_at

    gen, off = _load(service, name, version)
    for p in generator_parts(evaluate_openapi(gen, off), gen, off, name):
        for loc in p.focus:
            assert node_at(p.official, loc) is not None or node_at(p.generated, loc) is not None, \
                (p.owner, p.aspect, loc)


@pytest.mark.parametrize("service, name, version", INPUTS)
def test_the_lines_of_the_differences_add_up_to_the_lines_that_differ(service, name, version):
    """The report's table is in leaves: equal + every part's difference leaves must be
    exactly every leaf of either document, region by region."""
    from openapi_analysis.judge.parts import leaf_census, region

    gen, off = _load(service, name, version)
    report = evaluate_openapi(gen, off)
    census = leaf_census(report, gen, off)
    o, g = flatten_parts(off), flatten_parts(gen)
    assert sum(c["total"] for c in census.values()) == len({*o, *g})
    differing = {r: 0 for r in census}
    for p in generator_parts(report, gen, off, name):
        differing[region(p.owner)] += sum(d.leaves for d in p.differences)
    assert {r: c["total"] - c["equal"] for r, c in census.items()} == differing
