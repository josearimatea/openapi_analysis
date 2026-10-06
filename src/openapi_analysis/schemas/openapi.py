"""Report of evaluation 2 — generated YAML × official YAML, document against document.

Leaves are split in three groups and scored apart, because one "how many leaves
match" number weighs a reworded description the same as a wrong type:
  contract  paths, methods, schemas, types, $ref, enum, required — what the API promises
  metadata  info, servers, externalDocs, openapi, tags, security, x-* extensions
  prose     description, summary, title, operationId — need only MEAN the same

The contract is then broken down by its owner — each operation and each schema —
so a reader sees WHERE the document diverges and why (a schema created in the
wrong place, a composition flattened, a parameter put on another operation),
instead of a flat list of leaf paths.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from openapi_analysis.config.settings import REPORT_SCHEMA_VERSION
from openapi_analysis.schemas.rulesbank import SourceInfo, now


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


class LeafCounts(BaseModel):
    """Contract leaves of one owner (an operation or a schema)."""
    total: int = 0       # official leaves under this owner
    exact: int = 0
    absent: int = 0
    differing: int = 0
    extra: int = 0       # generated leaves under this owner that the official lacks


class ContractDetail(BaseModel):
    """One contract difference, located by owner and element.

    absent / extra: all leaves of one element (a parameter, a response media type,
    a property) collapsed into one entry, `leaves` counting them. differing: one
    entry per leaf, with both values.
    """
    owner: str              # "GET /x", "PATH /x", "SCHEMA Name", "OTHER"
    element: str            # relative to the owner, e.g. "parameters[in=query,name=scope]"
    kind: Literal["absent", "differing", "extra"]
    leaves: int = 1
    generated: Any = None
    official: Any = None


class ValidationIssue(BaseModel):
    """One violation of the OpenAPI 3.0 format (layer 2 — syntax, not quality)."""
    check: Literal["schema", "local_ref", "semantics"]
    location: str           # JSON path in the document, '/'-separated
    message: str


class ValidityReport(BaseModel):
    """Is the document valid OpenAPI 3.0? See openapi/validation.py."""
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)   # semantics runs only if the
                                                          # first two pass
    validator: str = ""                                   # tool and version


class OperationScore(BaseModel):
    """One operation (METHOD /path), official vs generated.

    A row "PATH /x" holds what is declared on the path item itself (parameters
    shared by every method); its params lists compare path-level parameters only.
    """
    operation: str
    status: Literal["present", "missing", "extra"]
    params_missing: list[str] = Field(default_factory=list)    # "query scope"
    params_extra: list[str] = Field(default_factory=list)
    # official on THIS operation, generated on the path item — offered to every
    # method of the path (§3.22)
    params_at_path_level: list[str] = Field(default_factory=list)
    media_missing: list[str] = Field(default_factory=list)     # request body media types
    media_extra: list[str] = Field(default_factory=list)
    responses_missing: list[str] = Field(default_factory=list)  # status codes
    responses_extra: list[str] = Field(default_factory=list)
    leaves: LeafCounts = Field(default_factory=LeafCounts)


class SchemaScore(BaseModel):
    """One schema of components.schemas, official vs generated."""
    name: str
    status: Literal["present", "missing", "misplaced", "extra"]
    found_at: str = ""            # misplaced: where the generated document put it
    shape_official: str = ""      # e.g. "allOf[2]", "type=object, properties[5]"
    shape_generated: str = ""
    note: str = ""
    leaves: LeafCounts = Field(default_factory=LeafCounts)


class OpenAPIEvaluation(BaseModel):
    schema_version: int = REPORT_SCHEMA_VERSION
    kind: Literal["openapi"] = "openapi"
    evaluated_at: str = Field(default_factory=now)   # when THIS report was produced
    official: SourceInfo
    generated: SourceInfo
    contract: GroupScore
    metadata: GroupScore
    prose: GroupScore
    operations: list[OperationScore]     # every operation (and path item) of either document
    schemas: list[SchemaScore]           # every schema of either document
    other_leaves: LeafCounts = Field(default_factory=LeafCounts)  # contract leaves owned
                                         # by neither, e.g. a schema outside components.schemas
    details: list[ContractDetail] = Field(default_factory=list)   # contract, by owner
    validity_generated: ValidityReport   # layer 2: is each document valid OpenAPI 3.0?
    validity_official: ValidityReport
    operations_missing: list[str]        # "METHOD /path" official, not generated
    operations_extra: list[str]          # "METHOD /path" generated, not official
    schemas_missing: list[str]           # includes the misplaced ones
    schemas_extra: list[str]
    refs_total: int
    refs_with_siblings: list[str]        # $ref with sibling keys (ignored by OAS 3.0)
