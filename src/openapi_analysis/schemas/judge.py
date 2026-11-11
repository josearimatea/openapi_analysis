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

VerdictLabel = Literal["error", "improvement", "equivalent", "useful", "uncertain"]
Clearer = Literal["official", "generated", "same"]


class SearchHints(BaseModel):
    """What the retrieval is aimed with — taken from the part, never guessed."""
    clause: str = ""                 # 3GPP clause the bank rule came from ("12.1.3.1.4")
    path: str = ""                   # "/{className}={id}"
    method: str = ""                 # "patch"
    schemas: list[str] = Field(default_factory=list)       # schema names involved
    other_paths: list[str] = Field(default_factory=list)  # paths of the part's blocks elsewhere
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
    path: str = ""                   # spec chunks: the headings above it, down to the clause
    title: str = ""
    text: str


class Difference(BaseModel):
    """One place where the two sides differ, located in the document.

    absent / extra: a whole subtree on one side only (`leaves` counts its leaves);
    differing: both sides have it with another value (both values given);
    moved: a block grouped with one at another location (official / generated hold
    the two locations) — the change of place, judged as any other difference;
    duplicate: a further declaration, in the generated document, of what it already
    declares (official: where the original declaration is) — judged whole, once.
    """
    kind: Literal["absent", "differing", "extra", "moved", "duplicate"]
    # what is known without reading it (judge/prompts.py KNOWN): the same content under
    # another key, a request the official declares as a callback and the generated as a
    # path, a key beside a $ref
    known: Literal["", "same_content", "callback_to_path", "beside_ref", "empty_schema"] = ""
    hint: str = ""                   # what to ask of this difference, told on its own line
    location: str                    # display path in the document ("paths./x.patch.responses.200")
    leaves: int = 1
    official: Any = None             # differing, moved
    generated: Any = None
    official_location: str = ""      # where it is in the official document, when that
                                     # differs from `location` (a block grouped elsewhere)


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
    cited: dict[str, dict[str, Any]] = Field(default_factory=dict)  # generator: side → the
                                     # local $ref the context cites → what it points to
    replaced: dict[str, list[str]] = Field(default_factory=dict)  # generator: a local schema
                                     # of the part → the official's $refs to another file
                                     # with the same name (judge/group_parts.py)
    headers: dict[str, Any] = Field(default_factory=dict)  # generator: the document
                                     # header of each side (servers, info...) — context only
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
    reason: str = Field(description="Think first, before the verdict: which passage decides "
                                    "this difference, what it says, and what follows, naming "
                                    "the evidence ids it rests on.")
    verdict: VerdictLabel = Field(description="What the reason leads to: error | improvement | "
                                              "equivalent | useful | uncertain, for THIS "
                                              "difference alone, with the same meanings as the "
                                              "part's verdict.")


class JudgeAnswer(BaseModel):
    """What the LLM returns for one part (structured output)."""
    why_different: str = Field(description="Why the generated side differs from the official "
                                           "one: the probable cause, whether the difference is "
                                           "in a value, an address (level, location) or a "
                                           "structure.")
    spec_3gpp: str = Field(description="What the 3GPP spec evidence says about this part.")
    openapi: str = Field(description="What the OpenAPI reference evidence allows or recommends "
                                     "for this part.")
    citations: list[Citation] = Field(description="The evidence the verdict rests on: at least "
                                                  "one, and only ids you were given.")
    differences: list[DifferenceVerdict] = Field(
        default_factory=list,
        description="One ruling per difference listed under DIFFERENCES (D1, D2, ...): every "
                    "difference, once each, in the order given.")
    clearer: Clearer = Field(description="Which version is easier to understand: official, "
                                         "generated, or same.")
    clearer_why: str = Field(description="Why that version is easier to understand.")
    grouping_wrong: bool = Field(
        default=False,
        description="True only if some blocks put together in this part do NOT play the same "
                    "role in the API (they were grouped as corresponding by mistake). False when "
                    "they correspond, right or wrong.")
    wrongly_grouped: list[str] = Field(
        default_factory=list,
        description="When grouping_wrong: the locations of the blocks that do not belong with "
                    "the rest, exactly as listed under FOCUS. They are taken out and judged on "
                    "their own.")
    wrongly_grouped_why: str = Field(
        default="", description="When grouping_wrong: why those blocks do not belong.")
    verdict: VerdictLabel = Field(description="Last, after the differences: error: the generated "
                                              "side is wrong. improvement: the generated side is "
                                              "better than the official one (needs S or O "
                                              "evidence). equivalent: different form, same "
                                              "meaning, on both sides (the CONTEXT may suffice). "
                                              "useful: only on the generated side, not called for "
                                              "and contradicted by nothing. uncertain: the meaning "
                                              "changes and nothing given decides.")


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
    rule_verdicts: dict[str, str] = Field(default_factory=dict)   # rules bank, "error
                                     # responses" part: each rule's verdict (bank rule index,
                                     # or "official"), by its form (judge/rules.py) or by the
                                     # judge on its difference; "same": equal to the official
    official_focus: dict[str, Any] = Field(default_factory=dict)   # … and as it is on each
    generated_focus: dict[str, Any] = Field(default_factory=dict)  # side (location → node)
    evidence: list[Evidence]                 # what the judge read, with the ids it saw
    decided_by: Literal["llm", "no_evidence", "rule"]   # rule: judge/rules.py, no LLM
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
    spec: str = ""                   # the spec version the analysis is based on
    version_notes: list[str] = Field(default_factory=list)  # what differs from that version
                                     # (allow_other_version), or could not be checked
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
    official_view: dict[str, dict[str, int]] = Field(default_factory=dict)  # (old reports)
    views: dict[str, dict[str, int]] = Field(default_factory=dict)  # generator: the fields
                                     # of each document by outcome (judge/group_parts.views):
                                     # "official", "generated", and the "header" apart
    grouping: dict[str, int] = Field(default_factory=dict)  # generator: block memberships
                                     # by how they were grouped (address, key, llm)
    regrouped: list[str] = Field(default_factory=list)  # generator: blocks the judge took
                                     # out of a group, judged again on their own (why)

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.verdicts:
            out[v.answer.verdict] = out.get(v.answer.verdict, 0) + 1
        return out
