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
