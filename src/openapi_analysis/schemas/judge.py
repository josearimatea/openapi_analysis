"""The judge's records (layer 3, docs/JUDGE_PLAN.md).

A Part is one divergence, cut small enough that a retrieval can be aimed at it:
one bank rule (rules bank evaluation), or one aspect of one owner — an operation's
responses, a schema's definition — (generator evaluation). It carries the whole
owner on both sides as context, the exact differences it is about, a deterministic
summary, and the hints the retrieval needs.

A Verdict is the judge's answer on one part, with the evidence it read (spec and
OpenAPI reference chunks, each under the id the judge saw) — cached and auditable.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from openapi_analysis.schemas.openapi import ValidityReport
from openapi_analysis.schemas.rulesbank import SourceInfo

VerdictLabel = Literal["error", "improvement", "equivalent", "uncertain"]
Clearer = Literal["official", "generated", "same"]


class SearchHints(BaseModel):
    """What the retrieval is aimed with — taken from the part, never guessed."""
    clause: str = ""                 # 3GPP clause the bank rule came from ("12.1.3.1.4")
    path: str = ""                   # "/{className}={id}"
    method: str = ""                 # "patch"
    schemas: list[str] = Field(default_factory=list)       # schema names involved
    external_refs: list[str] = Field(default_factory=list)  # "TS28623_ComDefs.yaml#/…"
    terms: list[str] = Field(default_factory=list)          # extra words (operation, field)


class Evidence(BaseModel):
    """One retrieved chunk the judge reads — recorded so a verdict can be audited."""
    id: str = ""                     # the id the judge sees and cites ("S1", "O2")
    source: Literal["spec", "openapi"]
    collection: str
    query: str
    filters: dict[str, str] = Field(default_factory=dict)
    clause: str = ""                 # spec chunks: the clause it comes from
    title: str = ""
    text: str


class Difference(BaseModel):
    """One place where the two sides differ, located in the document.

    absent / extra: a whole subtree on one side only (`leaves` counts its leaves);
    differing: both sides have it with another value (both values given).
    """
    kind: Literal["absent", "differing", "extra"]
    location: str                    # display path in the document ("paths./x.patch.responses.200")
    leaves: int = 1
    official: Any = None             # differing only
    generated: Any = None


class Part(BaseModel):
    """One divergence to be judged.

    The judge gets the WHOLE owner as context — the whole operation, callback, schema
    or block, official and generated, exactly as in the documents — and judges only
    the `focus`, whose exact `differences` were computed deterministically.
    """
    id: str                          # stable — the verdict cache is keyed on it
    evaluation: Literal["rulesbank", "generator"]
    input: str                       # the evaluated bank / generated document (label)
    owner: str                       # "PATCH /x", "PATH /x", "SCHEMA Name", or a rule address
    aspect: str                      # what diverges (see judge/parts.py)
    summary: str                     # deterministic one-line description of the divergence
    focus: list[str] = Field(default_factory=list)        # locations judged, inside the owner
    differences: list[Difference] = Field(default_factory=list)  # exactly what differs
    diff_terms: list[str] = Field(default_factory=list)   # the values in play (codes,
                                     # parameter / property names, media types)
    official: Any = None             # the whole owner, official side (None: absent there)
    generated: Any = None            # the whole owner, generated / bank side
    hints: SearchHints = Field(default_factory=SearchHints)
    invalid_issues: list[str] = Field(default_factory=list)  # layer-2 issues inside it:
                                     # not valid OpenAPI 3.0


# ── the judge's answer and the recorded verdict ──────────────────────────────

class Citation(BaseModel):
    """A piece of evidence the judge relied on, by the id it was given ("S2", "O1")."""
    evidence_id: str = Field(description="Id of what you rely on, as given: 'S2' (3GPP spec), "
                                         "'O1' (OpenAPI reference), 'C1' (the official side "
                                         "of the CONTEXT) or 'C2' (the generated side).")
    quote: str = Field(description="The short passage supporting the verdict, copied as "
                                   "written (from the CONTEXT: the YAML line).")


class DifferenceVerdict(BaseModel):
    """The judge's ruling on ONE difference of the part (structured output)."""
    difference_id: str = Field(description="Id of the difference you rule on, e.g. 'D1', "
                                           "exactly as given.")
    verdict: VerdictLabel = Field(description="error | improvement | equivalent | uncertain, "
                                              "for THIS difference alone, with the same "
                                              "meanings as the part's verdict.")
    reason: str = Field(description="One or two sentences: why this verdict, naming the "
                                    "evidence ids it rests on.")


class JudgeAnswer(BaseModel):
    """What the LLM returns for one part (structured output)."""
    why_different: str = Field(description="Why the generated side differs from the official "
                                           "one: the probable cause, whether the difference is "
                                           "in a value, an address (level, location) or a "
                                           "structure.")
    verdict: VerdictLabel = Field(description="error: the generated side is wrong. improvement: "
                                              "the generated side is better than the official "
                                              "one (needs S or O evidence). equivalent: different "
                                              "form, same meaning (the CONTEXT may suffice). "
                                              "uncertain: the meaning changes and nothing given "
                                              "decides.")
    spec_3gpp: str = Field(description="What the 3GPP spec evidence says about this part.")
    openapi: str = Field(description="What the OpenAPI reference evidence allows or recommends "
                                     "for this part.")
    clearer: Clearer = Field(description="Which version is easier to understand: official, "
                                         "generated, or same.")
    clearer_why: str = Field(description="Why that version is easier to understand.")
    citations: list[Citation] = Field(description="The evidence the verdict rests on: at least "
                                                  "one, and only ids you were given.")
    differences: list[DifferenceVerdict] = Field(
        default_factory=list,
        description="One ruling per difference listed under DIFFERENCES (D1, D2, ...): every "
                    "difference, once each, in the order given.")


class Verdict(BaseModel):
    """The recorded judgement of one part — cached, versioned, auditable."""
    part_id: str
    evaluation: Literal["rulesbank", "generator"]
    input: str
    owner: str
    aspect: str
    summary: str
    answer: JudgeAnswer
    focus: list[str] = Field(default_factory=list)           # what was judged …
    differences: list[Difference] = Field(default_factory=list)
    difference_verdicts: list[str] = Field(default_factory=list)   # one per difference,
                                     # in order — the judge's, after the checks
    official_focus: dict[str, Any] = Field(default_factory=dict)   # … and as it is on each
    generated_focus: dict[str, Any] = Field(default_factory=dict)  # side (location → node)
    evidence: list[Evidence]                 # what the judge read, with the ids it saw
    decided_by: Literal["llm", "no_evidence"]
    overrides: list[str] = Field(default_factory=list)  # deterministic corrections applied
    model: str = ""
    prompt_version: str = ""
    cache_key: str = ""
    judged_at: str = ""


class JudgeReport(BaseModel):
    """The verdicts on one evaluated input — reported apart from the agreement numbers."""
    evaluation: Literal["rulesbank", "generator"]
    input: str
    spec_collection: str
    service: str
    scope: list[str] = Field(default_factory=list)   # spec blocks searched ("11.1", "12.1")
    model: str
    prompt_version: str
    evaluated_at: str
    verdicts: list[Verdict]
    usage: dict[str, Any] = Field(default_factory=dict)   # calls, tokens, cost of THIS run
    owners_total: int = 0            # owners of either document (generator)
    owners_equal: list[str] = Field(default_factory=list)  # owners with no part: equal
    parts_total: int = 0             # parts found — more than the verdicts if a run is partial
    leaves: dict[str, dict[str, int]] = Field(default_factory=dict)  # generator: the
                                     # values of both documents by region (parts.leaf_census)
    validity_generated: ValidityReport | None = None   # layer 2 (generator)
    validity_official: ValidityReport | None = None
    official: SourceInfo | None = None   # the official YAML compared against (label, version)

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.verdicts:
            out[v.answer.verdict] = out.get(v.answer.verdict, 0) + 1
        return out
