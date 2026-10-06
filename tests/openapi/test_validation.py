"""Layer 2 — OpenAPI 3.0 validity (syntax only). Small hand-made documents."""

import yaml

from openapi_analysis.config.paths import REFERENCE_DIR
from openapi_analysis.openapi.validation import validate_document


def _doc(paths=None, schemas=None):
    return {"openapi": "3.0.1", "info": {"title": "t", "version": "1"},
            "paths": paths if paths is not None else {"/x": {"get": {"responses": {
                "200": {"description": "ok"}}}}},
            "components": {"schemas": schemas or {}}}


def test_a_valid_document_passes_every_check():
    v = validate_document(_doc())
    assert v.valid and v.issues == []
    assert v.checks_run == ["schema", "local_ref", "semantics"]


def test_a_key_openapi_does_not_allow_is_a_schema_issue():
    doc = _doc(paths={"/x": {"get": {"responses": {"200": {"description": "ok"}}},
                             "notifyX": {"post": {}}}})
    v = validate_document(doc)
    assert not v.valid
    assert [(i.check, i.location) for i in v.issues] == [("schema", "paths./x")]
    assert "notifyX" in v.issues[0].message


def test_a_path_must_start_with_a_slash():
    doc = _doc()
    doc["paths"]["components"] = {}
    assert any(i.location == "paths" and "components" in i.message
               for i in validate_document(doc).issues)


def test_every_broken_local_ref_is_listed():
    doc = _doc(schemas={"A": {"properties": {"p": {"$ref": "#/components/schemas/Gone"},
                                             "q": {"$ref": "#/components/schemas/Lost"}}}})
    v = validate_document(doc)
    assert [(i.check, i.location) for i in v.issues] == [
        ("local_ref", "components.schemas.A.properties.p"),
        ("local_ref", "components.schemas.A.properties.q"),
    ]
    assert "semantics" not in v.checks_run       # not run on a document with broken refs


def test_external_refs_are_not_opened():
    """A $ref to another 3GPP file must not abort validation (the file is not here)."""
    doc = _doc(schemas={"A": {"properties": {
        "p": {"$ref": "TS28623_ComDefs.yaml#/components/schemas/Uri"}}}})
    assert validate_document(doc).valid


def test_response_codes_are_keys_not_list_indexes():
    doc = _doc(paths={"/x": {"get": {"responses": {"200": {
        "description": "ok",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Gone"}}}}}}}})
    [issue] = validate_document(doc).issues
    assert issue.location == "paths./x.get.responses.200.content.application/json.schema"


def test_every_official_yaml_is_valid():
    for path in sorted(REFERENCE_DIR.glob("*/*.yaml")):
        v = validate_document(yaml.safe_load(path.read_text(encoding="utf-8")))
        assert v.valid, f"{path.name}: {v.issues[:3]}"
