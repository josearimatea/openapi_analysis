"""Compare a generated OpenAPI document with the official one, document against document.

Origin: openapi_generator/src/openapi_generator/eval/comparison.py — same leaf
model, kept so both repos read a run the same way. Differences: `x-*` extension
blocks (the generator stamps x-ai-generation) count as metadata, not contract;
parameters are identified by (in, name) instead of list position; enum and
required are compared as sets; the contract is broken down by owner (operation,
path item, schema); both documents are validated as OpenAPI 3.0 (layer 2,
openapi/validation.py); the result is the Pydantic report.

Every leaf of the official document is classified, then found in the generated
one by its exact path:
    exact      both have it, same value
    absent     official has it, generated does not
    differing  both have it, values disagree
plus `extra`: leaves the generated document adds. Extra is listed, not scored — a
document may state what the official one leaves implicit.

A leaf path is kept as a TUPLE of keys, never split back from a dotted string:
media types (application/vnd.3gpp.object-tree-flat+json), callback expressions
({$request.body#/x}) and malformed generated keys all contain dots. The dotted
string is only for display, with such keys quoted.

List position is part of a leaf path (allOf[1].type), so a composition whose
members moved reads as a difference rather than silently matching.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from openapi_analysis.openapi.validation import validate_document
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS
from openapi_analysis.schemas.openapi import (
    ContractDetail,
    GroupScore,
    LeafCounts,
    LeafDifference,
    OpenAPIEvaluation,
    OperationScore,
    SchemaScore,
)
from openapi_analysis.schemas.rulesbank import SourceInfo

# Leaf name → prose. Compared for information, never counted as a defect.
PROSE_KEYS = ("description", "summary", "title", "operationId")
# Top-level block → metadata about the document rather than the API contract.
METADATA_ROOTS = ("info", "servers", "externalDocs", "openapi", "tags", "security")
# JSON Schema keywords whose list is a SET: order carries no meaning, so the whole
# list is one leaf, compared sorted — a reordered enum is not a defect, a misspelled
# item still is.
SET_KEYWORDS = ("enum", "required")

GROUPS = ("contract", "metadata", "prose")
Parts = tuple[str, ...]


# ── leaves ───────────────────────────────────────────────────────────────────

def _item_label(prefix: Parts, i: int, value: Any) -> str:
    """A list item's label: its position — except a parameter, labelled by identity.

    OpenAPI identifies a parameter by (in, name), not by its place in the list, so
    a generated document listing the same parameters in another order must not
    read as wrong. Composition members (allOf[1]) keep their position.
    """
    if prefix and prefix[-1] == "parameters" and isinstance(value, dict) \
            and "name" in value and "in" in value:
        return f"[in={value['in']},name={value['name']}]"
    return f"[{i}]"


def flatten_parts(node: Any, prefix: Parts = ()) -> dict[Parts, Any]:
    """Flatten a parsed document into {(key, key, "[i]", ...): scalar}."""
    out: dict[Parts, Any] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = (*prefix, str(key))
            if key in SET_KEYWORDS and isinstance(value, list):
                out[path] = sorted(map(str, value))
                continue
            out.update(flatten_parts(value, path))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out.update(flatten_parts(value, (*prefix, _item_label(prefix, i, value))))
    else:
        out[prefix] = node
    return out


def join(parts: Parts) -> str:
    """Display form: dotted, list labels attached, keys holding a dot quoted."""
    out = ""
    for p in parts:
        if p.startswith("["):
            out += p
        else:
            key = f"'{p}'" if "." in p else p
            out = f"{out}.{key}" if out else key
    return out


def flatten(node: Any) -> dict[str, Any]:
    """Flatten a parsed document into {dotted.path: scalar} (display form)."""
    return {join(k): v for k, v in flatten_parts(node).items()}


def classify_parts(parts: Parts) -> str:
    """Bucket a leaf into 'contract', 'metadata' or 'prose'."""
    names = [p for p in parts if not p.startswith("[")]
    if names and names[-1] in PROSE_KEYS:
        return "prose"
    root = names[0] if names else ""
    if root in METADATA_ROOTS or root.startswith("x-"):
        return "metadata"
    return "contract"


def classify(leaf_path: str) -> str:
    """classify_parts for a dotted path without dotted keys (convenience)."""
    return classify_parts(tuple(leaf_path.replace("[", ".[").split(".")))


# ── owners and elements ──────────────────────────────────────────────────────

def owner(parts: Parts) -> tuple[str, int]:
    """(owner, number of leading parts it spans): 'GET /x', 'PATH /x', 'SCHEMA N', 'OTHER'."""
    if len(parts) > 2 and parts[0] == "paths":
        if parts[2] in HTTP_METHODS:
            return f"{parts[2].upper()} {parts[1]}", 3
        return f"PATH {parts[1]}", 2
    if len(parts) > 2 and parts[:2] == ("components", "schemas"):
        return f"SCHEMA {parts[2]}", 3
    return "OTHER", 0


def element(rel: Parts) -> Parts:
    """The element a leaf belongs to — a parameter, a response media type, a property,
    a callback — so the leaves under it are reported as one line."""
    if not rel:
        return rel
    head = rel[0]
    spans = {"parameters": 2, "callbacks": 2, "properties": 2, "schemas": 2}
    if head in spans:
        return rel[:spans[head]]
    if head == "responses":
        return rel[:4] if len(rel) > 3 and rel[2] == "content" else rel[:2]
    if head == "requestBody":
        return rel[:3] if len(rel) > 2 and rel[1] == "content" else rel[:2]
    if head in ("allOf", "oneOf", "anyOf") and len(rel) > 3 and rel[2] == "properties":
        return rel[:4]
    if head == "components" and len(rel) > 1:      # OTHER: a block outside its place
        return rel[:2]
    if head == "paths" and len(rel) > 1:
        return rel[:2]
    # anything else nested deeper (a key that has no business there, e.g. a callback
    # leaked into a path item) is one element: its first key
    return rel[:1] if len(rel) > 2 else rel


# ── per-operation and per-schema facts ───────────────────────────────────────

def _op_items(doc: dict) -> dict[str, tuple[dict, dict]]:
    """{"METHOD /path": (path item, operation)} for every operation of a document."""
    return {f"{m.upper()} {path}": (item, item[m])
            for path, item in (doc.get("paths") or {}).items() if isinstance(item, dict)
            for m in HTTP_METHODS if isinstance(item.get(m), dict)}


def _schemas(doc: dict) -> dict[str, Any]:
    return dict((doc.get("components") or {}).get("schemas") or {})


def _declared(node: dict) -> set[str]:
    """Parameters declared directly on a path item or an operation, as 'in name'."""
    return {f"$ref {p['$ref']}" if "$ref" in p else f"{p.get('in')} {p.get('name')}"
            for p in (node.get("parameters") or []) if isinstance(p, dict)}


def _params(item: dict, op: dict) -> set[str]:
    """Effective parameters of an operation: the path item's plus its own."""
    return _declared(item) | _declared(op)


def _media(op: dict) -> set[str]:
    rb = op.get("requestBody")
    return set((rb.get("content") or {}) if isinstance(rb, dict) else {})


def _codes(op: dict) -> set[str]:
    return {str(c) for c in (op.get("responses") or {})}


def shape(schema: Any) -> str:
    """The structural outline of a schema — enough to see a flattened composition."""
    if not isinstance(schema, dict):
        return ""
    if "$ref" in schema:
        return f"$ref {schema['$ref']}"
    parts = [f"{kw}[{len(schema[kw])}]" for kw in ("allOf", "oneOf", "anyOf")
             if isinstance(schema.get(kw), list)]
    if "type" in schema:
        parts.append(f"type={schema['type']}")
    for kw in ("properties", "enum"):
        if kw in schema:
            parts.append(f"{kw}[{len(schema[kw])}]")
    return ", ".join(parts)


def _misplaced(name: str, generated: dict) -> tuple[str, Any]:
    """Where a schema missing from components.schemas sits instead, if anywhere."""
    components = generated.get("components") or {}
    if isinstance(components.get(name), dict):
        return f"components.{name}", components[name]
    for section, block in components.items():
        if section != "schemas" and isinstance(block, dict) and isinstance(block.get(name), dict):
            return f"components.{section}.{name}", block[name]
    return "", None


def _all_refs(node: Any) -> list[str]:
    """Every $ref value in a document."""
    if isinstance(node, dict):
        own = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return own + [r for v in node.values() for r in _all_refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _all_refs(v)]
    return []


def _external_ref_files(official: dict) -> dict[str, str]:
    """{schema name: file} for every schema the official YAML takes from another file."""
    out: dict[str, str] = {}
    for ref in _all_refs(official):
        file, _, pointer = ref.partition("#")
        if file:
            out.setdefault(pointer.rsplit("/", 1)[-1], file)
    return out


def _matching_leaves(official_schema: Any, generated_schema: Any) -> tuple[int, int]:
    """(exact, total) contract leaves if the generated schema were at the official place."""
    off = {p: v for p, v in flatten_parts(official_schema).items()
           if classify_parts(p) == "contract"}
    gen = flatten_parts(generated_schema)
    return sum(1 for p, v in off.items() if gen.get(p) == v), len(off)


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


# ── comparison ───────────────────────────────────────────────────────────────

def _details(off_leaves: dict[Parts, Any], gen_leaves: dict[Parts, Any]) -> list[ContractDetail]:
    """Contract differences by owner; absent / extra collapsed per element."""
    collapsed: dict[tuple[str, str, str], int] = defaultdict(int)
    differing: list[ContractDetail] = []
    for parts, value in off_leaves.items():
        if classify_parts(parts) != "contract":
            continue
        own, span = owner(parts)
        if parts not in gen_leaves:
            collapsed[(own, join(element(parts[span:])), "absent")] += 1
        elif gen_leaves[parts] != value:
            differing.append(ContractDetail(owner=own, element=join(parts[span:]),
                                            kind="differing", generated=gen_leaves[parts],
                                            official=value))
    for parts in gen_leaves:
        if parts not in off_leaves and classify_parts(parts) == "contract":
            own, span = owner(parts)
            collapsed[(own, join(element(parts[span:])), "extra")] += 1
    details = [ContractDetail(owner=o, element=e, kind=k, leaves=n)
               for (o, e, k), n in collapsed.items()]
    order = {"absent": 0, "differing": 1, "extra": 2}
    return sorted(details + differing, key=lambda d: (d.owner, order[d.kind], d.element))


def compare_documents(generated: dict, official: dict, *,
                      generated_info: SourceInfo | None = None,
                      official_info: SourceInfo | None = None) -> OpenAPIEvaluation:
    """Compare two parsed OpenAPI documents."""
    gen_leaves, off_leaves = flatten_parts(generated), flatten_parts(official)
    groups = {name: GroupScore() for name in GROUPS}
    by_owner: dict[str, LeafCounts] = defaultdict(LeafCounts)

    for parts, off_value in off_leaves.items():
        group = classify_parts(parts)
        score = groups[group]
        score.total += 1
        counts = by_owner[owner(parts)[0]] if group == "contract" else LeafCounts()
        counts.total += 1
        path = join(parts)
        if parts not in gen_leaves:
            score.absent.append(path)
            counts.absent += 1
        elif gen_leaves[parts] == off_value:
            score.exact += 1
            counts.exact += 1
        else:
            score.differing.append(LeafDifference(path=path, generated=gen_leaves[parts],
                                                  official=off_value))
            counts.differing += 1
    for parts in gen_leaves:
        if parts not in off_leaves:
            group = classify_parts(parts)
            groups[group].extra.append(join(parts))
            if group == "contract":
                by_owner[owner(parts)[0]].extra += 1
    for score in groups.values():
        score.absent.sort()
        score.extra.sort()
        score.differing.sort(key=lambda d: d.path)

    # operations — and one "PATH /x" row per path item for what it declares itself
    gen_ops, off_ops = _op_items(generated), _op_items(official)
    off_paths, gen_paths = official.get("paths") or {}, generated.get("paths") or {}
    operations = []
    for p in sorted(set(off_paths) | set(gen_paths)):
        o_item = off_paths.get(p) if isinstance(off_paths.get(p), dict) else {}
        g_item = gen_paths.get(p) if isinstance(gen_paths.get(p), dict) else {}
        o_par, g_par = _declared(o_item), _declared(g_item)
        path_counts = by_owner.get(f"PATH {p}", LeafCounts())
        if o_par or g_par or path_counts.total or path_counts.extra:
            operations.append(OperationScore(
                operation=f"PATH {p}",
                status="present" if p in off_paths and p in gen_paths else (
                    "missing" if p in off_paths else "extra"),
                params_missing=sorted(o_par - g_par), params_extra=sorted(g_par - o_par),
                leaves=path_counts))
        for op in sorted(o for o in set(off_ops) | set(gen_ops) if o.split(" ", 1)[1] == p):
            status = "present" if op in off_ops and op in gen_ops else (
                "missing" if op in off_ops else "extra")
            o_item, o_op = off_ops.get(op, ({}, {}))
            g_item, g_op = gen_ops.get(op, ({}, {}))
            o_par, g_par = _params(o_item, o_op), _params(g_item, g_op)
            operations.append(OperationScore(
                operation=op, status=status,
                params_missing=sorted(o_par - g_par), params_extra=sorted(g_par - o_par),
                params_at_path_level=sorted((_declared(o_op) & _declared(g_item))
                                            - _declared(g_op)),
                media_missing=sorted(_media(o_op) - _media(g_op)),
                media_extra=sorted(_media(g_op) - _media(o_op)),
                responses_missing=sorted(_codes(o_op) - _codes(g_op)),
                responses_extra=sorted(_codes(g_op) - _codes(o_op)),
                leaves=by_owner.get(op, LeafCounts()),
            ))

    # schemas
    gen_schemas, off_schemas = _schemas(generated), _schemas(official)
    external = _external_ref_files(official)
    schemas = []
    for name in list(off_schemas) + [n for n in gen_schemas if n not in off_schemas]:
        score = SchemaScore(name=name, status="present",
                            shape_official=shape(off_schemas.get(name)),
                            shape_generated=shape(gen_schemas.get(name)),
                            leaves=by_owner.get(f"SCHEMA {name}", LeafCounts()))
        if name not in gen_schemas:
            found_at, node = _misplaced(name, generated)
            if found_at:
                exact, total = _matching_leaves(off_schemas[name], node)
                score.status, score.found_at = "misplaced", found_at
                score.shape_generated = shape(node)
                score.note = (f"defined at {found_at}, outside components.schemas; at the "
                              f"right place {exact}/{total} of its leaves would match")
            else:
                score.status = "missing"
        elif name not in off_schemas:
            score.status = "extra"
            if name in external:
                score.note = (f"external in the official YAML ({external[name]}); the "
                              "generated document defines its own copy")
        schemas.append(score)

    refs = _find_refs(generated)
    return OpenAPIEvaluation(
        official=official_info or SourceInfo(),
        generated=generated_info or SourceInfo(),
        contract=groups["contract"], metadata=groups["metadata"], prose=groups["prose"],
        operations=operations, schemas=schemas,
        other_leaves=by_owner.get("OTHER", LeafCounts()),
        details=_details(off_leaves, gen_leaves),
        validity_generated=validate_document(generated),
        validity_official=validate_document(official),
        operations_missing=sorted(set(off_ops) - set(gen_ops)),
        operations_extra=sorted(set(gen_ops) - set(off_ops)),
        schemas_missing=sorted(set(off_schemas) - set(gen_schemas)),
        schemas_extra=sorted(set(gen_schemas) - set(off_schemas)),
        refs_total=len(refs),
        refs_with_siblings=sorted(at for at, siblings in refs if siblings),
    )
