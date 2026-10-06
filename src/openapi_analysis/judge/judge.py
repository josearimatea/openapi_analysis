"""Judge one part: retrieve → (cache) → LLM → checks → verdict.

Every verdict rests on retrieval (docs/JUDGE_PLAN.md §3): a part reaches the LLM only
with evidence from BOTH the 3GPP spec and the OpenAPI reference; without it, the part
is recorded `uncertain` (decided_by "no_evidence") and the LLM is not called.

After the LLM answers, deterministic checks — recorded in `overrides`:
  - a verdict must cite at least one evidence id it was given, else → uncertain;
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

from openapi_analysis.judge.parts import node_at
from openapi_analysis.judge.prompts import PROMPT_VERSION, messages
from openapi_analysis.schemas.judge import Evidence, JudgeAnswer, Part, Verdict
from openapi_analysis.schemas.rulesbank import now

Retrieve = Callable[[Part], list[Evidence]]
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
    ids = {e.id for e in evidence}
    cited = [c for c in answer.citations if c.evidence_id in ids]
    if not cited:
        overrides.append(f"no valid citation (cited {[c.evidence_id for c in answer.citations]}"
                         f", given {sorted(ids)}): verdict {answer.verdict} -> uncertain")
        answer = answer.model_copy(update={"verdict": "uncertain"})
    elif len(cited) < len(answer.citations):
        overrides.append(f"dropped citations to ids not given: "
                         f"{[c.evidence_id for c in answer.citations if c.evidence_id not in ids]}")
        answer = answer.model_copy(update={"citations": cited})
    if part.invalid_issues and answer.verdict in ("improvement", "equivalent"):
        overrides.append(f"generated side is not valid OpenAPI 3.0: verdict {answer.verdict} "
                         "-> error")
        answer = answer.model_copy(update={"verdict": "error"})
    return answer, overrides


def difference_verdicts(part: Part, answer: JudgeAnswer) -> tuple[list[str], list[str]]:
    """The verdict of each difference, in order, after deterministic floors:
      - a difference the judge did not rule on takes `uncertain`;
      - a difference inside a location reported not valid OpenAPI 3.0 (layer 2), or
        holding one, is never improvement / equivalent -> error;
      - the part's own verdict, when forced to uncertain (no valid citation), applies
        to every difference."""
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
        if v in ("improvement", "equivalent") and any(
                w == d.location or w.startswith((d.location + ".", d.location + "["))
                or d.location.startswith((w + ".", w + "[")) for w in issues):
            notes.append(f"D{i} inside a location not valid OpenAPI 3.0: {v} -> error")
            v = "error"
        out.append(v)
    return out, notes


def _analysed(part: Part, verdict: Verdict) -> Verdict:
    """The verdict with what it was about: the focus and the exact differences, and
    the focus as it is on each side — so a reader compares it with the documents.
    Taken from the part, not the cache (it is not part of the judge's answer)."""
    per_difference, notes = difference_verdicts(part, verdict.answer)
    return verdict.model_copy(update={
        "focus": part.focus, "differences": part.differences,
        "difference_verdicts": per_difference,
        "overrides": verdict.overrides + [n for n in notes if n not in verdict.overrides],
        "official_focus": {loc: node_at(part.official, loc) for loc in part.focus},
        "generated_focus": {loc: node_at(part.generated, loc) for loc in part.focus}})


def judge_part(part: Part, *, retrieve: Retrieve, ask: AskLLM, model: str,
               cache_dir: Path | None = None) -> Verdict:
    """The verdict on one part (see the module docstring)."""
    return _analysed(part, _judge_part(part, retrieve=retrieve, ask=ask, model=model,
                                       cache_dir=cache_dir))


def _judge_part(part: Part, *, retrieve: Retrieve, ask: AskLLM, model: str,
                cache_dir: Path | None = None) -> Verdict:
    evidence = number_evidence(retrieve(part))
    if not (any(e.source == "spec" for e in evidence)
            and any(e.source == "openapi" for e in evidence)):
        return _no_evidence(part, evidence, model)

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
