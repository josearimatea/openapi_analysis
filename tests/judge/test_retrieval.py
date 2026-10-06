"""Aiming the judge's retrieval at a part — no Qdrant: a fake search records the calls.

Locks the scheme (docs/JUDGE_PLAN.md §4.4): 3 focused queries on the spec and 2 on the
OpenAPI reference, PER_QUERY new chunks each, spec chunks kept in the service's scope,
no annex clause ever handed to the judge. Whether the real hits are pertinent is
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

def test_each_query_brings_its_own_new_chunks_and_both_sources_are_searched():
    spec_hits = [chunk(f"12.1.{i}", i) for i in range(20)]
    ref_hits = [chunk("", i) for i in range(20)]
    search = FakeSearch({"spec": spec_hits, "openapi_reference": ref_hits})
    p = part(official={"200": {}}, generated={"4XX": {}})
    ev = retrieve_evidence(p, "spec", search=search, scope=("12.1",), per_query=5, pool=25)
    assert [c[1] for c in search.calls] == ["spec"] * 3 + ["openapi_reference"] * 2
    assert sum(e.source == "spec" for e in ev) == 15         # 3 queries × 5, none repeated
    assert sum(e.source == "openapi" for e in ev) == 10      # 2 queries × 5
    assert len({e.text for e in ev}) == len(ev)
    assert {e.query for e in ev if e.source == "spec"} == set(spec_queries(p))


def test_spec_chunks_out_of_scope_or_from_an_annex_are_never_evidence():
    hits = [chunk("12.3.1", 0), chunk("A.1.1", 1), chunk("12.1.1.2", 2), chunk("11.1.1", 3)]
    search = FakeSearch({"spec": hits, "openapi_reference": [chunk("", 9)]})
    ev = retrieve_evidence(part(), "spec", search=search, scope=("12.1",))
    assert {e.clause for e in ev if e.source == "spec"} == {"12.1.1.2"}


def test_no_scope_keeps_every_normative_clause():
    hits = [chunk("12.3.1", 0), chunk("12.1.1", 1), chunk("A.2", 2)]
    search = FakeSearch({"spec": hits, "openapi_reference": []})
    ev = retrieve_evidence(part(), "spec", search=search, scope=())
    assert {e.clause for e in ev} == {"12.3.1", "12.1.1"}
