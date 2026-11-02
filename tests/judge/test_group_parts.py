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
    text = v["text"].get("official", 0)
    assert sum(v["official"].values()) + header.get("official", 0) + text == len(flatten_parts(off))
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
    assert _outcome("generated", "extra", "improvement") == "better"
    assert _outcome("generated", "extra", "useful") == "extra useful"
    assert _outcome("generated", "extra", "error") == "extra wrong"
    assert _outcome("generated", "differing", "improvement") == "better"
    assert _outcome("generated", "differing", "uncertain") == "undecided"
    assert _outcome("generated", "differing", None) == "undecided"          # not judged


def test_text_only_the_official_has_is_counted_apart_and_not_scored():
    op = {"summary": "s", "responses": {"200": {"description": "OK"}}}
    off = {"openapi": "3.0.1", "paths": {"/a": {"get": op}}}
    gen = {"openapi": "3.0.1", "paths": {"/a": {"get": {"responses": op["responses"]}}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    v = views(a, parts, part_of, [_verdict(p, "equivalent") for p in parts])
    assert v["text"] == {"official": 1}
    assert v["official"]["different but right"] == 0 and v["official"]["same"] == 1


def test_a_field_only_the_official_has_that_is_not_text_stays_in_the_view():
    response = {"200": {"description": "OK"}}
    off = {"openapi": "3.0.1", "paths": {"/a": {"get": {"deprecated": True, "responses": response}}}}
    gen = {"openapi": "3.0.1", "paths": {"/a": {"get": {"responses": response}}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    v = views(a, parts, part_of, [_verdict(p, "error") for p in parts])
    assert v["official"]["missing"] == 1 and not v["text"]


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
    assert v["duplicates"] == {"generated": 2}           # already among them: not counted twice


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


def test_the_one_oneof_alternative_kept_at_the_root_is_compared_field_by_field():
    generic = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    nrm = {"anyOf": [{"$ref": "Ext.yaml#/components/schemas/A"},
                     {"$ref": "Ext.yaml#/components/schemas/B"}]}
    off = {"openapi": "3.0.1", "components": {"schemas": {"R": {"oneOf": [generic, nrm]}}}}
    gen = {"openapi": "3.0.1", "components": {"schemas": {"R": {
        **generic, "required": ["id", "attributes"]}}}}
    a = _aligned(off, gen)
    parts, part_of = group_parts(a, "g")
    root = "components.schemas.R"
    assert [(d.kind, d.location) for d in parts[0].differences] == [
        ("moved", f"{root}.type"), ("moved", f"{root}.properties"),
        ("absent", f"{root}.oneOf"), ("differing", f"{root}.required")]     # one line per field
    assert parts[0].differences[2].leaves == 2                      # only the alternative lost
    v = views(a, parts, part_of, [_verdict(parts[0], "equivalent")])
    assert sum(v["official"].values()) == len(flatten_parts(off["components"]))
    assert v["official"]["different but right"] == 5
    wrong = _verdict(parts[0], "equivalent")
    wrong.difference_verdicts = ["equivalent", "equivalent", "error", "error"]
    w = views(a, parts, part_of, [wrong])
    assert w["official"]["missing"] == 2 and w["official"]["wrong"] == 1   # required, by its own line
    assert w["generated"]["wrong"] == 1


def test_two_alternatives_sharing_keys_with_the_root_stay_a_plain_difference():
    alt = {"properties": {"a": {"type": "string"}}}
    off = {"openapi": "3.0.1", "components": {"schemas": {"R": {"oneOf": [alt, dict(alt)]}}}}
    gen = {"openapi": "3.0.1", "components": {"schemas": {"R": dict(alt)}}}
    assert not any(d.kind == "moved" for d in group_parts(_aligned(off, gen), "g")[0][0].differences)


def _across():
    """The same notification as a callback (official) and as an endpoint (generated)."""
    body = {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/N"}}}}
    off = {"openapi": "3.0.1", "paths": {"/x": {"put": {
        "responses": {"200": {"description": "OK"}},
        "callbacks": {"onN": {"{$request.body#/u}": {"post": {
            "requestBody": body,
            "responses": {"204": {"description": "ok"}, "default": {"description": "Error"}}}}}}}}}}
    gen = {"openapi": "3.0.1", "paths": {"/x": {"put": {"responses": {"200": {"description": "OK"}}}},
                                         "/sink": {"post": {
        "operationId": "notify", "requestBody": body,
        "responses": {"204": {"description": "No Content"}, "4XX": {"description": "Error"}}}}}}
    a = _aligned(off, gen)
    a.new_group(["official:paths./x.put.callbacks.onN"], ["generated:paths./sink.post"], "llm",
                primary=False)
    return a


def test_a_callback_and_an_endpoint_are_compared_field_by_field():
    a = _across()
    part = next(p for p in group_parts(a, "g")[0] if p.aspect.startswith("callback"))
    cb = "paths./x.put.callbacks.onN.{$request.body#/u}.post"
    found = {(d.kind, d.location) for d in part.differences}
    assert ("moved", "paths./sink.post") in found
    assert ("extra", "paths./sink.post.operationId") in found
    assert ("moved", "paths./sink.post.requestBody") in found
    assert ("differing", "paths./sink.post.responses.204.description") in found
    assert ("extra", "paths./sink.post.responses.4XX.description") in found
    quoted = cb.replace("{$request.body#/u}", "'{$request.body#/u}'")
    assert ("absent", f"{quoted}.responses.default.description") in found
    assert not any(d.kind == "absent" and d.location.endswith(".requestBody") for d in part.differences)


def test_a_callback_as_a_path_and_the_same_content_are_marked():
    part = next(p for p in group_parts(_across(), "g")[0] if p.aspect.startswith("callback"))
    by = {d.location: d.known for d in part.differences}
    assert by["paths./sink.post"] == "callback_to_path"
    assert by["paths./sink.post.requestBody"] == "same_content"
    assert by["paths./sink.post.responses"] == ""


def test_a_key_beside_a_ref_is_marked_and_a_groupers_tags_are_dropped():
    from openapi_analysis.judge.group_parts import _without_tags

    def doc(schema):
        return {"openapi": "3.0.1", "paths": {"/x": {"get": {"responses": {"200": {
            "description": "d", "content": {"application/json": {"schema": schema}}}}}}}}
    ref = {"$ref": "#/components/schemas/R"}
    part = group_parts(_aligned(doc(ref), doc({**ref, "type": "array"})), "g")[0][0]
    assert [d.known for d in part.differences] == ["beside_ref"]
    assert _without_tags("Same delivery (R12). B2 and B5 are copies.") == "Same delivery (R12)."


def test_a_required_naming_more_tells_what_to_ask_per_field():
    def doc(required):
        schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
        return {"openapi": "3.0.1", "components": {"schemas": {"N": {**schema, **required}}}}
    part = group_parts(_aligned(doc({"required": ["a"]}), doc({"required": ["a", "b"]})), "g")[0][0]
    assert "this requires b." in part.differences[0].hint
    extra = group_parts(_aligned(doc({}), doc({"required": ["a", "b"]})), "g")[0][0]
    assert "this requires a, b." in extra.differences[0].hint
    fewer = group_parts(_aligned(doc({"required": ["a", "b"]}), doc({"required": ["a"]})), "g")[0][0]
    assert fewer.differences[0].hint == ""


def test_nullable_missing_on_an_empty_schema_is_known():
    def doc(value):
        return {"openapi": "3.0.1", "components": {"schemas": {"N": {"properties": {"v": value}}}}}
    part = group_parts(_aligned(doc({"nullable": True}), doc({})), "g")[0][0]
    assert [d.known for d in part.differences] == ["empty_schema"]
    typed = group_parts(_aligned(doc({"type": "string", "nullable": True}), doc({"type": "string"})),
                        "g")[0][0]
    assert [d.known for d in typed.differences] == [""]            # a type restricts: judged


def test_a_field_written_as_a_ref_on_one_side_is_one_difference():
    def doc(path):
        return {"openapi": "3.0.1", "components": {"schemas": {"M": {"properties": {"path": path}}}}}
    part = group_parts(_aligned(doc({"$ref": "Ext.yaml#/components/schemas/Uri"}),
                                doc({"type": "string"})), "g")[0][0]
    assert [(d.kind, d.location) for d in part.differences] == [
        ("differing", "components.schemas.M.properties.path")]


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
