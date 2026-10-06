"""The judge's spec index: normative text only — no annex, ever (docs/JUDGE_PLAN.md §4.1).

No Qdrant, no LLM: only the cut and the split that decide what can be indexed.
"""

import re

import pytest

from openapi_analysis.config.paths import SPECS_DIR
from openapi_analysis.judge.spec_index import (
    block_of,
    clause_of,
    in_scope,
    normative_only,
    split_sections,
)

SAMPLE = """\
Contents
1 Scope [5](#scope)
12.1 Operations [10](#operations)
Annex A (normative): OpenAPI specification [99](#annex-a)

# Foreword
Produced by 3GPP.

# 1 Scope
The present document specifies the provisioning MnS.

##### 12.1.1.1.1 Introduction {#introduction-1}
The createMOI operation is mapped to PUT.

Some Title
----------
Body of a setext section.

# Annex A (normative): OpenAPI specification
## A.1.1 OpenAPI document "TS28532_ProvMnS.yaml"
openapi: 3.0.1
info:
  title: Provisioning MnS

# Annex B (informative): Change history
A table.
"""


def test_the_contents_listing_and_every_annex_are_cut():
    body = normative_only(SAMPLE)
    assert "Annex" not in body
    assert "openapi:" not in body
    assert "[5](#scope)" not in body
    assert "createMOI" in body


def test_sections_carry_their_clause_and_a_clean_title():
    secs = {s.title: s for s in split_sections(SAMPLE)}
    assert list(secs) == ["Foreword", "1 Scope", "12.1.1.1.1 Introduction", "Some Title"]
    assert secs["12.1.1.1.1 Introduction"].clause == "12.1.1.1.1"
    assert secs["Foreword"].clause == ""


@pytest.mark.parametrize("title, clause", [
    ("12.1.1.1.1 Introduction", "12.1.1.1.1"),
    ("12.1.1.4.1a.7 Type NotifyMoiAttributeValueChanges", "12.1.1.4.1a.7"),
    ("4 Overview", "4"),
    ("A.1.1 OpenAPI document", "A.1.1"),
    ("Annex A (normative): OpenAPI specification", "A"),
    ("Foreword", ""),
])
def test_clause_of(title, clause):
    assert clause_of(title) == clause


def test_block_and_scope():
    assert block_of("12.1.1.4.1a.7") == "12.1"
    assert block_of("4") == "4"
    assert in_scope("12.1.1.3", ("12.1",)) and in_scope("12.1", ("12.1",))
    assert not in_scope("12.10.1", ("12.1",))           # a block, not a string prefix
    assert not in_scope("11.1.1.10", ("12.1",))
    assert in_scope("11.1.1.10", ())                      # no scope: everything


@pytest.mark.parametrize("service, bank, scope", [
    ("ProvMnS", "rules_bank_28532-i20_full_20260915_214107", ("12.1",)),
    ("PerfMnS", "rules_bank_28532-i20_full_20260915_232343", ("12.3",)),
])
def test_the_scope_is_read_from_the_bank(service, bank, scope):
    """No table per spec: the blocks of the clauses the bank's rules came from."""
    import json

    from openapi_analysis.config.paths import RULESBANK_DIR
    from openapi_analysis.services.judge_service import scope_of_bank

    data = json.loads((RULESBANK_DIR / service / f"{bank}.json").read_text(encoding="utf-8"))
    assert scope_of_bank(data) == scope


def test_no_annex_reaches_the_index_of_the_real_spec():
    """TS 28.532 i20: its Annex A is the official YAML — none of it may be indexed."""
    secs = split_sections((SPECS_DIR / "28532-i20.md").read_text(encoding="utf-8"))
    assert secs, "the spec produced no section"
    assert not [s.title for s in secs if re.match(r"(Annex\b|[A-Z]\.\d)", s.title)]
    assert not [s.title for s in secs
                if re.search(r"^\s*(openapi|paths|components):", s.content, re.MULTILINE)]
    assert secs[-1].clause.startswith("12.")          # the normative text ends in clause 12


# ── the shared corpus: annexes cut at retrieval ──────────────────────────────

CORPUS = {
    0: "Contents\n1 Scope 7\n2 References 7\n3 Definitions 8\n12.1 Provisioning 10\n"
       "Annex A (normative): OpenAPI specification 202\nAnnex B (Informative): Guidelines\n",
    1: "#### 12.1.1.3.2.1.3.2 HTTP GET\nThis method shall support the URI query parameters.",
    2: "ErrorResponse  4xx/5xx  Returned in case of an error  M\n"
       "########  Annex A (normative): OpenAPI specification\nA.0 Introduction\n",
    3: "openapi: 3.0.1\ninfo:\n  title: Provisioning MnS\n",
    4: "**Spec 28532-i00, Release Rel-18, Series 28_series** Table 5\n| Parameter | S |",
}


def test_the_corpus_annex_starts_at_its_heading_not_in_the_contents():
    from openapi_analysis.judge.spec_index import annex_cut

    assert annex_cut(CORPUS) == (2, CORPUS[2].index("########"))


def test_corpus_chunks_keep_only_normative_text():
    from openapi_analysis.judge.spec_index import annex_cut, corpus_text

    cut = annex_cut(CORPUS)
    kept = {i: corpus_text(t, i, cut) for i, t in CORPUS.items()}
    assert kept[0] == ""                                  # contents listing
    assert kept[1] == CORPUS[1]
    assert "4xx/5xx" in kept[2] and "Annex" not in kept[2]  # cut inside the chunk
    assert kept[3] == ""                                  # annex, and an OpenAPI piece
    assert kept[4] == CORPUS[4]                           # extracted tables are kept


def test_a_piece_of_an_openapi_document_is_never_spec_text():
    from openapi_analysis.judge.spec_index import corpus_text

    yaml_piece = "parameters:\n  \\- name: scope\n    in: query\n    schema:\n      type: string\n"
    assert corpus_text(yaml_piece, None, None) == ""


def test_the_clause_is_read_from_the_chunk_heading():
    from openapi_analysis.judge.spec_index import heading_clause

    assert heading_clause(CORPUS[1]) == ("12.1.1.3.2.1.3.2", "12.1.1.3.2.1.3.2 HTTP GET")
    assert heading_clause("a table row without heading") == ("", "")
    caption = "rows ... **Table 12.5.1.3.2.1.3.2-2: Data structures supported** ..."
    assert heading_clause(caption)[0] == "12.5.1.3.2.1.3.2"      # read from the caption


def test_a_chunk_is_split_where_one_section_ends_and_the_next_begins():
    """The corpus cuts by size: a chunk holding the end of HTTP GET (its 4xx/5xx row)
    and the start of HTTP PATCH gives the row to GET, not to PATCH."""
    from openapi_analysis.judge.spec_index import chunk_clauses, split_by_heading

    chunks = {10: "#### 12.1.1.3.2.1.3.2 HTTP GET\nquery parameters ...",
              11: "ErrorResponse  4xx/5xx  Returned in case of an error  M\n"
                  "#### 12.1.1.3.2.1.3.3 HTTP PATCH\nrequest body ...",
              12: "more PATCH text",
              13: "**Spec 28532-i00, Release Rel-18** Table 9 Table 12.5.1.2-1: rows"}
    begins = chunk_clauses(chunks)
    assert {i: c for i, (c, _) in begins.items()} == {
        10: "", 11: "12.1.1.3.2.1.3.2", 12: "12.1.1.3.2.1.3.3", 13: "12.5.1.2"}
    pieces = split_by_heading(chunks[11], begins[11])
    assert [(c, t.split("\n")[0][:13]) for c, _, t in pieces] == [
        ("12.1.1.3.2.1.3.2", "ErrorResponse"), ("12.1.1.3.2.1.3.3", "#### 12.1.1.3")]
