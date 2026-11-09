"""The judge's spec index: the clause of a section and the scope read from a bank.

No Qdrant, no LLM. The cut itself is qdrant_3gpp_rag's; that annexes stay out of every
spec search is locked in tests/judge/test_retrieval.py (annex = False).
"""

import pytest

from openapi_analysis.judge.spec_index import block_of, clause_of


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


def test_block_of():
    assert block_of("12.1.1.4.1a.7") == "12.1"
    assert block_of("4") == "4"
    assert block_of("") == ""


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
