"""Aiming the judge's retrieval at a part — no Qdrant: a fake search records the calls.

Locks the scheme (docs/JUDGE_PLAN.md §4.4): 3 focused queries on the spec and 2 on the
OpenAPI reference, PER_QUERY chunks each, the spec filtered on the server to the
service's scope and no annex, the defining sections first. Whether the real hits are pertinent is
checked by hand on the pilot parts (docs/RASTREIO.md).
"""

from openapi_analysis.judge.retrieval import (
    differing_terms,
    openapi_queries,
    retrieve_evidence,
    spec_queries,
    subject,
)
from openapi_analysis.schemas.judge import Part, SearchHints


def part(owner="PATCH /{className}={id}", aspect="responses", evaluation="generator",
         official=None, generated=None, diff_terms=(), **hints):
    hints.setdefault("path", "/{className}={id}")
    hints.setdefault("method", "patch" if owner.startswith("PATCH") else "")
    return Part(id="x", evaluation=evaluation, input="i", owner=owner, aspect=aspect,
                summary="s", official=official, generated=generated,
                diff_terms=list(diff_terms), hints=SearchHints(**hints))


class FakeSearch:
    """Returns `hits[collection]` for every query, recording the calls."""

    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def __call__(self, query, collection, k, filters):
        self.calls.append((query, collection, k, filters))
        return self.hits.get(collection, [])[:k]


def chunk(clause, n):
    return (f"text {clause} #{n}", {"clause": clause, "title": f"{clause} title"})


# ── the queries ──────────────────────────────────────────────────────────────

def test_a_schema_part_is_searched_by_its_name_alone_first():
    p = part(owner="SCHEMA NotifyEvent", aspect="definition",
             diff_terms=["specificProblem"],
             schemas=["NotifyEvent", "NotificationHeader", "SpecificProblem"])
    queries = spec_queries(p)
    assert queries[0] == "NotifyEvent"                       # not mixed with its references
    assert queries[1] == "Definition of type NotifyEvent"
    assert "specificProblem" in queries[2]


def test_a_callback_part_uses_the_notification_name():
    p = part(owner="PUT /x", aspect="callback notifyEvent")
    assert subject(p) == "notifyEvent"
    assert spec_queries(p)[1] == "Notification notifyEvent"


def test_an_operation_part_names_the_method_and_what_differs():
    """The terms are the part's differences, not the whole operation it carries."""
    p = part(official={"paths./x.patch": {"summary": "context only"}},
             diff_terms=["200", "204", "default", "4XX", "5XX"])
    queries = spec_queries(p)
    assert queries[0] == "HTTP PATCH"
    assert all(code in queries[2] for code in ("200", "204", "default", "4XX", "5XX"))
    assert "context" not in queries[2]


def test_a_bank_rule_is_searched_with_its_own_rule_text():
    rule = {"rule_type": "response", "rule_text": "The getMOIAttributes operation returns 200.",
            "openapi_mapping": {"openapi_field": "200", "openapi_value": "Resource"}}
    p = part(owner="response …", aspect="different", evaluation="rulesbank",
             generated=rule, official=rule, terms=["getMOIAttributes"], method="get")
    queries = spec_queries(p)
    assert queries[0] == "getMOIAttributes"
    assert queries[1] == rule["rule_text"]
    assert "200" in differing_terms(p)


def test_the_reference_is_searched_with_the_object_and_the_concept():
    p = part(diff_terms=["default", "4XX"])
    obj, concept = openapi_queries(p)
    assert "Responses Object" in obj
    assert "default" in concept and "4XX" in concept


def test_three_spec_queries_and_two_reference_queries():
    p = part(official={"200": {}}, generated={"4XX": {}})
    assert len(spec_queries(p)) == 3 and len(openapi_queries(p)) == 2


# ── the search ───────────────────────────────────────────────────────────────

def test_each_query_is_searched_and_nothing_is_repeated():
    search = FakeSearch({"spec": [chunk(f"12.1.{i}", i) for i in range(20)],
                         "openapi_reference": [chunk("", i) for i in range(20)]})
    p = part(official={"200": {}}, generated={"4XX": {}})
    ev = retrieve_evidence(p, "spec", search=search, scope=("12.1",), per_query=5)
    assert [c[1] for c in search.calls] == ["spec"] * 3 + ["openapi_reference"] * 2
    assert all(c[2] == 5 for c in search.calls)
    assert len({e.text for e in ev}) == len(ev)


def test_the_spec_is_filtered_on_the_server_per_block_of_the_scope():
    search = FakeSearch({"spec": [chunk("12.1.1", 0)], "openapi_reference": [chunk("", 1)]})
    ev = retrieve_evidence(part(), "spec", search=search, scope=("11.1", "12.1"))
    spec = [c[3] for c in search.calls if c[1] == "spec"]
    assert {"annex": False, "clause_ancestors": "11.1"} in spec
    assert {"annex": False, "clause_ancestors": "12.1"} in spec
    assert all(c[3] is None for c in search.calls if c[1] == "openapi_reference")
    assert next(e for e in ev if e.source == "spec").filters["clause_ancestors"] == "11.1"


def test_no_scope_still_keeps_annexes_out():
    search = FakeSearch({"spec": [], "openapi_reference": []})
    retrieve_evidence(part(), "spec", search=search, scope=())
    assert all(c[3] == {"annex": False} for c in search.calls if c[1] == "spec")


def test_a_type_or_a_notification_asks_first_for_the_sections_that_define_it():
    search = FakeSearch({"spec": [chunk("12.1.1.4", i) for i in range(9)]})
    p = part(owner="MoiChange", aspect="schema — grouped by address", schemas=["MoiChange"])
    retrieve_evidence(p, "spec", search=search, scope=("12.1",), per_definition=3)
    assert search.calls[0] == ("MoiChange", "spec", 3, {"annex": False,
                                                        "clause_ancestors": "12.1",
                                                        "defines": "MoiChange"})
    search = FakeSearch({"spec": []})
    p = part(owner="callback notifyEvent — POST x — registered by PUT /x",
             aspect="callback — missing in the generated")
    retrieve_evidence(p, "spec", search=search, scope=("12.1",))
    assert search.calls[0][3]["defines"] == "notifyEvent"
    search = FakeSearch({"spec": []})
    retrieve_evidence(part(), "spec", search=search, scope=("12.1",))
    assert "defines" not in search.calls[0][3]                # an operation defines nothing


def test_a_ref_to_another_file_is_looked_for_in_its_spec_by_defined_name():
    ref = "TS28623_ComDefs.yaml#/components/schemas/NotificationHeader"
    search = FakeSearch({"all": [chunk("C.4.2a", 0)], "spec": [], "openapi_reference": []})
    p = part(external_refs=[ref, "Other.yaml#/x"])
    ev = retrieve_evidence(p, "spec", search=search, scope=("12.1",), external_collection="all")
    call = next(c for c in search.calls if c[1] == "all")
    assert call[0] == "NotificationHeader"
    assert call[3] == {"spec_number": "28623", "defines": "NotificationHeader"}
    assert ev[0].title.startswith(f"definition of {ref}") and ev[0].clause == "C.4.2a"
    assert len([c for c in search.calls if c[1] == "all"]) == 1       # not a 3GPP file name


def test_the_judge_sees_where_each_spec_passage_sits():
    from openapi_analysis.judge.prompts import user_message

    where = "12.1 Provisioning › 12.1.2 Solution set for ONAP VES › 12.1.2.2.6 Notification"
    hits = [("text", {"clause": "12.1.2.2.6", "title": "Notification", "path": where})]
    ev = retrieve_evidence(part(), "spec", search=FakeSearch({"spec": hits}), scope=("12.1",))
    assert ev[0].path == where
    assert f"in: {where}" in user_message(part(), [ev[0].model_copy(update={"id": "S1"})])
