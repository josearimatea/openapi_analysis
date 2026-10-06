"""Aiming the judge's retrieval at a part — no Qdrant: a fake search records the calls.

The real search was checked by hand on the ProvMnS pilot parts (docs/RASTREIO.md);
these tests lock the aiming: defining-title targets, the service scope, the bank
rule's clause, and that no annex clause is ever handed to the judge.
"""

import pytest

from openapi_analysis.config.paths import SPECS_DIR
from openapi_analysis.judge.retrieval import names, openapi_query, retrieve_evidence, title_targets
from openapi_analysis.judge.spec_index import outline
from openapi_analysis.schemas.judge import Part, SearchHints

OUTLINE = outline(SPECS_DIR / "28532-i20.md")
TITLES = {c: t for c, t, _ in OUTLINE}


def part(owner="PUT /{className}={id}", aspect="responses", evaluation="generator", **hints):
    return Part(id="x", evaluation=evaluation, input="i", owner=owner, aspect=aspect,
                summary="s", hints=SearchHints(**hints))


class FakeSearch:
    def __init__(self, hits=None):
        self.calls = []
        self.hits = hits or {}

    def __call__(self, query, collection, k, filters):
        self.calls.append((collection, filters))
        return self.hits.get((collection, tuple(sorted((filters or {}).items()))), [])


def test_the_subject_comes_before_the_referenced_schemas():
    p = part(aspect="callback notifyMOICreation", schemas=["Resource", "PatchItem"])
    assert names(p)[0] == "notifyMOICreation"


def test_only_a_defining_heading_is_a_title_target():
    """'Resource structure on the MnS producer' is not where the schema Resource is."""
    targets = [TITLES[c] for c in title_targets(part(schemas=["Resource"]), OUTLINE, "ProvMnS")]
    assert targets == ["12.1.1.4.1a.1 Type Resource"]


def test_a_title_without_text_leads_to_its_subclauses():
    """'11.1.1.10 Notification notifyEvent' has its text in 11.1.1.10.1 / .2."""
    targets = title_targets(part(aspect="callback notifyEvent"), OUTLINE, "ProvMnS")
    assert targets[:2] == ["11.1.1.10.1", "11.1.1.10.2"]
    assert "12.1.2.2.6" in targets


def test_title_targets_stay_in_the_service():
    """notifyThresholdCrossing is a PerfMnS notification: nothing for ProvMnS."""
    assert title_targets(part(aspect="callback notifyThresholdCrossing"), OUTLINE, "ProvMnS") == []
    assert title_targets(part(aspect="callback notifyThresholdCrossing"), OUTLINE, "PerfMnS")


def test_the_passes_and_their_filters():
    search = FakeSearch()
    p = part(evaluation="rulesbank", owner="callback …", aspect="different",
             clause="12.1.1.2.1", terms=["notifyMOICreation"])
    retrieve_evidence(p, "spec_col", search=search, service="ProvMnS", titles=OUTLINE)
    filters = [f for _, f in search.calls]
    assert {"clause": "12.1.1.2.1"} in filters                    # the bank rule's clause
    assert {"service": "ProvMnS"} in filters                      # similarity, in the service
    assert any(f and f.get("clause", "").startswith("11.1.1.7") for f in filters)  # title
    assert search.calls[-1] == ("openapi_reference", None)


def test_an_annex_clause_is_never_evidence():
    hits = {("spec_col", (("service", "ProvMnS"),)): [
        ("annex text", {"clause": "A.1.1", "title": "A.1.1 OpenAPI document"}),
        ("normative text", {"clause": "12.1.1.1.2", "title": "12.1.1.1.2 Operation createMOI"}),
    ]}
    ev = retrieve_evidence(part(), "spec_col", search=FakeSearch(hits), service="ProvMnS")
    assert [e.clause for e in ev if e.source == "spec"] == ["12.1.1.1.2"]


@pytest.mark.parametrize("aspect, word", [
    ("responses", "Responses Object"), ("parameters", "Parameter Object"),
    ("callback notifyEvent", "Callback Object"), ("definition", "Schema Object"),
])
def test_the_reference_is_searched_with_the_object_of_the_aspect(aspect, word):
    owner = "SCHEMA X" if aspect == "definition" else "PUT /x"
    assert word in openapi_query(part(owner=owner, aspect=aspect))
