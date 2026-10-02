"""Report of evaluation 2 — generated YAML × official YAML, document against document.

Leaves are split in three groups and scored apart, because one "how many leaves
match" number weighs a reworded description the same as a wrong type:
  contract  paths, methods, schemas, types, $ref, enum, required — what the API promises
  metadata  info, servers, externalDocs, openapi, tags, security, x-* extensions
  prose     description, summary, title, operationId — need only MEAN the same
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from openapi_analysis.config.settings import REPORT_SCHEMA_VERSION
from openapi_analysis.schemas.rulesbank import SourceInfo


class LeafDifference(BaseModel):
    path: str
    generated: Any
    official: Any


class GroupScore(BaseModel):
    """How one group of leaves fared against the official document."""
    total: int = 0                                   # leaves in the official document
    exact: int = 0
    absent: list[str] = Field(default_factory=list)  # official leaf not generated
    differing: list[LeafDifference] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)   # generated leaf not official

    @computed_field
    @property
    def ratio(self) -> float:
        return round(self.exact / self.total, 4) if self.total else 0.0


class OpenAPIEvaluation(BaseModel):
    schema_version: int = REPORT_SCHEMA_VERSION
    kind: Literal["openapi"] = "openapi"
    official: SourceInfo
    generated: SourceInfo
    contract: GroupScore
    metadata: GroupScore
    prose: GroupScore
    operations_missing: list[str]        # "METHOD /path" official, not generated
    operations_extra: list[str]          # "METHOD /path" generated, not official
    schemas_missing: list[str]
    schemas_extra: list[str]
    refs_total: int
    refs_with_siblings: list[str]        # $ref with sibling keys (ignored by OAS 3.0)
