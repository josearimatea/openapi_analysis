"""Pin the results this repo reports for the inputs in data/inputs.

Every number published from this instrument is locked here, per input. A change
to the extraction, the comparison or the inputs that moves one of them fails this
test, so the move is a deliberate edit — never a silent drift (the lesson of the
three mis-measurements in CLAUDE.md §2).
"""

import json

import pytest
import yaml

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.services import (
    evaluate_all_generated,
    evaluate_all_rules_banks,
    evaluate_openapi,
    evaluate_rules_bank,
    extract_official_rules,
)

BANK_I20_PROVMNS = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20260915_214107.json"
OFFICIAL_PROVMNS = reference_yaml("ProvMnS", "18.2.0")

# (expected, covered, value_equal, value_different, value_not_comparable,
#  bank_rules, bank_extra, bank_invalid_rules, shared_addresses)
RULES_BANK_RESULTS = {
    "rules_bank_28532-i20_full_20260915_214107": (113, 81, 53, 19, 9, 122, 39, 14, 2),
    "rules_bank_28532-i00_full_20260828_210819": (113, 59, 40, 15, 4, 97, 37, 5, 1),
    "rules_bank_28532-i20_full_20260915_232343": (15, 14, 13, 0, 1, 18, 4, 1, 0),
    "rules_bank_28532-i00_full_20260926_182802": (15, 14, 13, 0, 1, 22, 8, 0, 0),
    "rules_bank_28532-i00_full_20260818_214526": (15, 13, 11, 1, 1, 17, 3, 0, 1),
}

# contract leaves: (total, exact, absent, differing, extra)
OPENAPI_RESULTS = {
    "provmns_20260920_194130": (169, 38, 126, 5, 270),
    "provmns_20260828_232853": (169, 62, 102, 5, 181),
    "perfmns_20260823_031421": (18, 17, 1, 0, 3),
}


def _stem(label):
    return label.rsplit("/", 1)[-1].rsplit(".", 1)[0]


@pytest.fixture(scope="module")
def bank_reports():
    return {_stem(r.bank.label): r for r in evaluate_all_rules_banks(save=False)}


@pytest.fixture(scope="module")
def openapi_reports():
    return {_stem(r.generated.label): r for r in evaluate_all_generated(save=False)}


def test_every_input_is_evaluated(bank_reports, openapi_reports):
    assert set(bank_reports) == set(RULES_BANK_RESULTS)
    assert set(openapi_reports) == set(OPENAPI_RESULTS)


@pytest.mark.parametrize("bank", sorted(RULES_BANK_RESULTS))
def test_rules_bank_results(bank_reports, bank):
    r = bank_reports[bank]
    t = r.totals
    assert (t.expected, t.covered, t.value_equal, t.value_different, t.value_not_comparable,
            t.bank_rules, t.bank_extra, r.bank_invalid_rules,
            len(r.shared_addresses)) == RULES_BANK_RESULTS[bank]


def test_rules_bank_i20_provmns_by_rule_type(bank_reports):
    """The reference bank, per rule_type:
    (expected, covered, equal, different, not_comparable, bank_rules, bank_extra)."""
    r = bank_reports["rules_bank_28532-i20_full_20260915_214107"]
    got = {k: (c.expected, c.covered, c.value_equal, c.value_different,
               c.value_not_comparable, c.bank_rules, c.bank_extra)
           for k, c in r.by_rule_type.items()}
    assert got == {
        "callback":        (5, 5, 0, 5, 0, 6, 0),       # wrong expression in all 5
        "path_operation":  (4, 4, 4, 0, 0, 4, 0),
        "path_parameter":  (2, 2, 2, 0, 0, 3, 1),
        "query_parameter": (5, 0, 0, 0, 0, 6, 6),       # all at path level (§3.22)
        "request_body":    (11, 8, 8, 0, 0, 9, 1),
        "response":        (21, 13, 2, 5, 6, 32, 19),
        "schema_property": (65, 49, 37, 9, 3, 62, 12),
    }


def test_external_ref_turned_internal_is_measured_323(bank_reports):
    r = bank_reports["rules_bank_28532-i20_full_20260915_214107"]
    lost = [m for m in r.matches if m.note.startswith("§3.23")]
    assert len(lost) == 5


@pytest.mark.parametrize("generated", sorted(OPENAPI_RESULTS))
def test_openapi_results(openapi_reports, generated):
    c = openapi_reports[generated].contract
    assert (c.total, c.exact, len(c.absent), len(c.differing),
            len(c.extra)) == OPENAPI_RESULTS[generated]


def test_services_accept_parsed_documents():
    """Sibling repos call the services with what they hold in memory: dicts."""
    bank = json.loads(BANK_I20_PROVMNS.read_text(encoding="utf-8"))
    official = yaml.safe_load(OFFICIAL_PROVMNS.read_text(encoding="utf-8"))
    from_dicts = evaluate_rules_bank(bank, official)
    from_paths = evaluate_rules_bank(BANK_I20_PROVMNS, OFFICIAL_PROVMNS)
    assert from_dicts.totals == from_paths.totals
    assert evaluate_openapi(official, official).contract.ratio == 1.0


def test_extracted_official_rules_are_a_rules_bank_document():
    doc = extract_official_rules(OFFICIAL_PROVMNS)
    assert set(doc) == {"metadata", "summary", "rules"}
    assert doc["summary"]["total"] == len(doc["rules"]) == 113
