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
#  bank_rules, bank_extra, bank_invalid_rules, shared_addresses, bank_ranges)
# since 07/nov/2026 an official default is covered by the bank's 4XX / 5XX (docs/RULES.md §4)
RULES_BANK_RESULTS = {
    "rules_bank_28532-i20_full_20260915_214107": (107, 87, 53, 25, 9, 122, 28, 14, 2, 5),
    "rules_bank_28532-i00_full_20260828_210819": (97, 59, 39, 16, 4, 97, 35, 5, 1, 2),  # v17.5.0
    "rules_bank_28532-i20_full_20260915_232343": (15, 15, 13, 1, 1, 18, 2, 1, 0, 1),
    "rules_bank_28532-i00_full_20260926_182802": (15, 15, 13, 1, 1, 22, 6, 0, 0, 1),
    "rules_bank_28532-i00_full_20260818_214526": (15, 14, 12, 1, 1, 17, 1, 0, 1, 1),
}

# contract leaves: (total, exact, absent, differing, extra)
OPENAPI_RESULTS = {
    "provmns_20260920_194130": (169, 38, 126, 5, 270),
    "provmns_20260828_232853": (145, 61, 78, 6, 181),      # official v17.5.0
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
            len(r.shared_addresses), t.bank_ranges) == RULES_BANK_RESULTS[bank]


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
        "response":        (21, 19, 2, 11, 6, 32, 8),       # 6 defaults covered by 4XX/5XX
        "schema_property": (59, 49, 37, 9, 3, 62, 12),
    }


def test_bank_rules_add_up_for_every_bank(bank_reports):
    for r in bank_reports.values():
        t = r.totals
        assert t.bank_rules == t.covered + t.bank_duplicates + t.bank_ranges + t.bank_extra


def test_generated_provmns_defects_are_located(openapi_reports):
    """The latest generated ProvMnS: what the per-owner breakdown must point at."""
    r = openapi_reports["provmns_20260920_194130"]
    status = {s.name: (s.status, s.found_at) for s in r.schemas}
    assert status["MoiChange"] == ("misplaced", "components.MoiChange")
    assert status["NotifyMoiAttributeValueChanges"] == (
        "misplaced", "components.NotifyMoiAttributeValueChanges")
    ops = {o.operation: o for o in r.operations}
    assert len(ops["GET /{className}={id}"].params_at_path_level) == 5     # §3.22
    checks = [i.check for i in r.validity_generated.issues]
    assert (checks.count("schema"), checks.count("local_ref")) == (11, 7)
    assert any(i.location == "paths" and "'components'" in i.message
               for i in r.validity_generated.issues)          # a path called "components"


def test_validity_of_every_generated_document(openapi_reports):
    """Layer 2: which generated documents are valid OpenAPI 3.0 (the official always are)."""
    got = {name: (r.validity_generated.valid, len(r.validity_generated.issues),
                  r.validity_official.valid)
           for name, r in openapi_reports.items()}
    assert got == {
        "provmns_20260920_194130": (False, 18, True),
        "provmns_20260828_232853": (True, 0, True),
        "perfmns_20260823_031421": (True, 0, True),
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
    assert doc["summary"]["total"] == len(doc["rules"]) == 107


def test_every_input_is_evaluated_against_the_official_of_its_spec_version():
    from openapi_analysis.services.inputs import manifest, official_of, spec_code_of

    expected = {"i00": {"ProvMnS": "17.5.0", "PerfMnS": "17.1.0"},
                "i20": {"ProvMnS": "18.2.0", "PerfMnS": "18.1.0"}}
    entries = [*manifest()["generated"], *manifest()["rulesbank"]]
    assert {spec_code_of(e) for e in entries} == {"i00", "i20"}
    for e in entries:
        version = expected[spec_code_of(e)][e["service"]]
        assert official_of(e).name.endswith(f"_v{version}.yaml"), e["path"]


def _versions(spec, official, input_name="provmns_20260828_232853", **kw):
    from openapi_analysis.services.inputs import check_versions, load, spec_document

    label = f"data/inputs/generated/ProvMnS/{input_name}.yaml"
    doc, official_label = load(reference_yaml("ProvMnS", official))
    return check_versions(spec_document(spec), label, "generated", doc, official_label, **kw)


def test_the_input_and_the_official_must_be_of_the_spec_the_analysis_is_based_on():
    from openapi_analysis.services.inputs import VersionMismatch

    assert _versions("28532-i00", "17.5.0") == []
    assert _versions("28532-i20", "18.2.0", "provmns_20260920_194130") == []
    with pytest.raises(VersionMismatch, match="v18.2.0, and the official of 28532-i00 is v17.5.0"):
        _versions("28532-i00", "18.2.0")
    with pytest.raises(VersionMismatch, match="comes from spec i00"):
        _versions("28532-i20", "18.2.0")


def test_another_version_can_be_compared_on_purpose_and_it_is_stated():
    notes = _versions("28532-i20", "18.2.0", allow_other_version=True)
    assert len(notes) == 1 and "comes from spec i00" in notes[0]


def test_an_analysis_needs_a_spec_and_refuses_a_mismatch_on_the_command_line(capsys):
    from openapi_analysis.cli import main

    gen = "data/inputs/generated/ProvMnS/provmns_20260828_232853.yaml"
    old = str(reference_yaml("ProvMnS", "18.2.0"))
    with pytest.raises(SystemExit):
        main(["openapi", str(ROOT / gen), old])                   # no --spec
    assert main(["openapi", str(ROOT / gen), old, "--spec", "28532-i00"]) == 2
    assert "v18.2.0, and the official of 28532-i00 is v17.5.0" in capsys.readouterr().err
    assert main(["openapi", str(ROOT / gen), old, "--spec", "28532-i00",
                 "--allow-other-version"]) == 0
