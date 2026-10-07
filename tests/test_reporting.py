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
    from openapi_analysis.reporting.final import census, render_final
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
                     leaves=leaf_census(report, gen, off),
                     validity_generated=report.validity_generated,
                     validity_official=report.validity_official)
    rows, total = census(jr)
    # the API only — the header (29 values) apart; every value counted once
    assert (total["total"], total["equal"], total["error"], total["not judged"]) == (553, 38, 515, 0)
    assert total["total"] == (total["equal"] + total["changed"] + total["only_official"]
                              + total["only_generated"])
    assert rows["document header"]["total"] == 29
    text = render_final(jr)
    for step in ("RESULT\n", "Valid OpenAPI 3.0 (result 1): NO — 18 issue(s)",
                 "RESULT 1 — OPENAPI VALIDATION", "RESULT 2 — VALUE BY VALUE",
                 "IMPROVEMENTS", "DETAIL, PART BY PART"):
        assert step in text
