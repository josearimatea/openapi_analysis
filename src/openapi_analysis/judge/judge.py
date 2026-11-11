"""Judge one part: retrieve → (cache) → LLM → checks → verdict.

Every part is searched for in the 3GPP spec and the OpenAPI reference (docs/
JUDGE_PLAN.md §3), and the LLM is always asked: besides the retrieved passages (S, O)
it may cite the part's CONTEXT — the official side C1, the generated side C2 — which is
enough to see that two sides mean the same thing (judge-v4). Before judge-v4 a part
without evidence from both sources was ruled `uncertain` without asking.

After the LLM answers, deterministic checks — recorded in `overrides`:
  - a verdict must cite at least one id it was given (S, O, C1, C2), else → uncertain;
  - an improvement must cite the spec or the OpenAPI reference: one resting on the
    CONTEXT alone → uncertain (being different is not being better);
  - a part whose generated side is not valid OpenAPI 3.0 (layer 2) is never an
    improvement or equivalent → error.

Verdicts are cached one file per part under data/judgements/, keyed on the part, the
evidence texts, the model and PROMPT_VERSION: a rerun reads them back; a change in
any of these makes a new verdict instead of reusing the old one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

from openapi_analysis.judge.parts import _keys, is_prose, node_at
from openapi_analysis.judge.prompts import PROMPT_VERSION, messages
from openapi_analysis.schemas.judge import Difference, Evidence, JudgeAnswer, Part, Verdict
from openapi_analysis.schemas.rulesbank import now

Retrieve = Callable[[Part], list[Evidence]]
# the two sides of the part's CONTEXT, citable as evidence (prompts.py, judge-v4)
CONTEXT_IDS = {"C1", "C2"}
# what is known of a difference without reading it (Difference.known)
KNOWN_VERDICT = {"same_content": "equivalent", "callback_to_path": "error", "beside_ref": "error",
                 "empty_schema": "equivalent"}
_SEVERITY = ("error", "uncertain", "improvement", "useful", "equivalent")
AskLLM = Callable[[list[tuple[str, str]]], JudgeAnswer]


def number_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Give each chunk the id the judge sees: S1, S2 … (spec), O1, O2 … (reference)."""
    counters = {"spec": 0, "openapi": 0}
    out = []
    for e in evidence:
        counters[e.source] += 1
        out.append(e.model_copy(update={"id": f"{'S' if e.source == 'spec' else 'O'}"
                                              f"{counters[e.source]}"}))
    return out


def cache_key(part: Part, evidence: list[Evidence], model: str) -> str:
    payload = {"part": part.model_dump(mode="json"), "evidence": [e.text for e in evidence],
               "model": model, "prompt": PROMPT_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _cache_file(cache_dir: Path, part: Part, key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", part.input)[:80]
    return cache_dir / part.evaluation / safe / f"{key}.json"


def _no_evidence(part: Part, evidence: list[Evidence], model: str) -> Verdict:
    missing = [s for s in ("spec", "openapi") if not any(e.source == s for e in evidence)]
    reason = f"no evidence retrieved from: {', '.join(missing)}"
    return Verdict(
        part_id=part.id, evaluation=part.evaluation, input=part.input, owner=part.owner,
        aspect=part.aspect, summary=part.summary, evidence=evidence,
        answer=JudgeAnswer(why_different=reason, verdict="uncertain", spec_3gpp="",
                           openapi="", clearer="same", clearer_why="not judged",
                           citations=[]),
        decided_by="no_evidence", model=model, prompt_version=PROMPT_VERSION,
        judged_at=now())


def _check(part: Part, answer: JudgeAnswer, evidence: list[Evidence]) -> tuple[JudgeAnswer,
                                                                             list[str]]:
    """Deterministic floors on the LLM's answer."""
    overrides: list[str] = []
    ids = {e.id for e in evidence} | CONTEXT_IDS
    cited = [c for c in answer.citations if c.evidence_id in ids]
    if not cited:
        overrides.append(f"no valid citation (cited {[c.evidence_id for c in answer.citations]}"
                         f", given {sorted(ids)}): verdict {answer.verdict} -> uncertain")
        answer = answer.model_copy(update={"verdict": "uncertain"})
    elif len(cited) < len(answer.citations):
        overrides.append(f"dropped citations to ids not given: "
                         f"{[c.evidence_id for c in answer.citations if c.evidence_id not in ids]}")
        answer = answer.model_copy(update={"citations": cited})
    external = [c for c in answer.citations if c.evidence_id not in CONTEXT_IDS]
    if answer.verdict == "improvement" and answer.citations and not external:
        overrides.append("improvement cites only the CONTEXT (C1/C2), no spec or OpenAPI "
                         "evidence: improvement -> uncertain")
        answer = answer.model_copy(update={"verdict": "uncertain"})
    if part.invalid_issues and answer.verdict in ("improvement", "equivalent", "useful"):
        overrides.append(f"generated side is not valid OpenAPI 3.0: verdict {answer.verdict} "
                         "-> error")
        answer = answer.model_copy(update={"verdict": "error"})
    return answer, overrides


def _of_callback_path(part: Part, d: Difference) -> bool:
    """Whether this extra holds only the path parameters of a callback declared as a path."""
    if d.kind != "extra" or not any(c.known == "callback_to_path"
                                    and d.location == f"{c.location}.parameters"
                                    for c in part.differences):
        return False
    held = node_at(part.generated, d.location)
    return isinstance(held, list) and all(isinstance(p, dict) and p.get("in") == "path"
                                          for p in held)


def difference_verdicts(part: Part, answer: JudgeAnswer) -> tuple[list[str], list[str]]:
    """The verdict of each difference, in order, after deterministic floors:
      - a difference the judge did not rule on takes `uncertain`;
      - a difference inside a location reported not valid OpenAPI 3.0 (layer 2), or
        holding one, is never improvement / equivalent -> error;
      - the part's own verdict, when forced to uncertain (no valid citation), applies
        to every difference;
      - a difference in prose only (description, summary, title) is always equivalent:
        not part of the contract, never an error or an improvement;
      - what only the generated side has cannot be equivalent, which needs both sides:
        equivalent there is useful;
      - what is known without reading it (KNOWN_VERDICT) takes its verdict: the same
        content under another key, a callback declared as a path, a key beside a $ref;
      - an operationId the official lacks is never an improvement: OpenAPI makes it
        optional, so nothing calls for it;
      - the path parameters of a callback declared as a path are never an improvement: they
        exist only because of that move, already an error;
      - a duplicate (a further declaration of what the generated document already
        declares) is never improvement / equivalent -> error, unless the judge says it
        does not belong to the group (it is then judged again on its own)."""
    notes: list[str] = []
    given = {d.difference_id.strip().upper(): d.verdict for d in answer.differences}
    issues = [i.partition(": ")[0] for i in part.invalid_issues]
    out = []
    for i, d in enumerate(part.differences, 1):
        v = given.get(f"D{i}")
        if v is None:
            notes.append(f"D{i} not ruled on -> uncertain")
            v = "uncertain"
        if answer.verdict == "uncertain" and v != "uncertain" and not answer.citations:
            v = "uncertain"
        fixed = KNOWN_VERDICT.get(d.known)
        if fixed and v != fixed:
            notes.append(f"D{i} {d.known}: {v} -> {fixed}")
            v = fixed
        if d.kind == "extra" and _keys(d.location)[-1] == "operationId" and v == "improvement":
            notes.append(f"D{i} operationId: improvement -> useful")
            v = "useful"
        if v == "improvement" and _of_callback_path(part, d):
            notes.append(f"D{i} path parameters of a callback declared as a path: "
                         "improvement -> useful")
            v = "useful"
        if v in ("improvement", "equivalent", "useful") and any(
                w == d.location or w.startswith((d.location + ".", d.location + "["))
                or d.location.startswith((w + ".", w + "[")) for w in issues):
            notes.append(f"D{i} inside a location not valid OpenAPI 3.0: {v} -> error")
            v = "error"
        if is_prose(d.location) and d.kind != "duplicate" and v not in ("equivalent", "useful"):
            notes.append(f"D{i} prose only: {v} -> equivalent")
            v = "equivalent"
        if d.kind != "extra" and v == "useful":
            notes.append(f"D{i} on the official side too: useful -> equivalent")
            v = "equivalent"
        if d.kind == "extra" and v == "equivalent":
            notes.append(f"D{i} only in the generated: equivalent -> useful")
            v = "useful"
        if d.kind == "duplicate" and v in ("improvement", "equivalent", "useful") \
                and d.location not in answer.wrongly_grouped:
            notes.append(f"D{i} a second declaration of the same object: {v} -> error")
            v = "error"
        out.append(v)
    return out, notes


def _analysed(part: Part, verdict: Verdict) -> Verdict:
    """The verdict with what it was about: the focus and the exact differences, and
    the focus as it is on each side — so a reader compares it with the documents.
    Taken from the part, not the cache (it is not part of the judge's answer)."""
    per_difference, notes = difference_verdicts(part, verdict.answer)
    if per_difference:                                     # the part's verdict follows them
        worst = next(v for v in _SEVERITY if v in per_difference)
        verdict = verdict.model_copy(update={
            "answer": verdict.answer.model_copy(update={"verdict": worst})})
    return verdict.model_copy(update={
        "focus": part.focus, "differences": part.differences,
        "difference_verdicts": per_difference,
        "overrides": verdict.overrides + [n for n in notes if n not in verdict.overrides],
        "official_focus": (_rule_side(part.official) if part.evaluation == "rulesbank"
                           else {loc: node_at(part.official, loc) for loc in part.focus}),
        "generated_focus": (_rule_side(part.generated) if part.evaluation == "rulesbank"
                            else {loc: node_at(part.generated, loc) for loc in part.focus})})


def _rule_side(side: object) -> dict:
    """A rules-bank part has no focus: the rule itself is what was judged (the official
    rule, or the bank rule(s)) — kept with the verdict for the report."""
    if side is None:
        return {}
    return {"rule": side}


def judge_part(part: Part, *, retrieve: Retrieve, ask: AskLLM, model: str,
               cache_dir: Path | None = None) -> Verdict:
    """The verdict on one part (see the module docstring)."""
    return _analysed(part, _judge_part(part, retrieve=retrieve, ask=ask, model=model,
                                       cache_dir=cache_dir))


def rule_verdict(part: Part, verdict: str, reason: str,
                 per_rule: dict[str, str] | None = None) -> Verdict:
    """The verdict of a part decided by a rule (judge/rules.py): no evidence read, no LLM,
    nothing cached — the rule gives it again on every run."""
    return _analysed(part, Verdict(
        part_id=part.id, evaluation=part.evaluation, input=part.input, owner=part.owner,
        aspect=part.aspect, summary=part.summary, evidence=[],
        answer=JudgeAnswer(why_different=reason, verdict=verdict, spec_3gpp="",
                           openapi="", clearer="same", clearer_why="not judged (a rule)",
                           citations=[]),
        rule_verdicts=dict(per_rule or {}), decided_by="rule", judged_at=now()))


_RULE_INDEX = re.compile(r"\(rule #(\d+)\)")


def with_rule_verdicts(part: Part, verdict: Verdict, fixed: dict[str, str]) -> Verdict:
    """A part the judge ruled on in part only (an "error responses" part): each rule takes
    the verdict its form fixed, or the judge's on its difference ("D1 4XX (rule #12)"); the
    part's verdict is the most serious of them."""
    per = dict(fixed)
    for d, v in zip(part.differences, verdict.difference_verdicts, strict=False):
        m = _RULE_INDEX.search(d.location)
        if m:
            per[m.group(1)] = v
    given = [v for v in per.values() if v and v != "same"]
    worst = next((v for v in _SEVERITY if v in given), verdict.answer.verdict)
    return verdict.model_copy(update={
        "rule_verdicts": per,
        "answer": verdict.answer.model_copy(update={"verdict": worst}),
        "overrides": verdict.overrides + [f"decided by the form (a rule): {fixed}"]
                     if fixed else verdict.overrides})


def _judge_part(part: Part, *, retrieve: Retrieve, ask: AskLLM, model: str,
                cache_dir: Path | None = None) -> Verdict:
    evidence = number_evidence(retrieve(part))     # the LLM is asked even with none:
    # the CONTEXT (C1/C2) can decide equivalence, never an improvement (see _check)

    key = cache_key(part, evidence, model)
    path = _cache_file(cache_dir, part, key) if cache_dir else None
    if path is not None and path.is_file():
        return Verdict.model_validate_json(path.read_text(encoding="utf-8"))

    answer, overrides = _check(part, ask(messages(part, evidence)), evidence)
    verdict = Verdict(
        part_id=part.id, evaluation=part.evaluation, input=part.input, owner=part.owner,
        aspect=part.aspect, summary=part.summary, answer=answer, evidence=evidence,
        decided_by="llm", overrides=overrides, model=model, prompt_version=PROMPT_VERSION,
        cache_key=key, judged_at=now())
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(verdict.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return verdict


def default_ask() -> AskLLM:
    """The real judge: gpt-5.6-luna (config/judge_settings), structured output."""
    from openapi_analysis.config.llm_config import get_llm

    structured = get_llm().with_structured_output(JudgeAnswer)

    def ask(msgs: list[tuple[str, str]]) -> JudgeAnswer:
        return structured.invoke(msgs)

    return ask
