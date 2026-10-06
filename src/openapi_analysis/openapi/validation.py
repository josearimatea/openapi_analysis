"""Layer 2 — is a document VALID OpenAPI 3.0? Syntax only, never quality.

Answers one question, with no interpretation: does the document follow the format
the OpenAPI 3.0 specification fixes (which fields exist where, of which type)?
Whether a valid choice is the RIGHT one (4XX/5XX vs default, a flattened allOf)
is not decided here — that needs reading the OpenAPI reference and the 3GPP spec.

Three checks, all deterministic:
  schema     the document against the official OpenAPI 3.0 JSON Schema (published
             by the OpenAPI Initiative, shipped in openapi-spec-validator). Lists
             EVERY violation; resolves no $ref.
  local_ref  every local $ref ("#/...") points to something in the document. The
             validator below stops at the first broken one; this lists them all.
  semantics  openapi-spec-validator's own checks (path parameters declared,
             unique operationIds, ...). Runs only when the two above pass.

External $refs ("TS28623_ComDefs.yaml#/...") point to files of other 3GPP specs,
which are not in data/inputs. Resolving them would abort every document, the
official ones included, on its first external ref. So an external file resolves
to a stub in which any schema exists and accepts anything: the document itself is
validated, the files it imports are not.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

from jsonschema import Draft4Validator
from jsonschema.exceptions import best_match
from jsonschema_path import SchemaPath
from openapi_spec_validator import OpenAPIV30SpecValidator
from openapi_spec_validator.schemas import schema_v30

from openapi_analysis.schemas.openapi import ValidationIssue, ValidityReport

VALIDATOR = f"openapi-spec-validator {importlib.metadata.version('openapi-spec-validator')}"
_BASE_URI = "file:///openapi_analysis/document.yaml"


class _AnySchemas(dict):
    """components.schemas of an external file we do not have: every name exists, as {}."""

    def __contains__(self, key: object) -> bool:
        return True

    def __getitem__(self, key: Any) -> dict:
        return {}


def _external_file(uri: str) -> dict:
    return {"components": {"schemas": _AnySchemas()}}


def _location(path: Any) -> str:
    """Same notation as the comparison: dotted, [i] for list items, dotted keys quoted."""
    out = ""
    for p in path:
        if isinstance(p, int):              # a list index ("200" as a key stays a key)
            out += f"[{p}]"
        else:
            key = f"'{p}'" if "." in str(p) else str(p)
            out = f"{out}.{key}" if out else key
    return out or "(root)"


def _schema_issues(doc: dict) -> list[ValidationIssue]:
    issues = []
    for e in Draft4Validator(schema_v30).iter_errors(doc):
        # a oneOf/anyOf failure reports the whole object; its best sub-error names the key
        specific = best_match(e.context) if e.validator in ("oneOf", "anyOf") and e.context else e
        issues.append(ValidationIssue(check="schema", location=_location(e.absolute_path),
                                      message=specific.message[:240]))
    return sorted(issues, key=lambda i: i.location)


def _resolves(doc: dict, pointer: str) -> bool:
    node: Any = doc
    for raw in pointer.lstrip("/").split("/") if pointer.strip("/") else []:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return False
    return True


def _local_ref_issues(doc: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def walk(node: Any, path: list[str | int]) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#") and not _resolves(doc, ref[1:]):
                issues.append(ValidationIssue(
                    check="local_ref", location=_location(path),
                    message=f"$ref '{ref}' points to nothing in this document"))
            for key, value in node.items():
                walk(value, [*path, str(key)])
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, [*path, i])

    walk(doc, [])
    return issues


def _semantic_issues(doc: dict) -> list[ValidationIssue]:
    spec = SchemaPath.from_dict(doc, base_uri=_BASE_URI, handlers={"file": _external_file})
    try:
        return [ValidationIssue(check="semantics",
                                location=_location(getattr(e, "absolute_path", [])),
                                message=str(getattr(e, "message", e))[:240])
                for e in OpenAPIV30SpecValidator(spec).iter_errors()]
    except Exception as exc:  # noqa: BLE001 — the validator aborts with varied types; report, never crash
        return [ValidationIssue(check="semantics", location="(validator)",
                                message=f"{type(exc).__name__}: {str(exc)[:200]}")]


def validate_document(doc: dict) -> ValidityReport:
    """Validate a parsed document as OpenAPI 3.0 (see the module docstring)."""
    issues = _schema_issues(doc) + _local_ref_issues(doc)
    checks = ["schema", "local_ref"]
    if not issues:
        issues = _semantic_issues(doc)
        checks.append("semantics")
    return ValidityReport(valid=not issues, issues=issues, checks_run=checks,
                          validator=VALIDATOR)
