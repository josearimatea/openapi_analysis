"""The checks on the grouper's answer (judge/grouping.py) — with answers written by
hand: what the LLM proposes is only grouped when it passes them. Whether the LLM
groups well is measured on the real documents, not here."""

from openapi_analysis.judge.grouping import apply_answer, grouping_messages, run_grouping
from openapi_analysis.openapi.alignment import Aligner
from openapi_analysis.schemas.alignment import (
    GroupingAnswer,
    ProposedGroup,
    ProposedJoin,
    Ungrouped,
)

BODY = {"schema": {"$ref": "#/components/schemas/Patch"}}
ERROR = {"description": "Error", "content": {"application/json": {
    "schema": {"$ref": "#/components/schemas/Error"}}}}


def _doc(paths):
    return {"openapi": "3.0.1", "info": {"title": "t", "version": "1"}, "paths": paths}


OFFICIAL = _doc({"/x": {
    "get": {"responses": {"200": {"description": "OK"}, "default": ERROR}},
    "patch": {"requestBody": {"content": {"application/json-patch+json": BODY,
                                          "application/3gpp-json-patch+json": BODY}},
              "responses": {"204": {"description": "OK"}}}}})
GENERATED = _doc({
    "/x": {"get": {"responses": {"200": {"description": "OK"}, "4XX": ERROR, "5XX": ERROR}},
           "patch": {"requestBody": {"content": {"application/vnd.3gpp.json-patch+json": BODY}},
                     "responses": {"204": {"description": "OK"}}}},
    "/root/x": {"get": {"responses": {"200": {"description": "OK"}}}}})


def _setup():
    a = Aligner(OFFICIAL, GENERATED)
    a.deterministic()
    owned = a.owned()
    msgs, ids = grouping_messages(a, "all", a.leftovers(owned), owned)
    tag = {a.blocks[b].location: t for t, b in ids.items() if b in a.blocks}
    group = {a.blocks[g.official[0]].location: g.id for g in a.groups if g.official}
    return a, msgs, ids, tag, group


def test_every_leftover_is_shown_with_what_it_most_resembles_even_if_grouped():
    _, msgs, _, tag, group = _setup()
    text = msgs[1][1]
    assert set(tag) == {"paths./x.get.responses.default", "paths./x.get.responses.4XX",
                        "paths./x.get.responses.5XX", "paths./root/x.get",
                        "paths./x.patch.requestBody.content.application/json-patch+json",
                        "paths./x.patch.requestBody.content.application/3gpp-json-patch+json",
                        ("paths./x.patch.requestBody.content."
                         "'application/vnd.3gpp.json-patch+json'")}
    # the extra GET /root/x is set beside the GET /x already grouped, with its content
    assert f"in group {group['paths./x.get']}: operation at paths./x.get" in text


def test_a_valid_answer_groups_and_joins():
    a, _, ids, tag, group = _setup()
    answer = GroupingAnswer(
        groups=[ProposedGroup(official=[tag["paths./x.get.responses.default"]],
                              generated=[tag["paths./x.get.responses.4XX"],
                                         tag["paths./x.get.responses.5XX"]], reason="R10")],
        joins=[ProposedJoin(block=tag["paths./root/x.get"], group=group["paths./x.get"],
                            reason="duplicate")],
        ungrouped=[Ungrouped(block=t, reason="-") for loc, t in tag.items()
                   if "requestBody" in loc])
    assert apply_answer(a, answer, ids) == []
    g = a.group_of[ids[tag["paths./x.get.responses.default"]]]
    assert len(g.generated) == 2 and set(g.how.values()) == {"llm"}
    assert ids[tag["paths./root/x.get"]] in a.group_of[ids[tag["paths./root/x.get"]]].generated


def test_the_checks_refuse_what_is_not_allowed():
    a, _, ids, tag, _ = _setup()
    official_mt = [t for loc, t in tag.items() if "requestBody" in loc and "vnd" not in loc]
    vnd = tag["paths./x.patch.requestBody.content.'application/vnd.3gpp.json-patch+json'"]
    answer = GroupingAnswer(
        groups=[
            # two official media types for one generated: one media type per side (R9)
            ProposedGroup(official=official_mt, generated=[vnd], reason="-"),
            # an id never given
            ProposedGroup(official=["A99"], generated=[tag["paths./x.get.responses.4XX"]],
                          reason="-"),
            # a response with an operation: kinds that do not correspond
            ProposedGroup(official=[tag["paths./x.get.responses.default"]],
                          generated=[tag["paths./root/x.get"]], reason="-"),
        ],
        joins=[ProposedJoin(block=tag["paths./x.get.responses.5XX"], group="G999",
                            reason="-")])
    refused = apply_answer(a, answer, ids)
    assert any("one media_type per side" in r for r in refused)
    assert any("A99" in r for r in refused)
    assert any("different kinds" in r for r in refused)
    assert any("unknown id" in r for r in refused)
    assert any(r.startswith("not answered") for r in refused)
    assert not [g for g in a.groups if "llm" in g.how.values()]     # nothing grouped


def test_a_join_of_a_second_media_type_is_refused():
    a, _, ids, tag, _ = _setup()
    o1 = tag["paths./x.patch.requestBody.content.application/json-patch+json"]
    o2 = tag["paths./x.patch.requestBody.content.application/3gpp-json-patch+json"]
    vnd = tag["paths./x.patch.requestBody.content.'application/vnd.3gpp.json-patch+json'"]
    apply_answer(a, GroupingAnswer(groups=[ProposedGroup(official=[o1], generated=[vnd],
                                                         reason="-")]), ids)
    g = a.group_of[ids[o1]]
    owned = a.owned()                    # a later call: the group is in its index now
    _, ids = grouping_messages(a, "all", a.leftovers(owned), owned)
    o2 = next(t for t, b in ids.items()
              if b in a.blocks and a.blocks[b].location.endswith("3gpp-json-patch+json"))
    refused = apply_answer(a, GroupingAnswer(joins=[ProposedJoin(block=o2, group=g.id,
                                                                 reason="-")]), ids)
    assert any("one media_type per side" in r for r in refused)


def test_the_documents_are_given_whole():
    _, msgs, _, _, _ = _setup()
    text = msgs[1][1]
    assert "OFFICIAL DOCUMENT (YAML):" in text and "GENERATED DOCUMENT (YAML):" in text
    assert "/root/x:" in text and "application/3gpp-json-patch+json" in text


def test_one_call_per_family_with_leftovers_and_answers_are_cached(tmp_path):
    a = Aligner(OFFICIAL, GENERATED, official_label="o", generated_label="g")
    a.deterministic()
    asked = []

    def ask(msgs):
        asked.append(msgs)
        return GroupingAnswer()

    r = run_grouping(a, ask=ask, model="m", cache_dir=tmp_path)
    # endpoints (GET /root/x) and request bodies / responses: two families, two calls
    assert len(asked) == 2 and [c.area for c in r.calls] == [
        "endpoints (paths, operations, callbacks)", "request bodies and responses"]
    b = Aligner(OFFICIAL, GENERATED, official_label="o", generated_label="g")
    b.deterministic()
    run_grouping(b, ask=ask, model="m", cache_dir=tmp_path)
    assert len(asked) == 2                                      # read back from the cache


def test_a_callback_never_joins_the_group_of_an_operation_on_its_own_side():
    """An official callback joined to the group of an operation (official + generated
    operation) would put two kinds on the official side: refused. The exception is
    only an operation on one side for a callback on the other."""
    cb = {"{$request.body#/u}": {"post": {"requestBody": {"content": {"application/json": BODY}},
                                          "responses": {"204": {"description": "ok"}}}}}
    official = _doc({"/x": {"put": {"responses": {"200": {"description": "OK"}},
                                    "callbacks": {"onN": cb}}}})
    generated = _doc({"/x": {"put": {"responses": {"200": {"description": "OK"}}}},
                      "/sink": {"post": {"requestBody": {"content": {"application/json": BODY}},
                                         "responses": {"204": {"description": "ok"}}}}})
    a = Aligner(official, generated)
    a.deterministic()
    owned = a.owned()
    _, ids = grouping_messages(a, "all", a.leftovers(owned), owned)
    tag = {a.blocks[b].location: t for t, b in ids.items() if b in a.blocks}
    put_group = a.group_of["official:paths./x.put"].id
    refused = apply_answer(a, GroupingAnswer(joins=[ProposedJoin(
        block=tag["paths./x.put.callbacks.onN"], group=put_group, reason="-")]), ids)
    assert any("different kinds" in r for r in refused)
    assert apply_answer(a, GroupingAnswer(groups=[ProposedGroup(
        official=[tag["paths./x.put.callbacks.onN"]], generated=[tag["paths./sink.post"]],
        reason="R12")]), ids) == []
