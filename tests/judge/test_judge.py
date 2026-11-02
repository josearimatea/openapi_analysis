"""The judge's guarantees — no network: a fake LLM and fake retrieval.

Locks what must hold whatever the LLM answers: every part is searched for and asked
about, a verdict cites only what it was given (S, O, or the CONTEXT C1/C2), an
improvement needs the spec or the reference, an invalid part is never an improvement,
and a cached verdict is read back instead of asking again.
"""

from openapi_analysis.judge.judge import judge_part, number_evidence
from openapi_analysis.judge.prompts import PROMPT_VERSION, SYSTEM, user_message
from openapi_analysis.schemas.judge import (
    Citation,
    DifferenceVerdict,
    Evidence,
    JudgeAnswer,
    Part,
)


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


def test_without_retrieved_evidence_the_llm_is_still_asked_and_may_rest_on_context():
    """judge-v4: the CONTEXT (C1 official, C2 generated) is citable — enough to rule two
    sides equivalent, never an improvement."""
    llm = FakeLLM(answer("equivalent", cite=("C1", "C2")))
    v = run(part(), [], llm)
    assert len(llm.calls) == 1 and v.decided_by == "llm"
    assert v.answer.verdict == "equivalent" and not v.overrides


def test_an_improvement_resting_on_the_context_alone_is_uncertain():
    v = run(part(), BOTH, FakeLLM(answer("improvement", cite=("C2",))))
    assert v.answer.verdict == "uncertain"
    assert any("cites only the CONTEXT" in o for o in v.overrides)
    v = run(part(), BOTH, FakeLLM(answer("improvement", cite=("C2", "O1"))))
    assert v.answer.verdict == "improvement"                       # with the reference: kept

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
    assert "OFFICIAL SIDE [C1]:" in text and "GENERATED SIDE [C2]:" in text and "4XX" in text
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
        "equivalent", "improvement", "error"]        # D1 is a description: prose never counts


def _ruling(kind, location, verdict):
    from openapi_analysis.schemas.judge import Difference, DifferenceVerdict

    d = Difference(kind=kind, location=location, official="a", generated="b")
    return d, answer(verdict).model_copy(update={"differences": [
        DifferenceVerdict(difference_id="D1", verdict=verdict, reason="r")]})


def test_what_only_the_generated_has_is_never_equivalent():
    for location, given, final in (("paths./x.get.operationId", "equivalent", "useful"),
                                   ("paths./x.get.operationId", "useful", "useful"),
                                   ("paths./x.get.operationId", "improvement", "useful"),
                                   ("paths./x.get.responses.204", "improvement", "improvement"),
                                   ("paths./x.get.operationId", "error", "error"),
                                   ("paths./x.get.description", "error", "useful")):
        d, reply = _ruling("extra", location, given)
        assert run(part(differences=[d]), BOTH, FakeLLM(reply)).difference_verdicts == [final]


def test_the_part_follows_a_ruling_changed_to_useful():
    d, reply = _ruling("extra", "paths./x.get.operationId", "equivalent")
    reply = reply.model_copy(update={"verdict": "equivalent"})
    assert run(part(differences=[d]), BOTH, FakeLLM(reply)).answer.verdict == "useful"


def test_a_duplicate_is_never_useful():
    d, reply = _ruling("duplicate", "paths./copy.get", "useful")
    assert run(part(differences=[d]), BOTH, FakeLLM(reply)).difference_verdicts == ["error"]


def test_useful_inside_an_invalid_location_is_an_error():
    d, reply = _ruling("extra", "paths./x.get.operationId", "useful")
    p = part(differences=[d], invalid_issues=["paths./x.get.operationId: bad"])
    assert run(p, BOTH, FakeLLM(reply)).difference_verdicts == ["error"]


def test_a_prose_difference_on_both_sides_stays_equivalent():
    d, reply = _ruling("differing", "paths./x.get.description", "error")
    assert run(part(differences=[d]), BOTH, FakeLLM(reply)).difference_verdicts == ["equivalent"]


def test_what_is_known_of_a_move_is_not_left_to_the_llm():
    from openapi_analysis.schemas.judge import Difference, DifferenceVerdict

    for known, given, final in (("same_content", "improvement", "equivalent"),
                               ("same_content", "error", "equivalent"),
                               ("same_content", "uncertain", "equivalent"),
                               ("callback_to_path", "improvement", "error"),
                               ("beside_ref", "equivalent", "error"),
                               ("empty_schema", "error", "equivalent"),
                               ("", "improvement", "improvement")):
        d = Difference(kind="moved", location="paths./a.post", official="o", generated="g", known=known)
        reply = answer(given).model_copy(update={"differences": [
            DifferenceVerdict(difference_id="D1", verdict=given, reason="r")]})
        v = run(part(differences=[d]), BOTH, FakeLLM(reply))
        assert v.difference_verdicts == [final] and v.answer.verdict == final


def test_the_path_parameters_of_a_callback_declared_as_a_path_are_no_improvement():
    from openapi_analysis.schemas.judge import Difference, DifferenceVerdict

    for where, final in (("path", "useful"), ("query", "improvement")):
        generated = {"paths": {"/a": {"post": {"parameters": [{"name": "a", "in": where}]}}}}
        move = Difference(kind="moved", location="paths./a.post", official="o", generated="g",
                          known="callback_to_path")
        extra = Difference(kind="extra", location="paths./a.post.parameters", generated="g")
        reply = answer("improvement").model_copy(update={"differences": [
            DifferenceVerdict(difference_id="D1", verdict="error", reason="r"),
            DifferenceVerdict(difference_id="D2", verdict="improvement", reason="r")]})
        p = part(differences=[move, extra]).model_copy(update={"generated": generated})
        assert run(p, BOTH, FakeLLM(reply)).difference_verdicts == ["error", final]


def test_a_property_named_like_prose_is_not_prose():
    from openapi_analysis.judge.parts import is_prose
    from openapi_analysis.schemas.judge import Difference

    for text in ("paths./x.get.summary", "info.title", "servers[0].description",
                 "paths./x.get.responses.default.description",
                 "components.schemas.N.properties.title.description",
                 "paths./x.get.parameters[in=query,name=f].description"):
        assert is_prose(text), text
    for field in ("components.schemas.N.properties.title",
                  "components.schemas.N.properties.description",
                  "components.schemas.description", "paths./x.get.operationId",
                  "servers[0].variables.description", "components.schemas.N.example.title",
                  "components.schemas.N.properties.properties.properties.summary"):
        assert not is_prose(field), field
    d = Difference(kind="absent", location="components.schemas.N.properties.title")
    reply = answer("error").model_copy(update={"differences": [
        DifferenceVerdict(difference_id="D1", verdict="error", reason="r")]})
    assert run(part(differences=[d]), BOTH, FakeLLM(reply)).difference_verdicts == ["error"]


def test_the_reason_comes_before_the_verdict():
    fields = list(DifferenceVerdict.model_fields)
    assert fields.index("reason") < fields.index("verdict")
    fields = list(JudgeAnswer.model_fields)
    assert fields.index("differences") < fields.index("verdict") and fields[-1] == "verdict"
    assert "Think before you rule" in SYSTEM


def test_a_known_fact_is_told_on_the_line_of_its_difference():
    from openapi_analysis.schemas.judge import Difference

    d = Difference(kind="extra", location="paths./x.schema.type", known="beside_ref")
    assert "known: this key is beside a $ref" in user_message(part(differences=[d]), BOTH)


def test_the_part_follows_its_differences():
    d, reply = _ruling("differing", "paths./x.get.required", "error")
    reply = reply.model_copy(update={"verdict": "improvement"})
    assert run(part(differences=[d]), BOTH, FakeLLM(reply)).answer.verdict == "error"


def test_the_rules_of_required_and_of_oas_facts_are_in_the_prompt():
    assert "M alone neither justifies nor condemns" in SYSTEM
    assert "SHALL be ignored" in SYSTEM
    assert "not by codes nobody declared" in SYSTEM
    assert "never cutting" in SYSTEM


def test_the_prompt_numbers_the_differences():
    msg = user_message(part(differences=_diffs(), focus=["paths./x.patch.responses"]), BOTH)
    assert "D1 ~ paths./x.patch.responses.200.description" in msg
    assert "D3 + paths./x.patch.responses.4XX" in msg
