"""The deterministic alignment (steps 1–4, docs/ALIGNMENT_PLAN.md): it groups only what
is exact, never loses or double-counts a value, and leaves the rest to the LLM."""

import collections

import pytest
import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.openapi.alignment import align
from openapi_analysis.openapi.comparison import flatten_parts


def _doc(paths=None, schemas=None, **extra):
    out = {"openapi": "3.0.1", "info": {"title": "t", "version": "1"},
           "paths": paths or {}, **extra}
    if schemas is not None:
        out["components"] = {"schemas": schemas}
    return out


def _op(**kw):
    return {"responses": {"200": {"description": "OK"}}, **kw}


def _param(name, where="path", **kw):
    return {"name": name, "in": where, "required": where == "path",
            "schema": {"type": "string"}, **kw}


def _groups(r):
    """{official locations: generated locations} of every group, with its steps."""
    return {(tuple(sorted(r.blocks[b].location for b in g.official)),
             tuple(sorted(r.blocks[b].location for b in g.generated))): set(g.how.values())
            for g in r.groups}


def _left(r, side):
    return {r.blocks[b].location for b in r.leftovers if r.blocks[b].side == side}


def _owned_add_up(r, official, generated):
    owned = collections.Counter()
    for bid, n in r.owned.items():
        assert "(no block)" not in bid
        owned[bid.split(":")[0]] += n
    assert owned["official"] == len(flatten_parts(official))
    assert owned["generated"] == len(flatten_parts(generated))


# ── exact correspondences ────────────────────────────────────────────────────

def test_a_path_parameter_and_its_copies_on_each_operation_are_one_group():
    """R5: a path-level parameter applies to every operation — the same parameter."""
    official = _doc({"/x/{id}": {"parameters": [_param("id")],
                                 "get": _op(), "delete": _op()}})
    generated = _doc({"/x/{id}": {"get": _op(parameters=[_param("id")]),
                                  "delete": _op(parameters=[_param("id")])}})
    r = align(official, generated)
    assert _groups(r)[(("paths./x/{id}.parameters[in=path,name=id]",),
                       ("paths./x/{id}.delete.parameters[in=path,name=id]",
                        "paths./x/{id}.get.parameters[in=path,name=id]"))] == {"key"}
    assert not r.leftovers
    _owned_add_up(r, official, generated)


def test_a_query_parameter_moved_to_the_path_item_is_grouped_with_the_level_change():
    """§3.22: the generator put the operation's query parameter on the path item."""
    official = _doc({"/x": {"get": _op(parameters=[_param("scope", "query")])}})
    generated = _doc({"/x": {"parameters": [_param("scope", "query")], "get": _op()}})
    r = align(official, generated)
    assert _groups(r)[(("paths./x.get.parameters[in=query,name=scope]",),
                       ("paths./x.parameters[in=query,name=scope]",))] == {"key"}


def test_a_parameter_by_ref_is_the_parameter_it_points_to():
    """R14 / R4: a local $ref is resolved; header names are case insensitive."""
    official = _doc({"/x": {"get": _op(parameters=[{"$ref": "#/components/parameters/Id"}])}})
    official["components"] = {"parameters": {"Id": _param("X-Request-Id", "header")}}
    generated = _doc({"/x": {"get": _op(parameters=[_param("x-request-id", "header")])}})
    r = align(official, generated)
    assert (("paths./x.get.parameters[0]",),
            ("paths./x.get.parameters[in=header,name=x-request-id]",)) in _groups(r)


def test_a_path_with_renamed_template_names_is_the_same_path():
    """R2: /pets/{petId} and /pets/{name} are the same path."""
    official = _doc({"/pets/{petId}": {"get": _op()}})
    generated = _doc({"/pets/{name}": {"get": _op()}})
    r = align(official, generated)
    assert _groups(r)[(("paths./pets/{petId}.get",), ("paths./pets/{name}.get",))] == {"key"}


def test_an_operation_with_the_same_operation_id_is_the_same_operation():
    """R3: operationId is unique among the operations of an API."""
    official = _doc({"/a": {"get": _op(operationId="listThings")}})
    generated = _doc({"/b": {"get": _op(operationId="listThings")}})
    r = align(official, generated)
    assert (("paths./a.get",), ("paths./b.get",)) in _groups(r)


def test_a_schema_copied_elsewhere_joins_its_schema():
    """R13 / R14: the same schema name outside components.schemas is a copy of it."""
    thing = {"type": "object", "properties": {"a": {"type": "string"}}}
    official = _doc(schemas={"Thing": thing})
    generated = _doc({"/x": {"put": _op(callbacks={"components": {"Thing": thing}})}},
                     schemas={"Thing": thing})
    generated["components"]["Thing"] = thing
    r = align(official, generated)
    group = _groups(r)[(("components.schemas.Thing",),
                        ("components.Thing", "components.schemas.Thing",
                         "paths./x.put.callbacks.components.Thing"))]
    assert group == {"address", "key"}
    _owned_add_up(r, official, generated)


def test_a_renamed_callback_with_the_same_delivery_is_grouped():
    """R11 / R12: a callback's name carries no meaning; what it delivers does."""
    def cb(expr):
        return {expr: {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Note"}}}},
            "responses": {"204": {"description": "ok"}}}}}
    official = _doc({"/s": {"post": _op(callbacks={"onNote": cb("{$request.body#/url}")})}})
    generated = _doc({"/s": {"post": _op(callbacks={"noteSent": cb("{target}")})}})
    r = align(official, generated)
    assert _groups(r)[(("paths./s.post.callbacks.onNote",),
                       ("paths./s.post.callbacks.noteSent",))] == {"key"}


# ── what is NOT exact stays a leftover, for the LLM ──────────────────────────

def test_servers_are_never_used_to_align_a_path():
    """A path that repeats the server prefix is not grouped here: that needs reading."""
    official = _doc({"/x": {"get": _op()}}, servers=[{"url": "{root}/svc"}])
    generated = _doc({"/{root}/svc/x": {"get": _op()}})
    r = align(official, generated)
    assert "paths./x.get" in _left(r, "official")
    assert "paths./{root}/svc/x.get" in _left(r, "generated")


def test_an_operation_and_a_callback_with_the_same_delivery_are_left_to_the_llm():
    """The same method and body do not prove the same role: an API may well receive
    what a callback sends."""
    body = {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/N"}}}}
    official = _doc({"/s": {"post": _op(callbacks={"onN": {"{$request.body#/u}": {
        "post": {"requestBody": body, "responses": {"204": {"description": "ok"}}}}}})}})
    generated = _doc({"/s": {"post": _op()}, "/sink": {"post": _op(requestBody=body)}})
    r = align(official, generated)
    assert "paths./s.post.callbacks.onN" in _left(r, "official")
    assert "paths./sink.post" in _left(r, "generated")


def test_a_key_two_official_blocks_share_decides_nothing():
    """/a/{x} and /a/{y} are the same path by R2 — with both in the official, which one
    a generated /a/{z} is cannot be told."""
    official = _doc({"/a/{x}": {"get": _op()}, "/a/{y}": {"get": _op()}})
    generated = _doc({"/a/{z}": {"get": _op()}})
    r = align(official, generated)
    assert _left(r, "generated") == {"paths./a/{z}.get"}


def test_default_and_error_ranges_are_left_to_the_llm():
    """R10: whether a default plays the role of 4XX / 5XX needs interpretation."""
    official = _doc({"/x": {"get": {"responses": {"200": {"description": "OK"},
                                                  "default": {"description": "Error"}}}}})
    generated = _doc({"/x": {"get": {"responses": {"200": {"description": "OK"},
                                                   "4XX": {"description": "Error"},
                                                   "5XX": {"description": "Error"}}}}})
    r = align(official, generated)
    assert _left(r, "official") == {"paths./x.get.responses.default"}
    assert _left(r, "generated") == {"paths./x.get.responses.4XX", "paths./x.get.responses.5XX"}
    assert [c for c, _ in r.candidates["official:paths./x.get.responses.default"]]


def test_content_shared_by_two_official_blocks_decides_nothing():
    """Two official media types with the same schema: which one a renamed generated
    media type is cannot be told by content."""
    body = {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/P"}}}
    official = _doc({"/x": {"patch": _op(requestBody={"content": {
        "application/json-patch+json": body, "application/3gpp-json-patch+json": body}})}})
    generated = _doc({"/x": {"patch": _op(requestBody={"content": {
        "application/vnd.3gpp.json-patch+json": body}})}})
    r = align(official, generated)
    assert len(_left(r, "official")) == 2 and len(_left(r, "generated")) == 1


def test_a_trivial_schema_does_not_group_by_content():
    """{type: object} is many schemas: content alone does not make them one."""
    official = _doc(schemas={"Resource": {"type": "object"}})
    generated = _doc(schemas={"ErrorResponse": {"type": "object"}})
    r = align(official, generated)
    assert not [g for g in r.groups if g.kind == "schema"]


# ── the real inputs ──────────────────────────────────────────────────────────

def _load(path):
    return yaml.safe_load(path.read_text())


REF = ROOT / "data/inputs/reference"
GEN = ROOT / "data/inputs/generated"

# (official, generated): (groups, leftovers official, leftovers generated)
ALIGNMENT_RESULTS = {
    (("ProvMnS", "18.2.0"), "ProvMnS/provmns_20260828_232853"): (35, 18, 20),
    (("PerfMnS", "18.1.0"), "PerfMnS/perfmns_20260823_031421"): (12, 1, 2),
}


@pytest.mark.parametrize(("official", "generated"), list(ALIGNMENT_RESULTS))
def test_the_alignment_of_the_generated_documents_is_pinned(official, generated):
    off, gen = _load(reference_yaml(*official)), _load(GEN / f"{generated}.yaml")
    r = align(off, gen)
    _owned_add_up(r, off, gen)
    assert (len(r.groups), len(_left(r, "official")), len(_left(r, "generated"))) \
        == ALIGNMENT_RESULTS[(official, generated)]


@pytest.mark.parametrize("doc", [REF / "ProvMnS/TS28532_ProvMnS_v18.2.0.yaml",
                                 GEN / "ProvMnS/provmns_20260828_232853.yaml"])
def test_a_document_against_itself_is_all_address(doc):
    d = _load(doc)
    r = align(d, d)
    assert not r.leftovers
    assert {s for g in r.groups for s in g.how.values()} == {"address"}


def test_two_official_versions_differ_only_by_what_the_new_one_added():
    """v18.2.0 added the dataNodeSelector query parameter, the notifyEvent callback and
    the NotifyEvent schema to v17.5.0 — and nothing else is left over."""
    r = align(_load(REF / "ProvMnS/TS28532_ProvMnS_v17.5.0.yaml"),
              _load(REF / "ProvMnS/TS28532_ProvMnS_v18.2.0.yaml"))
    assert not _left(r, "official")
    assert _left(r, "generated") == {
        "paths./{className}={id}.get.parameters[in=query,name=dataNodeSelector]",
        "paths./{className}={id}.put.callbacks.notifyEvent",
        "components.schemas.NotifyEvent"}
