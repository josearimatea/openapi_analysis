"""The judge's spec index: normative text only — no annex, ever (docs/JUDGE_PLAN.md §4.1).

No Qdrant, no LLM: only the cut and the split that decide what can be indexed.
"""

import re

import pytest

from openapi_analysis.config.paths import SPECS_DIR
from openapi_analysis.judge.spec_index import clause_of, normative_only, split_sections

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


@pytest.mark.parametrize("service, words", [
    ("ProvMnS", "provisioning"), ("PerfMnS", "performance"), ("HeartbeatNtf", "heartbeat"),
    ("StreamingDataMnS", "streaming"), ("FileDataReportingMnS", "file data reporting"),
])
def test_the_service_clauses_match_the_spec_headings(service, words):
    """judge_settings.SPEC_SERVICE_CLAUSES, checked against TS 28.532 i20's own headings."""
    from openapi_analysis.config.judge_settings import SPEC_SERVICE_CLAUSES
    from openapi_analysis.judge.spec_index import outline

    titles = {c: t for c, t, _ in outline(SPECS_DIR / "28532-i20.md")}
    for clause in SPEC_SERVICE_CLAUSES["28532"][service]:
        assert words in titles[clause].lower(), f"{clause}: {titles[clause]}"


def test_no_annex_reaches_the_index_of_the_real_spec():
    """TS 28.532 i20: its Annex A is the official YAML — none of it may be indexed."""
    secs = split_sections((SPECS_DIR / "28532-i20.md").read_text(encoding="utf-8"))
    assert secs, "the spec produced no section"
    assert not [s.title for s in secs if re.match(r"(Annex\b|[A-Z]\.\d)", s.title)]
    assert not [s.title for s in secs
                if re.search(r"^\s*(openapi|paths|components):", s.content, re.MULTILINE)]
    assert secs[-1].clause.startswith("12.")          # the normative text ends in clause 12
