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


def test_the_final_analysis_renders_and_adds_up():
    import yaml

    from openapi_analysis.judge.parts import document_owners, generator_parts, leaf_census
    from openapi_analysis.reporting.markdown import render_judge_final
    from openapi_analysis.schemas.judge import JudgeAnswer, JudgeReport, Verdict

    gen = yaml.safe_load((ROOT / "data/inputs/generated/ProvMnS/"
                          "provmns_20260920_194130.yaml").read_text(encoding="utf-8"))
    off = yaml.safe_load(OFFICIAL.read_text(encoding="utf-8"))
    report = evaluate_openapi(gen, off)
    parts = generator_parts(report, gen, off, "g")
    answer = JudgeAnswer(why_different="w", verdict="error", spec_3gpp="", openapi="",
                         clearer="official", clearer_why="c", citations=[])
    verdicts = [Verdict(part_id=p.id, evaluation="generator", input="g", owner=p.owner,
                        aspect=p.aspect, summary=p.summary, answer=answer, evidence=[],
                        decided_by="llm", focus=p.focus, differences=p.differences)
                for p in parts]
    jr = JudgeReport(evaluation="generator", input="g", spec_collection="c", service="ProvMnS",
                     model="m", prompt_version="v", evaluated_at="2026-10-06T00:00:00-03:00",
                     verdicts=verdicts, parts_total=len(parts),
                     owners_total=len(document_owners(report, gen, off)),
                     leaves=leaf_census(report, gen, off))
    md = render_judge_final(jr)
    # the API only: 582 lines in both documents, 29 of them the header (not scored)
    assert "| **total (API)** | 553 | 38 | 0 | 0 | 515 | 0 | 0 | **6.9%** |" in md
    assert "29 lines: equal 6, error 23." in md
    import re

    assert len(re.findall(r"^### \d+\. ", md, re.MULTILINE)) == len(parts)
