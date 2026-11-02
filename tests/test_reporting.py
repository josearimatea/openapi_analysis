"""The text and Markdown reports render on the real inputs (no LLM)."""

from openapi_analysis.config.paths import ROOT, reference_yaml
from openapi_analysis.reporting.text import render_openapi, render_rulesbank
from openapi_analysis.services import evaluate_openapi, evaluate_rules_bank

OFFICIAL = reference_yaml("ProvMnS", "18.2.0")


def test_layer_1_and_2_reports_render():
    gen = ROOT / "data/inputs/generated/ProvMnS/provmns_20260920_194130.yaml"
    bank = ROOT / "data/inputs/rulesbank/ProvMnS/rules_bank_28532-i20_full_20260915_214107.json"
    assert "%" in render_openapi(evaluate_openapi(gen, OFFICIAL))
    assert "%" in render_rulesbank(evaluate_rules_bank(bank, OFFICIAL))


def test_the_final_analysis_renders_the_two_views():
    import yaml

    from openapi_analysis.judge.group_parts import group_parts, grouping_counts, views
    from openapi_analysis.openapi.alignment import Aligner
    from openapi_analysis.reporting.final import correct, render_final
    from openapi_analysis.schemas.judge import JudgeAnswer, JudgeReport, Verdict

    gen = yaml.safe_load((ROOT / "data/inputs/generated/ProvMnS/"
                          "provmns_20260828_232853.yaml").read_text(encoding="utf-8"))
    off = yaml.safe_load(OFFICIAL.read_text(encoding="utf-8"))
    report = evaluate_openapi(gen, off)
    a = Aligner(off, gen)
    a.deterministic()
    parts, part_of = group_parts(a, "g")
    answer = JudgeAnswer(why_different="w", verdict="error", spec_3gpp="", openapi="",
                         clearer="official", clearer_why="c", citations=[])
    verdicts = [Verdict(part_id=p.id, evaluation="generator", input="g", owner=p.owner,
                        aspect=p.aspect, summary=p.summary, answer=answer, evidence=[],
                        decided_by="llm", focus=p.focus, differences=p.differences,
                        difference_verdicts=["error"] * len(p.differences))
                for p in parts]
    jr = JudgeReport(evaluation="generator", input="g", spec_collection="c", service="ProvMnS",
                     model="m", prompt_version="v", evaluated_at="2026-10-29T00:00:00-03:00",
                     verdicts=verdicts, parts_total=len(parts),
                     validity_generated=report.validity_generated,
                     validity_official=report.validity_official,
                     views=views(a, parts, part_of, verdicts), grouping=grouping_counts(a))
    # every difference ruled an error: what is right is only what is the same
    o, g = jr.views["official"], jr.views["generated"]
    assert correct(o, "official") == o["same"] and correct(g, "generated") == g["same"]
    assert o["missing"] > 0 and g["extra wrong"] > 0 and o["undecided"] == 0
    text = render_final(jr)
    for step in ("RESULT\n", "Valid OpenAPI 3.0: YES",
                 "1. HOW MUCH OF THE OFFICIAL THE GENERATED REPRODUCES",
                 "2. HOW MUCH OF THE GENERATED IS RIGHT", "REPRODUCED CORRECTLY",
                 "IMPROVEMENTS", "RESULT 1 — OPENAPI VALIDATION", "GROUPINGS THE JUDGE DISPUTED",
                 "DETAIL, PART BY PART"):
        assert step in text


def test_a_ruling_decided_by_a_rule_shows_the_rule_not_the_judges_text():
    from openapi_analysis.reporting.final import _reasons
    from openapi_analysis.schemas.judge import DifferenceVerdict, JudgeAnswer, Verdict

    answer = JudgeAnswer(why_different="-", verdict="error", spec_3gpp="", openapi="", clearer="same",
                         clearer_why="-", citations=[], differences=[
        DifferenceVerdict(difference_id="D1", verdict="error", reason="this loses the contract"),
        DifferenceVerdict(difference_id="D2", verdict="error", reason="kept")])
    v = Verdict(part_id="p", evaluation="generator", input="i", owner="o", aspect="a", summary="s",
                answer=answer, evidence=[], decided_by="llm",
                overrides=["D1 same_content: error -> equivalent"])
    why = _reasons(v)
    assert "identical" in why["D1"] and "loses" not in why["D1"] and why["D2"] == "kept"


def test_what_a_rule_decides_shows_the_rule_even_when_the_judge_agreed():
    from openapi_analysis.reporting.final import _reasons
    from openapi_analysis.schemas.judge import Difference, DifferenceVerdict, JudgeAnswer, Verdict

    answer = JudgeAnswer(why_different="-", verdict="error", spec_3gpp="", openapi="", clearer="same",
                         clearer_why="-", citations=[], differences=[
        DifferenceVerdict(difference_id="D1", verdict="error", reason="makes the document invalid")])
    v = Verdict(part_id="p", evaluation="generator", input="i", owner="o", aspect="a", summary="s",
                answer=answer, evidence=[], decided_by="llm",
                differences=[Difference(kind="extra", location="a.type", known="beside_ref")])
    assert "not allowed by that rule" in _reasons(v)["D1"]
    assert "invalid" not in _reasons(v)["D1"]


def test_a_reason_names_what_its_ids_stand_for():
    from openapi_analysis.reporting.final import _named, _sources
    from openapi_analysis.schemas.judge import Citation, Evidence, JudgeAnswer, Verdict

    answer = JudgeAnswer(why_different="-", verdict="error", spec_3gpp="", openapi="", clearer="same",
                         clearer_why="-", citations=[Citation(evidence_id="S1", quote="the row")])
    evidence = [Evidence(id="S1", source="spec", collection="c", query="q", text="t", clause="12.1.1"),
                Evidence(id="O1", source="openapi", collection="c", query="q", text="t", title="Schema Object")]
    v = Verdict(part_id="p", evaluation="generator", input="i", owner="o", aspect="a", summary="s",
                answer=answer, evidence=evidence, decided_by="llm")
    assert _named(v, "see S1, O1 and C2; S9") == (
        "see S1 [clause 12.1.1], O1 [Schema Object] and C2 [generated]; S9")
    assert any("S1 [clause 12.1.1]: the row" in line for line in _sources(v))
