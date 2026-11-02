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
          ("ProvMnS", "provmns_20260828_232853", "17.5.0"),
          ("PerfMnS", "perfmns_20260823_031421", "17.1.0")]


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
    (*INPUTS[0], 66), (*INPUTS[1], 61), (*INPUTS[2], 8)])
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


def test_a_second_declaration_is_one_duplicate_judged_whole():
    """The same operation declared twice in the generated document (same operationId):
    the one at the official's place is compared field by field; the other is ONE
    duplicate difference, and all its fields take its verdict (error: extra wrong)."""
    op = {"operationId": "getThing", "responses": {"200": {"description": "OK"}}}
    off = {"openapi": "3.0.1", "paths": {"/a": {"get": op}}}
    gen = {"openapi": "3.0.1", "paths": {"/a": {"get": dict(op, summary="s")},
                                         "/copy/a": {"get": dict(op)}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    part = next(p for p in parts if p.owner.startswith("GET /a"))
    kinds = [(d.kind, d.location) for d in part.differences]
    assert ("duplicate", "paths./copy/a.get") in kinds
    assert ("extra", "paths./a.get.summary") in kinds
    assert not any(loc.startswith("paths./copy/a.get.") for _, loc in kinds)   # judged whole
    assert part.headers["official"] == {"openapi": "3.0.1"}
    v = views(a, parts, part_of, [_verdict(p, "error") for p in parts])
    assert v["generated"]["extra wrong"] == 3            # operationId, 200.description, summary


def _disputing(part, *locations):
    v = _verdict(part, "equivalent")
    v.answer.grouping_wrong, v.answer.wrongly_grouped = True, list(locations)
    return v


def test_a_block_the_judge_disputes_is_taken_out_and_judged_on_its_own():
    from openapi_analysis.judge.group_parts import regroup

    op = {"operationId": "getThing", "responses": {"200": {"description": "OK"}}}
    off = {"openapi": "3.0.1", "paths": {"/a": {"get": op}}}
    gen = {"openapi": "3.0.1", "paths": {"/a": {"get": dict(op, summary="s")},
                                         "/copy/a": {"get": dict(op)}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    part = next(p for p in parts if p.owner.startswith("GET /a"))
    new = regroup(a, parts, part_of, [_disputing(part, "paths./copy/a.get")], "g")
    assert new is not None
    new_parts, _, taken = new
    assert taken[0].startswith("paths./copy/a.get: taken out of GET /a")
    extra = next(p for p in new_parts if p.owner.startswith("GET /copy/a"))
    assert extra.aspect == "operation — extra in the generated"
    again = next(p for p in new_parts if p.owner.startswith("GET /a"))
    assert not any(d.kind == "duplicate" for d in again.differences)


def test_the_primary_pair_is_never_taken_out_and_a_one_sided_group_dissolves():
    from openapi_analysis.judge.group_parts import regroup

    gen, off = _load(*INPUTS[1])
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    get = next(p for p in parts if p.owner == "GET /{className}={id}")
    assert regroup(a, parts, part_of, [_disputing(get, "paths./{className}={id}.get")],
                   "g") is None                               # the primary pair stays
    param = next(p for p in parts if p.owner.startswith("path id ("))
    new_parts, _, taken = regroup(a, parts, part_of, [_disputing(
        param, "paths./{className}={id}.parameters[in=path,name=id]")], "g")
    assert len(taken) == 1                                    # the official one taken out:
    assert any(p.aspect == "parameter — missing in the generated" and "name=id" in p.focus[0]
               for p in new_parts)                            # the group dissolved


@pytest.mark.parametrize(("service", "name", "version"), INPUTS)
def test_nothing_of_a_real_part_is_cut_on_the_way_to_the_judge(service, name, version):
    """Every context, value, header and evidence text reaches the message whole."""
    from openapi_analysis.judge.prompts import _dump, _inline, user_message
    from openapi_analysis.schemas.judge import Evidence

    gen, off = _load(service, name, version)
    a = _aligned(off, gen)
    evidence = [Evidence(id="S1", source="spec", collection="c", query="q", text="x" * 9000)]
    for p in group_parts(a, name)[0]:
        message = user_message(p, evidence)
        assert "x" * 9000 in message
        assert _dump(p.official) in message and _dump(p.generated) in message
        for d in p.differences:
            if d.kind == "differing":
                assert _inline(d.official) in message and _inline(d.generated) in message
        for side, doc in (("official", off), ("generated", gen)):
            assert set(p.headers[side]) == {k for k in doc if not k.startswith("x-")
                                            and k not in ("paths", "components")}


def test_the_generators_run_record_is_judged_but_not_shown_in_every_part():
    gen, off = _load(*INPUTS[0])
    assert "x-ai-generation" in gen
    parts, _ = group_parts(_aligned(off, gen), "g")
    assert all("x-ai-generation" not in p.headers["generated"] for p in parts)
    assert any(p.owner == "x-ai-generation" for p in parts)              # its own part


EXTERNAL = "TS28623_ComDefs.yaml#/components/schemas/ErrorResponse"


def _responses(ref):
    return {"get": {"responses": {"200": {"description": "d", "content": {"application/json": {
        "schema": {"$ref": ref}}}}}}}


def test_a_local_schema_named_as_an_official_external_definition_is_linked_to_it():
    from openapi_analysis.judge.prompts import user_message

    local = "#/components/schemas/ErrorResponse"
    off = {"openapi": "3.0.1", "paths": {"/x": _responses(EXTERNAL)}}
    gen = {"openapi": "3.0.1", "paths": {"/x": _responses(local)},
           "components": {"schemas": {"ErrorResponse": {"type": "object"},
                                      "Other": {"type": "object"}}}}
    parts, _ = group_parts(_aligned(off, gen), "g")
    stub = next(p for p in parts if p.owner == "ErrorResponse")     # defined here, cites nothing
    assert stub.replaced == {local: [EXTERNAL]}
    assert EXTERNAL in stub.hints.external_refs                     # so its definition is searched
    assert f"- {local} (generated) — the official document uses: {EXTERNAL}" in user_message(
        stub, [])
    user = next(p for p in parts if p.replaced and p.owner != "ErrorResponse")   # cites it
    assert user.replaced == {local: [EXTERNAL]}
    other = next(p for p in parts if p.owner == "Other")            # another name: no link
    assert other.replaced == {}
    assert "LOCAL SCHEMAS IN PLACE" not in user_message(other, [])


def test_a_name_the_official_defines_itself_replaces_nothing():
    local = "#/components/schemas/ErrorResponse"
    schemas = {"schemas": {"ErrorResponse": {"type": "object"}}}
    off = {"openapi": "3.0.1", "paths": {"/x": _responses(EXTERNAL), "/y": _responses(local)},
           "components": schemas}
    gen = {"openapi": "3.0.1", "paths": {"/x": _responses(local), "/y": _responses(local)},
           "components": {"schemas": {"ErrorResponse": {"type": "string"}}}}
    parts, _ = group_parts(_aligned(off, gen), "g")
    assert parts and all(p.replaced == {} for p in parts)


def test_an_allof_member_written_at_the_root_is_compared_field_by_field():
    """One wrong $ref among equal properties: only that field is wrong, on both views."""
    header = {"$ref": "Ext.yaml#/components/schemas/Header"}
    props = {"text": {"type": "string"}, "list": {"$ref": "Ext.yaml#/components/schemas/L"}}
    off = {"openapi": "3.0.1", "components": {"schemas": {"N": {
        "allOf": [header, {"type": "object", "properties": props, "required": ["text"]}]}}}}
    gen = {"openapi": "3.0.1", "components": {"schemas": {"N": {
        "allOf": [header], "type": "object", "required": ["text"], "properties": {
            "text": {"type": "string"}, "list": {"$ref": "#/components/schemas/L"}}}}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    part = parts[0]
    root = "components.schemas.N"
    assert [(d.kind, d.location) for d in part.differences] == [
        ("moved", f"{root}.type"), ("moved", f"{root}.properties"),
        ("moved", f"{root}.required"), ("differing", f"{root}.properties.list.$ref")]
    wrong = part.differences[-1]
    assert wrong.official_location == f"{root}.allOf[1].properties.list.$ref"
    verdict = _verdict(part, "equivalent")
    verdict.difference_verdicts = ["equivalent"] * 3 + ["error"]
    v = views(a, parts, part_of, [verdict])
    for side in ("official", "generated"):
        assert v[side]["wrong"] == 1 and v[side]["different but right"] == 3   # type, required, text
        assert v[side]["same"] == 1                                            # the allOf header
    back = group_parts(_aligned(gen, off), "g")[0][0]            # the other way round
    assert ("differing", f"{root}.allOf[1].properties.list.$ref") in [
        (d.kind, d.location) for d in back.differences]


@pytest.mark.parametrize(("member", "root"), [
    ({"$ref": "#/components/schemas/M"}, {"properties": {"a": {"type": "string"}}}),   # a $ref
    ({"type": "object"}, {"type": "object"}),                                 # type proves nothing
    ({"properties": {"a": {"type": "string"}}}, {"required": ["a"]}),                  # no key shared
])
def test_what_is_not_a_flattened_member_stays_a_plain_difference(member, root):
    off = {"openapi": "3.0.1", "components": {"schemas": {"N": {"allOf": [member]}}}}
    gen = {"openapi": "3.0.1", "components": {"schemas": {"N": root}}}
    part = group_parts(_aligned(off, gen), "g")[0][0]
    assert not any(d.kind == "moved" for d in part.differences)


def test_real_flattened_notifications_differ_only_where_they_really_differ():
    gen, off = _load(*INPUTS[1])
    parts, _ = group_parts(_aligned(off, gen), "g")
    p = next(x for x in parts if x.owner == "NotifyMoiCreation")
    root = "components.schemas.NotifyMoiCreation"
    assert [(d.kind, d.location) for d in p.differences] == [
        ("moved", f"{root}.type"), ("moved", f"{root}.properties"),
        ("differing", f"{root}.properties.attributeList.$ref")]


def test_a_part_carries_what_its_local_refs_point_to():
    from openapi_analysis.judge.prompts import user_message

    gen, off = _load(*INPUTS[1])
    parts, _ = group_parts(_aligned(off, gen), "g")
    p = next(x for x in parts if x.owner == "response 200 — PUT /{className}={id}")
    cited = p.cited["generated"]
    assert cited and all(ref.startswith("#/") for ref in cited)
    assert "CITED SCHEMAS" in user_message(p, [])
    a = _aligned({"openapi": "3.0.1", "paths": {}},
                 {"openapi": "3.0.1", "paths": {"/x": {"get": {"responses": {"200": {
                     "description": "d", "content": {"application/json": {"schema": {
                         "$ref": "#/components/schemas/Nowhere"}}}}}}}}})
    leftover = next(x for x in group_parts(a, "g")[0] if x.owner.startswith("GET /x"))
    assert leftover.cited["generated"] == {"#/components/schemas/Nowhere":
                                           "(not defined in this document)"}
