"""The judge's guarantees — no network: a fake LLM and fake retrieval.

Locks what must hold whatever the LLM answers: every verdict rests on retrieval from
BOTH sources, cites only evidence it was given, an invalid part is never an
improvement, and a cached verdict is read back instead of asking again.
"""

from openapi_analysis.judge.judge import judge_part, number_evidence
from openapi_analysis.judge.prompts import PROMPT_VERSION, SYSTEM, user_message
from openapi_analysis.schemas.judge import Citation, Evidence, JudgeAnswer, Part


def part(**kw):
    return Part(id="generator|g|PATCH /x|responses", evaluation="generator", input="g",
                owner="PATCH /x", aspect="responses", summary="codes differ",
                official={"default": {"description": "error"}},
                generated={"4XX": {"description": "error"}}, **kw)


def ev(source, text="passage"):
    return Evidence(source=source, collection="c", query="q", text=f"{source} {text}")


BOTH = [ev("spec", "a"), ev("spec", "b"), ev("openapi", "c")]


def answer(verdict="improvement", cite=("S1",)):
    return JudgeAnswer(why_different="ranges instead of default", verdict=verdict,
                       spec_3gpp="…", openapi="…", clearer="generated", clearer_why="…",
                       citations=[Citation(evidence_id=i, quote="q") for i in cite])


class FakeLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, msgs):
        self.calls.append(msgs)
        return self.reply


def run(p, evidence, llm, cache_dir=None):
    return judge_part(p, retrieve=lambda _: list(evidence), ask=llm, model="m",
                      cache_dir=cache_dir)


def test_evidence_is_numbered_per_source():
    assert [e.id for e in number_evidence(BOTH)] == ["S1", "S2", "O1"]


def test_without_both_sources_the_llm_is_not_asked():
    for evidence in ([ev("spec")], [ev("openapi")], []):
        llm = FakeLLM(answer())
        v = run(part(), evidence, llm)
        assert v.answer.verdict == "uncertain" and v.decided_by == "no_evidence"
        assert llm.calls == []


def test_a_verdict_citing_nothing_given_is_uncertain():
    v = run(part(), BOTH, FakeLLM(answer("improvement", cite=("S9",))))
    assert v.answer.verdict == "uncertain"
    assert v.overrides and "no valid citation" in v.overrides[0]


def test_citations_to_unknown_ids_are_dropped():
    v = run(part(), BOTH, FakeLLM(answer("error", cite=("S1", "X7"))))
    assert v.answer.verdict == "error"
    assert [c.evidence_id for c in v.answer.citations] == ["S1"]


def test_an_invalid_part_is_never_an_improvement():
    p = part(invalid_issues=["paths./x.patch.requestBody: 'responses' not allowed"])
    for verdict in ("improvement", "equivalent"):
        assert run(p, BOTH, FakeLLM(answer(verdict))).answer.verdict == "error"


def test_a_cached_verdict_is_read_back(tmp_path):
    first = FakeLLM(answer("improvement"))
    v1 = run(part(), BOTH, first, cache_dir=tmp_path)
    second = FakeLLM(answer("error"))
    v2 = run(part(), BOTH, second, cache_dir=tmp_path)
    assert second.calls == [] and v2.answer.verdict == "improvement"
    assert v1.cache_key == v2.cache_key and v1.prompt_version == PROMPT_VERSION


def test_new_evidence_is_a_new_verdict(tmp_path):
    run(part(), BOTH, FakeLLM(answer("improvement")), cache_dir=tmp_path)
    again = FakeLLM(answer("error"))
    v = run(part(), [*BOTH, ev("spec", "new")], again, cache_dir=tmp_path)
    assert len(again.calls) == 1 and v.answer.verdict == "error"


def test_the_prompt_shows_both_sides_the_issues_and_the_evidence_ids():
    p = part(invalid_issues=["bad key"])
    text = user_message(p, number_evidence(BOTH))
    assert "OFFICIAL SIDE:" in text and "GENERATED SIDE:" in text and "4XX" in text
    assert "NOT VALID OPENAPI 3.0" in text and "bad key" in text
    assert "[S1]" in text and "[S2]" in text and "[O1]" in text
    assert "Answer in English." in SYSTEM


# ── one verdict per difference ───────────────────────────────────────────────

def _diffs():
    from openapi_analysis.schemas.judge import Difference

    return [Difference(kind="differing", location="paths./x.patch.responses.200.description",
                       official="OK", generated="Success"),
            Difference(kind="absent", location="paths./x.patch.responses.default", leaves=3),
            Difference(kind="extra", location="paths./x.patch.responses.4XX", leaves=2)]


def test_each_difference_gets_its_own_verdict_and_a_missing_one_is_uncertain():
    from openapi_analysis.schemas.judge import DifferenceVerdict

    reply = answer("error").model_copy(update={"differences": [
        DifferenceVerdict(difference_id="D1", verdict="equivalent", reason="same meaning"),
        DifferenceVerdict(difference_id="d3", verdict="improvement", reason="S1")]})
    v = run(part(differences=_diffs()), BOTH, FakeLLM(reply))
    assert v.difference_verdicts == ["equivalent", "uncertain", "improvement"]
    assert any("D2 not ruled on" in o for o in v.overrides)


def test_a_difference_inside_an_invalid_location_is_never_an_improvement():
    from openapi_analysis.schemas.judge import DifferenceVerdict

    reply = answer("error").model_copy(update={"differences": [
        DifferenceVerdict(difference_id=f"D{i}", verdict="improvement", reason="r")
        for i in (1, 2, 3)]})
    p = part(differences=_diffs(),
             invalid_issues=["paths./x.patch.responses.4XX: 'x' is not allowed"])
    assert run(p, BOTH, FakeLLM(reply)).difference_verdicts == [
        "improvement", "improvement", "error"]


def test_the_prompt_numbers_the_differences():
    msg = user_message(part(differences=_diffs(), focus=["paths./x.patch.responses"]), BOTH)
    assert "D1 ~ paths./x.patch.responses.200.description" in msg
    assert "D3 + paths./x.patch.responses.4XX" in msg
