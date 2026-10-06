"""Unit tests for the document comparison — no data files.

Ported from openapi_generator/tests/eval/test_comparison.py, plus the changes made
here (parameters by name, enum/required as sets, x-* as metadata).
"""

from openapi_analysis.openapi.comparison import classify, compare_documents, flatten


def _doc(schemas=None, paths=None, **top):
    return {
        "openapi": "3.0.1",
        "info": {"title": "t", "version": "1.0"},
        "paths": paths if paths is not None else {"/x": {"post": {"responses": {"204": {}}}}},
        "components": {"schemas": schemas or {}},
        **top,
    }


def test_flatten_keeps_composition_position():
    leaves = flatten({"allOf": [{"$ref": "X"}, {"type": "object"}]})
    assert leaves == {"allOf[0].$ref": "X", "allOf[1].type": "object"}


def test_classify_splits_the_three_groups():
    assert classify("components.schemas.Foo.type") == "contract"
    assert classify("paths./x.post.responses.204.description") == "prose"
    assert classify("info.version") == "metadata"
    assert classify("servers[0].url") == "metadata"
    assert classify("x-ai-generation.model") == "metadata"
    assert classify("components.schemas.Foo.properties.bar.description") == "prose"


def test_identical_documents_score_perfectly():
    doc = _doc({"Foo": {"type": "string", "enum": ["A"]}})
    result = compare_documents(doc, doc)
    assert result.contract.absent == [] and result.contract.differing == []
    assert result.contract.ratio == 1.0
    assert result.schemas_missing == [] and result.schemas_extra == []


def test_missing_schema_is_reported_as_absent_contract():
    official = _doc({"Foo": {"type": "string"}, "Bar": {"type": "integer"}})
    result = compare_documents(_doc({"Foo": {"type": "string"}}), official)
    assert result.schemas_missing == ["Bar"]
    assert "components.schemas.Bar.type" in result.contract.absent


def test_wrong_type_is_reported_as_differing():
    result = compare_documents(_doc({"Foo": {"type": "object"}}), _doc({"Foo": {"type": "string"}}))
    assert [d.path for d in result.contract.differing] == ["components.schemas.Foo.type"]


def test_prose_difference_does_not_touch_the_contract():
    official = _doc(paths={"/x": {"post": {"description": "Send it", "responses": {"204": {}}}}})
    generated = _doc(paths={"/x": {"post": {"description": "Sends it.", "responses": {"204": {}}}}})
    result = compare_documents(generated, official)
    assert result.contract.differing == [] and result.contract.absent == []
    assert len(result.prose.differing) == 1


def test_missing_servers_and_extensions_land_in_metadata():
    result = compare_documents(_doc(**{"x-ai-generation": {"model": "m"}}),
                               _doc(servers=[{"url": "{root}"}]))
    assert result.contract.absent == [] and result.contract.extra == []
    assert "servers[0].url" in result.metadata.absent
    assert "x-ai-generation.model" in result.metadata.extra


def test_extra_contract_leaf_is_listed_not_counted_as_error():
    official = _doc({"Foo": {"type": "object", "properties": {"a": {"type": "string"}}}})
    generated = _doc({"Foo": {"type": "object", "properties": {"a": {"type": "string"}},
                              "required": ["a"]}})
    result = compare_documents(generated, official)
    assert result.contract.absent == [] and result.contract.differing == []
    assert result.contract.extra == ["components.schemas.Foo.required"]


def test_ref_siblings_are_flagged():
    generated = _doc({"Foo": {"properties": {
        "a": {"$ref": "#/components/schemas/Bar", "description": "dead text"},
        "b": {"$ref": "#/components/schemas/Bar"},
    }}})
    result = compare_documents(generated, _doc())
    assert result.refs_total == 2
    assert result.refs_with_siblings == ["components.schemas.Foo.properties.a"]


def test_composition_member_order_is_significant():
    official = _doc({"Foo": {"allOf": [{"$ref": "X"}, {"type": "object"}]}})
    generated = _doc({"Foo": {"allOf": [{"type": "object"}, {"$ref": "X"}]}})
    result = compare_documents(generated, official)
    assert result.contract.absent or result.contract.differing


def test_parameters_are_matched_by_name_not_position():
    p = [{"name": "a", "in": "query", "schema": {"type": "string"}},
         {"name": "b", "in": "query", "schema": {"type": "integer"}}]
    official = _doc(paths={"/x": {"get": {"parameters": p, "responses": {"200": {}}}}})
    generated = _doc(paths={"/x": {"get": {"parameters": p[::-1], "responses": {"200": {}}}}})
    result = compare_documents(generated, official)
    assert result.contract.differing == [] and result.contract.absent == []


def test_enum_and_required_are_sets():
    official = _doc({"E": {"type": "string", "enum": ["A", "B", "C"]}})
    assert compare_documents(_doc({"E": {"type": "string", "enum": ["C", "A", "B"]}}),
                             official).contract.differing == []
    typo = compare_documents(_doc({"E": {"type": "string", "enum": ["A", "B", "Cc"]}}), official)
    assert [d.path for d in typo.contract.differing] == ["components.schemas.E.enum"]


def test_keys_with_dots_stay_one_segment():
    """A media type holds dots; it must not be split into fake path segments."""
    media = "application/vnd.3gpp.object-tree-flat+json"
    official = _doc(paths={"/x": {"get": {"responses": {"200": {"content": {
        media: {"schema": {"type": "array"}}}}}}}})
    result = compare_documents(_doc(paths={"/x": {"get": {"responses": {"200": {}}}}}),
                               official)
    detail = [d for d in result.details if d.kind == "absent"]
    assert [(d.owner, d.element) for d in detail] == [
        ("GET /x", f"responses.200.content.'{media}'")]


def test_both_documents_are_validated():
    ok = {"/x": {"post": {"responses": {"204": {"description": "done"}}}}}
    generated = _doc(paths={**ok, "/y": {"notifyX": {"post": {}}}})
    result = compare_documents(generated, _doc(paths=ok))
    assert not result.validity_generated.valid
    assert result.validity_official.valid


def test_schema_outside_components_schemas_is_misplaced():
    official = _doc({"A": {"type": "object", "properties": {"p": {"type": "string"}}}})
    generated = _doc()
    generated["components"]["A"] = {"type": "object", "properties": {"p": {"type": "string"}}}
    s = next(s for s in compare_documents(generated, official).schemas if s.name == "A")
    assert s.status == "misplaced" and s.found_at == "components.A"
    assert "2/2" in s.note


def test_operation_parameter_declared_on_the_path_is_flagged_322():
    param = {"name": "q", "in": "query", "schema": {"type": "string"}}
    official = _doc(paths={"/x": {"get": {"parameters": [param], "responses": {}},
                                  "put": {"responses": {}}}})
    generated = _doc(paths={"/x": {"parameters": [param], "get": {"responses": {}},
                                   "put": {"responses": {}}}})
    ops = {o.operation: o for o in compare_documents(generated, official).operations}
    assert ops["GET /x"].params_at_path_level == ["query q"]
    assert ops["GET /x"].params_missing == []           # still offered, via the path item
    assert ops["PUT /x"].params_extra == ["query q"]    # … and to every other method


def test_details_collapse_the_leaves_of_one_parameter():
    param = {"name": "q", "in": "query", "required": False, "schema": {"type": "string"}}
    official = _doc(paths={"/x": {"get": {"parameters": [param], "responses": {}}}})
    generated = _doc(paths={"/x": {"get": {"responses": {}}}})
    detail = [d for d in compare_documents(generated, official).details if d.kind == "absent"]
    assert [(d.element, d.leaves) for d in detail] == [("parameters[in=query,name=q]", 4)]


def test_operations_missing_and_extra():
    official = _doc(paths={"/x": {"get": {"responses": {}}, "put": {"responses": {}}}})
    generated = _doc(paths={"/x": {"get": {"responses": {}}}, "/y": {"post": {"responses": {}}}})
    result = compare_documents(generated, official)
    assert result.operations_missing == ["PUT /x"]
    assert result.operations_extra == ["POST /y"]
