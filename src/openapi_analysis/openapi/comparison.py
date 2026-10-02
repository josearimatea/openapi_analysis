"""Compare a generated OpenAPI document with the official one, document against document.

Origin: openapi_generator/src/openapi_generator/eval/comparison.py — same leaf
model, kept so both repos read a run the same way. Differences: `x-*` extension
blocks (the generator stamps x-ai-generation) count as metadata, not contract;
parameters are identified by (in, name) instead of list position; enum and
required are compared as sets; operations are compared as METHOD + path; the
result is the Pydantic report.

Every leaf of the official document is classified, then found in the generated
one by its exact path:
    exact      both have it, same value
    absent     official has it, generated does not
    differing  both have it, values disagree
plus `extra`: leaves the generated document adds. Extra is listed, not scored — a
document may state what the official one leaves implicit.

List position is part of a leaf path (allOf[1].type), so a composition whose
members moved reads as a difference rather than silently matching.
"""

from __future__ import annotations

from typing import Any

from openapi_analysis.rulesbank.rule_types import HTTP_METHODS
from openapi_analysis.schemas.openapi import GroupScore, LeafDifference, OpenAPIEvaluation
from openapi_analysis.schemas.rulesbank import SourceInfo

# Leaf name → prose. Compared for information, never counted as a defect.
PROSE_KEYS = ("description", "summary", "title", "operationId")
# Top-level block → metadata about the document rather than the API contract.
METADATA_ROOTS = ("info", "servers", "externalDocs", "openapi", "tags", "security")

GROUPS = ("contract", "metadata", "prose")


def _item_label(prefix: str, i: int, value: Any) -> str:
    """A list item's label: its position — except a parameter, labelled by identity.

    OpenAPI identifies a parameter by (in, name), not by its place in the list, so
    a generated document listing the same parameters in another order must not
    read as wrong. Composition members (allOf[1]) keep their position.
    """
    if prefix.endswith("parameters") and isinstance(value, dict) \
            and "name" in value and "in" in value:
        return f"{prefix}[in={value['in']},name={value['name']}]"
    return f"{prefix}[{i}]"


# JSON Schema keywords whose list is a SET: order carries no meaning, so the whole
# list is one leaf, compared sorted — a reordered enum is not a defect, a misspelled
# item still is.
SET_KEYWORDS = ("enum", "required")


def flatten(node: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a parsed document into {dotted.path: scalar}."""
    out: dict[str, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in SET_KEYWORDS and isinstance(value, list):
                out[path] = sorted(map(str, value))
                continue
            out.update(flatten(value, path))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.update(flatten(value, _item_label(prefix, i, value)))
    else:
        out[prefix] = node
    return out


def classify(leaf_path: str) -> str:
    """Bucket a leaf path into 'contract', 'metadata' or 'prose'."""
    leaf_name = leaf_path.split(".")[-1].split("[")[0]
    if leaf_name in PROSE_KEYS:
        return "prose"
    root = leaf_path.split(".")[0].split("[")[0]
    if root in METADATA_ROOTS or root.startswith("x-"):
        return "metadata"
    return "contract"


def _find_refs(node: Any, at: str = "") -> list[tuple[str, list[str]]]:
    """Every $ref with the keys sitting beside it (OAS 3.0: siblings are ignored)."""
    found: list[tuple[str, list[str]]] = []
    if isinstance(node, dict):
        if "$ref" in node:
            found.append((at, [k for k in node if k != "$ref"]))
        for key, value in node.items():
            found.extend(_find_refs(value, f"{at}.{key}" if at else str(key)))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_find_refs(value, f"{at}[{i}]"))
    return found


def _operations(doc: dict) -> set[str]:
    return {f"{m.upper()} {path}"
            for path, item in (doc.get("paths") or {}).items() if isinstance(item, dict)
            for m in HTTP_METHODS if isinstance(item.get(m), dict)}


def _schemas(doc: dict) -> set[str]:
    return set((doc.get("components") or {}).get("schemas") or {})


def compare_documents(generated: dict, official: dict, *,
                      generated_info: SourceInfo | None = None,
                      official_info: SourceInfo | None = None) -> OpenAPIEvaluation:
    """Compare two parsed OpenAPI documents."""
    gen_leaves, off_leaves = flatten(generated), flatten(official)
    groups = {name: GroupScore() for name in GROUPS}

    for path, off_value in off_leaves.items():
        score = groups[classify(path)]
        score.total += 1
        if path not in gen_leaves:
            score.absent.append(path)
        elif gen_leaves[path] == off_value:
            score.exact += 1
        else:
            score.differing.append(LeafDifference(path=path, generated=gen_leaves[path],
                                                  official=off_value))
    for path in gen_leaves:
        if path not in off_leaves:
            groups[classify(path)].extra.append(path)
    for score in groups.values():
        score.absent.sort()
        score.extra.sort()
        score.differing.sort(key=lambda d: d.path)

    gen_ops, off_ops = _operations(generated), _operations(official)
    gen_schemas, off_schemas = _schemas(generated), _schemas(official)
    refs = _find_refs(generated)
    return OpenAPIEvaluation(
        official=official_info or SourceInfo(),
        generated=generated_info or SourceInfo(),
        contract=groups["contract"], metadata=groups["metadata"], prose=groups["prose"],
        operations_missing=sorted(off_ops - gen_ops),
        operations_extra=sorted(gen_ops - off_ops),
        schemas_missing=sorted(off_schemas - gen_schemas),
        schemas_extra=sorted(gen_schemas - off_schemas),
        refs_total=len(refs),
        refs_with_siblings=sorted(at for at, siblings in refs if siblings),
    )
