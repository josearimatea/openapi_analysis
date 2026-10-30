"""The generator's parts from the alignment, and the two views (judge/group_parts.py)
— on the deterministic alignment, no LLM: every field is counted once, a block is
compared by its own fields only, and each view adds up to its own document."""

import pytest
import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.judge.group_parts import _outcome, group_parts, views
from openapi_analysis.judge.parts import node_at
from openapi_analysis.openapi.alignment import Aligner
from openapi_analysis.openapi.comparison import flatten_parts
from openapi_analysis.schemas.judge import JudgeAnswer, Verdict
from openapi_analysis.services import evaluate_openapi

INPUTS = [("ProvMnS", "provmns_20260920_194130", "18.2.0"),
          ("ProvMnS", "provmns_20260828_232853", "18.2.0"),
          ("PerfMnS", "perfmns_20260823_031421", "18.1.0")]


def _load(service, name, version):
    gen = yaml.safe_load((ROOT / "data/inputs/generated" / service / f"{name}.yaml").read_text())
    off = yaml.safe_load(reference_yaml(service, version).read_text())
    return gen, off


def _aligned(off, gen):
    a = Aligner(off, gen)
    a.deterministic()
    return a


def _verdict(part, verdict):
    answer = JudgeAnswer(why_different="-", verdict=verdict, spec_3gpp="", openapi="",
                         clearer="same", clearer_why="-", citations=[])
    return Verdict(part_id=part.id, evaluation="generator", input="g", owner=part.owner,
                   aspect=part.aspect, summary=part.summary, answer=answer, evidence=[],
                   decided_by="llm", differences=part.differences,
                   difference_verdicts=[verdict] * len(part.differences))


def test_a_document_equal_to_the_official_has_no_part():
    off = yaml.safe_load(reference_yaml("ProvMnS", "18.2.0").read_text())
    parts, _ = group_parts(_aligned(off, off), "x")
    assert parts == []


@pytest.mark.parametrize(("service", "name", "version", "n_parts"), [
    (*INPUTS[0], 66), (*INPUTS[1], 64), (*INPUTS[2], 8)])
def test_parts_are_pinned_and_unique(service, name, version, n_parts):
    gen, off = _load(service, name, version)
    parts, _ = group_parts(_aligned(off, gen), name)
    assert len(parts) == n_parts
    assert len({p.id for p in parts}) == len(parts)


@pytest.mark.parametrize(("service", "name", "version"), INPUTS)
def test_each_view_adds_up_to_its_own_document(service, name, version):
    """Every field of each document is counted once, on its own side: the official view
    sums to the official's fields, the generated view to the generated's."""
    gen, off = _load(service, name, version)
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, name)
    v = views(a, parts, part_of, [_verdict(p, "equivalent") for p in parts])
    header = v["header"]
    assert sum(v["official"].values()) + header.get("official", 0) == len(flatten_parts(off))
    assert sum(v["generated"].values()) + header.get("generated", 0) == len(flatten_parts(gen))
    assert v["official"]["undecided"] == v["generated"]["undecided"] == 0


@pytest.mark.parametrize(("service", "name", "version"), INPUTS)
def test_every_focus_is_found_in_the_context_of_some_side(service, name, version):
    gen, off = _load(service, name, version)
    for p in group_parts(_aligned(off, gen), name)[0]:
        for loc in p.focus:
            assert node_at(p.official, loc) is not None or node_at(p.generated, loc) is not None


def test_an_operation_is_compared_by_its_own_fields_only():
    """Its parameters, bodies, responses and callbacks are blocks of their own, judged
    in their own parts — never a second time in the operation's."""
    gen, off = _load(*INPUTS[1])
    parts, _ = group_parts(_aligned(off, gen), "g")
    get = next(p for p in parts if p.owner == "GET /{className}={id}")
    assert [(d.kind, d.location.rsplit(".", 1)[1]) for d in get.differences] == [
        ("absent", "summary"), ("absent", "description"), ("extra", "operationId")]
    response = next(p for p in parts if p.owner.startswith("response 200 — GET"))
    assert list(response.official) == ["paths./{className}={id}.get"]    # the whole GET


def test_a_parameter_at_another_level_is_one_part_with_its_moves():
    gen, off = _load(*INPUTS[1])
    parts, _ = group_parts(_aligned(off, gen), "g")
    p = next(p for p in parts if p.owner.startswith("path id ("))
    assert p.aspect == "parameter — grouped by key"              # none at another's place
    assert {d.kind for d in p.differences} == {"moved"}
    assert len(p.differences) == 4                                # one per operation


def test_every_layer2_issue_lands_in_a_part():
    gen, off = _load(*INPUTS[0])
    report = evaluate_openapi(gen, off)
    issues = [f"{i.location}: {i.message}" for i in report.validity_generated.issues]
    parts, _ = group_parts(_aligned(off, gen), "g", issues)
    assert len({i for p in parts for i in p.invalid_issues}) == len(issues) == 18


def test_a_field_takes_the_outcome_of_its_difference():
    assert _outcome("official", None, None) == "same"
    assert _outcome("official", "absent", "error") == "missing"
    assert _outcome("official", "absent", "equivalent") == "different but right"
    assert _outcome("official", "moved", "error") == "wrong"
    assert _outcome("generated", "extra", "improvement") == "extra useful"
    assert _outcome("generated", "extra", "error") == "extra wrong"
    assert _outcome("generated", "differing", "improvement") == "better"
    assert _outcome("generated", "differing", "uncertain") == "undecided"
    assert _outcome("generated", "differing", None) == "undecided"          # not judged
