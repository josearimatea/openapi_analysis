"""The alignment of the two documents (docs/ALIGNMENT_PLAN.md): blocks and groups.

A Block is one object of a fixed kind in one document — an operation, a parameter, a
request body media type, a response, a callback, a schema, ... A Group joins the
blocks of both documents that CORRESPOND (play the same role); it never says they are
right — the judge does. A block left in no group is a leftover: missing (official) or
extra (generated).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Side = Literal["official", "generated"]
BlockKind = Literal["header", "path", "operation", "parameter", "media_type", "response",
                    "callback", "schema", "component", "block"]
# how a block came into its group — the deterministic steps first, then the LLM's
Step = Literal["address", "key", "llm"]


class Block(BaseModel):
    id: str                          # stable: "<side>:<display location>"
    side: Side
    kind: BlockKind
    loc: list[str]                   # the location as layer-1 parts (comparison.flatten_parts)
    location: str                    # display form (comparison.join)
    identity: str                    # what names it ("GET /x", "query scope", "200", ...)
    parent: str | None = None        # the enclosing block whose group gives it its scope


class Group(BaseModel):
    id: str                          # "G1", "G2", ... in document order
    kind: BlockKind
    official: list[str] = Field(default_factory=list)    # block ids
    generated: list[str] = Field(default_factory=list)
    how: dict[str, Step] = Field(default_factory=dict)    # block id → the step that added it
    primary: list[str] = Field(default_factory=list)     # the pair whose inner blocks are
                                     # aligned in turn (an operation's parameters, ...)
    reasons: list[str] = Field(default_factory=list)     # the LLM's, when it grouped


class GroupingCall(BaseModel):
    """One LLM grouping call, recorded for audit."""
    area: str                        # "whole documents", or a region when split
    blocks: dict[str, str] = Field(default_factory=dict)  # the id the LLM saw → block id
    answer: GroupingAnswer
    overrides: list[str] = Field(default_factory=list)   # what the checks refused
    cache_key: str = ""
    model: str = ""
    version: str = ""


class Alignment(BaseModel):
    official_label: str = ""
    generated_label: str = ""
    blocks: dict[str, Block] = Field(default_factory=dict)
    groups: list[Group] = Field(default_factory=list)
    leftovers: list[str] = Field(default_factory=list)   # active blocks in no group
    owned: dict[str, int] = Field(default_factory=dict)  # block id → leaves it owns
    candidates: dict[str, list[tuple[str, float]]] = Field(default_factory=dict)  # step 4:
                                     # official leftover → [(generated leftover, score)]
    calls: list[GroupingCall] = Field(default_factory=list)


# ── the LLM's answer (structured output) ─────────────────────────────────────

class ProposedGroup(BaseModel):
    official: list[str] = Field(description="Ids of the official blocks (A1, ...) in the "
                                            "group.")
    generated: list[str] = Field(description="Ids of the generated blocks (B1, ...) in the "
                                             "group.")
    reason: str = Field(description="Why these blocks play the same role, naming the rules "
                                    "(R1, ...) and what in the blocks shows it.")


class ProposedJoin(BaseModel):
    block: str = Field(description="Id of a leftover block (A… or B…).")
    group: str = Field(description="Id of the existing group (G…) it joins.")
    reason: str = Field(description="Why it is another form or copy of what the group holds, "
                                    "naming the rules (R1, ...).")


class Ungrouped(BaseModel):
    block: str = Field(description="Id of a block left with no counterpart.")
    reason: str = Field(description="Why no block on the other side plays its role.")


class GroupingAnswer(BaseModel):
    groups: list[ProposedGroup] = Field(default_factory=list)
    joins: list[ProposedJoin] = Field(default_factory=list, description="Overview only: "
                                      "leftovers joined to an existing group.")
    ungrouped: list[Ungrouped] = Field(default_factory=list, description="Every block given "
                                       "that is in no group and no join, once each.")


GroupingCall.model_rebuild()
