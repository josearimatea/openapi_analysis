"""The judge's prompt (layer 3). Versioned: PROMPT_VERSION is part of every verdict's
cache key, so changing the prompt produces a new measurement instead of silently
reusing verdicts given under the old one. Bump it on any change to this file.
"""

from __future__ import annotations

import yaml

from openapi_analysis.schemas.judge import Difference, Evidence, Part

PROMPT_VERSION = "judge-v3"

SYSTEM = """\
You are a reviewer of OpenAPI 3.0 documents derived from 3GPP specifications. You judge
ONE part of a document at a time: a place where the generated side differs from the
official 3GPP OpenAPI document.

You are given:
- CONTEXT: the whole owner of the part — the whole operation, callback, schema or block —
  on the official side and on the generated side, exactly as in the documents. It is
  there so you understand the part; it is not what you judge.
- FOCUS: what you judge — the locations inside the owner, and the exact list of
  differences, computed deterministically:
    "- location"  present in the official document only (absent from the generated one)
    "+ location"  present in the generated document only (extra)
    "~ location"  present in both, with another value (both values given)
  Every other line of the context is equal on both sides, or is judged in another part.
- evidence: passages of the 3GPP specification (ids S1, S2, ...) and of the OpenAPI 3.0
  reference (ids O1, O2, ...), retrieved for this part.

Read the CONTEXT to understand the part. Judge EACH difference (D1, D2, ...) on its own
— a reworded description and a wrong $ref in the same part get different verdicts —
then the FOCUS as a whole. Answer three questions, using ONLY the evidence given:
1. Why does the generated side differ from the official one? Name the probable cause:
   a different value, a different address (declared at another level or location), or a
   different structure (a composition flattened, a block moved, a key that is not allowed).
2. Is the difference an error or an improvement?
   - error: the generated side is wrong — it contradicts the 3GPP spec, breaks the OpenAPI
     reference, or loses information the official side carries.
   - improvement: the generated side is better than the official one — the spec or the
     reference supports it more, or the official side is the one in error.
   - equivalent: a different form with the same meaning and the same clarity.
   - uncertain: the evidence does not decide. Prefer uncertain to a guess.
   The official document can be wrong or out of date; do not assume it is right.
3. Which version is easier to understand for a reader of the API: official, generated,
   or same — and why.

Rules:
- Give one ruling per difference, by its id, for every difference listed. The verdict of
  the part as a whole is the most serious one among them that matters to a reader of the
  API (an error in one difference makes the part an error).
- A difference in prose only (a description, summary or title worded differently) is
  equivalent when it says the same thing, improvement when it is clearer or more precise,
  error when it says something false or loses information.
- Base every statement on the evidence. Cite the evidence ids you rely on (at least one),
  quoting the short passage that supports the verdict. Never cite an id you were not given.
- If the spec evidence does not address the part, say so; do not fill the gap with what
  you believe 3GPP usually does.
- A side reported as "not valid OpenAPI 3.0" breaks the OpenAPI format: that side is in
  error, whatever else is true.
- Answer in English.
"""


def _dump(node: object) -> str:
    """A side of the context, whole — never truncated: the judge reads the entire owner."""
    if node is None:
        return "(absent)"
    return yaml.safe_dump(node, sort_keys=False, allow_unicode=True, width=100)


def _evidence_block(e: Evidence, limit: int = 2500) -> str:
    if e.source == "spec":
        head = f"[{e.id}] 3GPP spec, clause {e.clause or '?'} — {e.title}"
    else:
        head = f"[{e.id}] OpenAPI 3.0 reference — {e.title or 'passage'}"
    text = e.text if len(e.text) <= limit else e.text[:limit] + " ... (truncated)"
    return f"{head}\n{text}"


def difference_line(d: Difference) -> str:
    """One difference as the judge and the report show it."""
    if d.kind == "differing":
        return (f"~ {d.location}\n    official:  {_inline(d.official)}"
                f"\n    generated: {_inline(d.generated)}")
    mark = "-" if d.kind == "absent" else "+"
    return f"{mark} {d.location}" + (f"  ({d.leaves} leaves)" if d.leaves > 1 else "")


def _inline(value: object, limit: int = 300) -> str:
    text = yaml.safe_dump(value, default_flow_style=True, width=10_000).strip()
    text = text.removesuffix("\n...").strip()
    return text if len(text) <= limit else text[:limit] + " ..."


def user_message(part: Part, evidence: list[Evidence]) -> str:
    """The part and its evidence, as the judge reads them."""
    what = ("a generated OpenAPI document" if part.evaluation == "generator"
            else "a rules bank (rules extracted from the 3GPP spec to build the document)")
    other = "GENERATED" if part.evaluation == "generator" else "RULES BANK"
    lines = [
        f"EVALUATED: {what} — {part.input}",
        f"PART: {part.owner} — {part.aspect}",
        f"SUMMARY: {part.summary}",
        "",
        "CONTEXT — OFFICIAL SIDE:",
        _dump(part.official),
        "",
        f"CONTEXT — {other} SIDE:",
        _dump(part.generated),
    ]
    if part.focus or part.differences:
        lines += ["", "FOCUS — judge only this:"]
        lines += [f"  at {loc}" for loc in part.focus]
        if part.differences:
            lines += ["", "DIFFERENCES:", *(f"D{i} {difference_line(d)}"
                                            for i, d in enumerate(part.differences, 1))]
    if part.invalid_issues:
        lines += ["", f"THE {other} SIDE IS NOT VALID OPENAPI 3.0 (layer-2 validation):",
                  *[f"- {i}" for i in part.invalid_issues]]
    lines += ["", "EVIDENCE:", *(_evidence_block(e) + "\n" for e in evidence)]
    return "\n".join(lines)


def messages(part: Part, evidence: list[Evidence]) -> list[tuple[str, str]]:
    return [("system", SYSTEM), ("human", user_message(part, evidence))]
