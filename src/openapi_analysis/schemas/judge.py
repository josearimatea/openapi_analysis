"""The judge's records (layer 3, docs/JUDGE_PLAN.md).

A Part is one divergence, cut small enough that a retrieval can be aimed at it:
one bank rule (rules bank evaluation), or one aspect of one owner — an operation's
responses, a schema's definition — (generator evaluation). It carries both sides
as they are, a deterministic summary, and the hints the retrieval needs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchHints(BaseModel):
    """What the retrieval is aimed with — taken from the part, never guessed."""
    clause: str = ""                 # 3GPP clause the bank rule came from ("12.1.3.1.4")
    path: str = ""                   # "/{className}={id}"
    method: str = ""                 # "patch"
    schemas: list[str] = Field(default_factory=list)       # schema names involved
    external_refs: list[str] = Field(default_factory=list)  # "TS28623_ComDefs.yaml#/…"
    terms: list[str] = Field(default_factory=list)          # extra words (operation, field)


class Part(BaseModel):
    """One divergence to be judged, with both sides as they are in their documents."""
    id: str                          # stable — the verdict cache is keyed on it
    evaluation: Literal["rulesbank", "generator"]
    input: str                       # the evaluated bank / generated document (label)
    owner: str                       # "PATCH /x", "PATH /x", "SCHEMA Name", or a rule address
    aspect: str                      # what diverges (see judge/parts.py ASPECTS)
    summary: str                     # deterministic one-line description of the divergence
    official: Any = None             # the official side (None: absent there)
    generated: Any = None            # the generated / bank side (None: absent there)
    hints: SearchHints = Field(default_factory=SearchHints)
    invalid_issues: list[str] = Field(default_factory=list)  # layer-2 issues inside it:
                                     # not valid OpenAPI 3.0 — an error before any judging
