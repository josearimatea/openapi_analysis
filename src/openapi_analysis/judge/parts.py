"""Cut the divergences between two documents into PARTS for the judge.

Deterministic, no LLM, no retrieval: it only reads the evaluation reports and the
documents they were computed from. A part is small enough to aim a retrieval at it
(docs/JUDGE_PLAN.md §3) — what is equal to the official YAML never becomes a part.

Generator (both documents) — every difference, contract, metadata and prose alike,
lands in exactly one part, given to the owner it sits in:
    operation  owner "PATCH /x"   aspects: parameters | request_body | responses |
                                           callback <name> | operation
    path item  owner "PATH /x"    aspects: parameters | path_item | unexpected_keys | path
    schema     owner "SCHEMA N"   aspects: definition | placement | missing | extra
    component  owner "COMPONENT parameters.N" (other components sections): definition
    block      owner "COMPONENTS k" (a key in components that is no section),
               "DOCUMENT info" / "DOCUMENT x-..." (metadata) and other top-level keys
The part holds the WHOLE owner on both sides as context — the whole operation (with
the path item's parameters for a parameters part), the whole callback with the
identity of the operation that registers it, the whole schema, the whole block —
and its focus: the exact differences, computed here as layer 1 computes leaves.

Rules bank (RulesBankEvaluation + the bank) — one part per rule:
    different  a bank rule on an official address, with another value
    duplicate  several bank rules on one official address (covers their values too)
    missing    an official rule the bank does not have
    extra      a bank rule on no official address

Layer-2 issues (not valid OpenAPI 3.0) are attached to the part they fall in — the
most specific one whose focus contains them, or whose key they name — so a part
already invalid can be ruled an error without asking the LLM.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from openapi_analysis.judge.spec_index import clause_of
from openapi_analysis.openapi.comparison import (
    METADATA_ROOTS,
    SET_KEYWORDS,
    Parts,
    _item_label,
    element,
    flatten_parts,
    join,
)
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS, rule_key
from openapi_analysis.schemas.judge import Difference, Part, SearchHints
from openapi_analysis.schemas.openapi import OpenAPIEvaluation, OperationScore, SchemaScore
from openapi_analysis.schemas.rulesbank import RulesBankEvaluation

# operation key in the document → aspect name
_OP_ASPECTS = {"parameters": "parameters", "requestBody": "request_body",
               "responses": "responses", "callbacks": "callbacks"}
_REF = re.compile(r"(?:([A-Za-z0-9_.\-]+\.ya?ml))?#/components/[A-Za-z]+/([A-Za-z0-9_.\-]+)")


# ── helpers ──────────────────────────────────────────────────────────────────

def _refs(node: Any) -> list[str]:
    """Every $ref value inside a node (internal and external)."""
    if isinstance(node, dict):
        own = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return own + [r for v in node.values() for r in _refs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _refs(v)]
    return []


def _ref_hints(*nodes: Any) -> tuple[list[str], list[str]]:
    """(schema names, external refs) referenced anywhere in the given nodes."""
    names: list[str] = []
    external: list[str] = []
    for ref in (r for n in nodes for r in _refs(n)):
        m = _REF.search(ref)
        if m and m.group(2) not in names:
            names.append(m.group(2))
        if m and m.group(1) and ref not in external:
            external.append(ref)
    return names, external


def _ref_hints_in_text(*texts: str) -> tuple[list[str], list[str]]:
    names: list[str] = []
    external: list[str] = []
    for text in texts:
        for file, name in _REF.findall(text or ""):
            if name not in names:
                names.append(name)
            ref = f"{file}#/components/schemas/{name}" if file else ""
            if ref and ref not in external:
                external.append(ref)
    return names, external


def _get(doc: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(k)
    return doc


def _codes(node: Any) -> list[str]:
    return sorted(map(str, node)) if isinstance(node, dict) else []


# ── generator ────────────────────────────────────────────────────────────────

_MISSING = object()
Diff = tuple[str, Parts, Any, Any]      # (kind, path, official, generated)
# components sections whose entries are named, reusable objects (OAS 3.0)
_COMPONENT_SECTIONS = ("schemas", "responses", "parameters", "examples", "requestBodies",
                       "headers", "securitySchemes", "links", "callbacks")
# path item keys that are not operations but are allowed there
_PATH_ITEM_FIELDS = ("summary", "description", "servers", "$ref")


def _keys(element: str) -> list[str]:
    """Split a display path ("callbacks.'$request.body#/x'.post") into its keys,
    keeping a quoted key — one holding dots — whole."""
    return [a or b for a, b in re.findall(r"'([^']*)'|([^.]+)", element)]


def _splittable(at: Parts) -> bool:
    """Above an owner: a subtree present on one side only is split into its children
    here, so one part never swallows several owners (all of paths, all schemas)."""
    if at in ((), ("paths",), ("components",)):
        return True
    if len(at) == 2 and at[0] == "components" and at[1] in _COMPONENT_SECTIONS:
        return True
    return len(at) == 4 and at[0] == "paths" and at[2] in HTTP_METHODS and at[3] == "callbacks"


def _str_keys(node: dict) -> dict[str, Any]:
    return {str(k): v for k, v in node.items()}


def _labelled(at: Parts, items: list) -> dict[str, Any]:
    return {_item_label(at, i, v): v for i, v in enumerate(items)}


def diff_documents(official: Any, generated: Any, at: Parts = ()) -> list[Diff]:
    """Every place where the two documents differ: (kind, path, official, generated).

    Same leaf identity as layer 1 (comparison.flatten_parts): parameters by (in, name),
    other list items by position, enum / required as sets, keys as strings. A subtree
    on one side only is ONE entry (kind absent / extra, carrying that subtree) unless
    it sits above an owner.
    """
    if official is _MISSING or generated is _MISSING:
        node = generated if official is _MISSING else official
        if isinstance(node, dict) and node and _splittable(at):
            out = []
            for k, v in _str_keys(node).items():
                out += diff_documents(_MISSING if official is _MISSING else v,
                                      v if official is _MISSING else _MISSING, (*at, k))
            return out
        if not flatten_parts(node):                      # an empty container: no leaf
            return []
        if official is _MISSING:
            return [("extra", at, None, node)]
        return [("absent", at, node, None)]
    if at and at[-1] in SET_KEYWORDS and isinstance(official, list) \
            and isinstance(generated, list):
        same = sorted(map(str, official)) == sorted(map(str, generated))
        return [] if same else [("differing", at, official, generated)]
    pair = None
    if isinstance(official, dict) and isinstance(generated, dict):
        pair = _str_keys(official), _str_keys(generated)
    elif isinstance(official, list) and isinstance(generated, list):
        pair = _labelled(at, official), _labelled(at, generated)
    if pair:
        o, g = pair
        return [d for k in [*o, *(k for k in g if k not in o)]
                for d in diff_documents(o.get(k, _MISSING), g.get(k, _MISSING), (*at, k))]
    return [] if official == generated else [("differing", at, official, generated)]


def _unit(p: Parts, official: dict, generated: dict,
          misplaced: dict[Parts, str]) -> tuple[str, str, Parts]:
    """(owner, aspect, anchor) of a difference — the anchor is the whole piece the
    judge gets as context: the operation, the callback, the schema, the block."""
    def both(*keys: str) -> bool:
        return isinstance(_get(official, *keys), dict) and isinstance(_get(generated, *keys), dict)

    root = p[0] if p else ""
    if root == "paths" and len(p) >= 2:
        path = p[1]
        if len(p) == 2 or not both("paths", path):
            return f"PATH {path}", "path", p[:2]
        key = p[2]
        if key in HTTP_METHODS:
            owner, anchor = f"{key.upper()} {path}", p[:3]
            if len(p) == 3 or not both("paths", path, key):
                return owner, "operation", anchor
            if p[3] == "callbacks" and len(p) > 4:
                return owner, f"callback {p[4]}", (*anchor, "callbacks", p[4])
            return owner, _OP_ASPECTS.get(p[3], "operation"), anchor
        aspect = ("parameters" if key == "parameters" else
                  "path_item" if key in _PATH_ITEM_FIELDS else "unexpected_keys")
        return f"PATH {path}", aspect, p[:2]
    if root == "components" and len(p) >= 2:
        for n in (3, 2):
            if p[:n] in misplaced:
                return f"SCHEMA {misplaced[p[:n]]}", "placement", ("components", "schemas",
                                                                   misplaced[p[:n]])
        if p[1] == "schemas" and len(p) >= 3:
            name = p[2]
            if name in misplaced.values():
                return f"SCHEMA {name}", "placement", p[:3]
            off = _get(official, "components", "schemas", name)
            gen = _get(generated, "components", "schemas", name)
            aspect = ("missing" if gen is None else "extra" if off is None else "definition")
            return f"SCHEMA {name}", aspect, p[:3]
        if p[1] in _COMPONENT_SECTIONS and len(p) >= 3:
            return f"COMPONENT {p[1]}.{p[2]}", "definition", p[:3]
        if p[1] not in _COMPONENT_SECTIONS and any(            # a copy of a schema,
                _get(doc, "components", "schemas", p[1]) is not None   # outside its place
                for doc in (official, generated)):
            return f"SCHEMA {p[1]}", "placement", ("components", "schemas", p[1])
        return f"COMPONENTS {p[1]}", "block", p[:2]
    if root in METADATA_ROOTS or root.startswith("x-"):
        return f"DOCUMENT {root}", "metadata", p[:1]
    return f"DOCUMENT {root or '(root)'}", "block", p[:1]


def _path_item_view(item: Any) -> Any:
    """A path item as context for its own keys: every non-operation key whole, each
    operation by its identity and parameters (each operation has its own parts)."""
    if not isinstance(item, dict):
        return item
    out: dict[str, Any] = {}
    for k, v in _str_keys(item).items():
        if k in HTTP_METHODS and isinstance(v, dict):
            out[k] = {f: v[f] for f in ("operationId", "summary", "parameters") if f in v}
        else:
            out[k] = v
    return out


def _identity(doc: dict, path: str, method: str) -> str:
    op = _get(doc, "paths", path, method) or {}
    bits = [f"{method.upper()} {path}"] + [f"{f}: {op[f]}" for f in ("operationId", "summary")
                                            if isinstance(op, dict) and op.get(f)]
    return " — ".join(bits)


def _context(doc: dict, aspect: str, anchor: Parts, ats: list[Parts]) -> dict[str, Any] | None:
    """The whole owner on one side, keyed by where it is in the document; None if the
    side has none of it. `ats`: where this side holds the piece — a schema also
    defined outside components.schemas is shown at every place."""
    ctx: dict[str, Any] = {}
    for at in ats:
        node = _get(doc, *at)
        if node is None:
            continue
        if anchor[0] == "paths" and len(anchor) == 2 and aspect != "path":
            ctx[join(at) + " (operations: identity and parameters only — each is judged "
                "in its own part)"] = _path_item_view(node)
        else:
            ctx[join(at)] = node
    if aspect == "parameters" and len(anchor) == 3:           # an operation's parameters
        shared = _get(doc, "paths", anchor[1], "parameters")
        if shared is not None:
            ctx[join(("paths", anchor[1], "parameters"))] = shared
    if aspect.startswith("callback ") and ctx:
        ctx = {"registered by": _identity(doc, anchor[1], anchor[2]), **ctx}
    return ctx or None


def _leaf_count(p: Parts, official: Any, generated: Any) -> int:
    """How many layer-1 leaves a difference spans: the union of both sides' leaves
    under it (one side only for absent / extra), keyed as layer 1 keys them."""
    key = p[-1] if p else ""
    sides = [flatten_parts({key: v}) for v in (official, generated) if v is not None]
    return len(set().union(*sides)) or 1


def _where(p: Parts, aspect: str, anchor: Parts, misplaced: dict[Parts, str]) -> Parts:
    """The location a difference is judged at: the aspect's key in an operation or a
    path item, each field of an operation, the copy of a schema, else the owner."""
    if p[:len(anchor)] != anchor:                               # placement: elsewhere
        return next((at for at in misplaced if p[:len(at)] == at), p[:2])
    if anchor[0] == "paths" and len(anchor) == 3 and aspect == "operation":
        return p
    in_item = anchor[0] == "paths" and len(anchor) in (2, 3) and aspect not in (
        "path", "operation")
    return p[:len(anchor) + 1] if in_item and len(p) > len(anchor) else anchor


def _term(rel: Parts, fallback: str) -> str:
    """The element a difference is about, named: a code, a parameter, a media type,
    a property — read through comparison.element."""
    keys = [k for k in (element(rel) if rel else ()) if not re.fullmatch(r"\[\d+\]", k)]
    key = keys[-1] if keys else fallback
    m = re.fullmatch(r"\[in=[^,]*,name=(.*)\]", key)
    return m.group(1) if m else key


def _facts(aspect: str, op: OperationScore | None, schema: SchemaScore | None) -> list[str]:
    """What layer 1 already says about this aspect, in words."""
    if op is not None:
        facts = {
            "parameters": [op.params_missing and f"parameters missing {op.params_missing}",
                           op.params_extra and f"parameters extra {op.params_extra}",
                           op.params_at_path_level and
                           f"declared on the path item, not on this operation: "
                           f"{op.params_at_path_level}"],
            "request_body": [op.media_missing and f"media types missing {op.media_missing}",
                             op.media_extra and f"media types extra {op.media_extra}"],
            "responses": [op.responses_missing and f"codes missing {op.responses_missing}",
                          op.responses_extra and f"codes extra {op.responses_extra}"],
            "operation": [op.status != "present" and
                          f"operation {op.status} in the generated document"],
            "path": [op.status != "present" and
                     f"path item {op.status} in the generated document"],
        }.get(aspect, [])
        return [f for f in facts if f]
    if schema is not None:
        return [f for f in [
            f"schema {schema.status}" + (f" (at {schema.found_at})" if schema.found_at else ""),
            schema.shape_official != schema.shape_generated and
            f"shape official {schema.shape_official or '—'} vs generated "
            f"{schema.shape_generated or '—'}",
            schema.note] if f]
    return []


def generator_parts(report: OpenAPIEvaluation, generated: dict, official: dict,
                    input_label: str = "") -> list[Part]:
    """The divergent parts of a generated document — every difference in exactly one.

    Each difference between the two documents (contract, metadata and prose alike) is
    given to the owner it sits in; the part carries that whole owner on both sides,
    and the differences as its focus. Nothing that differs is left out.
    """
    label = input_label or report.generated.label
    misplaced = {tuple(_keys(s.found_at)): s.name for s in report.schemas
                 if s.status == "misplaced"}
    ops = {o.operation: o for o in report.operations}
    schemas = {s.name: s for s in report.schemas}

    units: dict[tuple[str, str], tuple[Parts, list[Diff]]] = {}
    for kind, p, o_val, g_val in diff_documents(official, generated):
        owner, aspect, anchor = _unit(p, official, generated, misplaced)
        units.setdefault((owner, aspect), (anchor, []))[1].append((kind, p, o_val, g_val))

    parts: list[Part] = []
    locations: dict[str, list[str]] = {}       # part id → document locations it judges
    for (owner, aspect), (anchor, diffs) in units.items():
        g_ats = [anchor]
        if aspect == "placement":                # where else the generated side defines it
            g_ats += list(dict.fromkeys(
                next((at for at in misplaced if p[:len(at)] == at), p[:2])
                for _, p, _, _ in diffs if p[:len(anchor)] != anchor))
        focus = list(dict.fromkeys(join(_where(p, aspect, anchor, misplaced))
                                   for _, p, _, _ in diffs))

        differences = [
            Difference(kind=k, location=join(p), leaves=_leaf_count(p, o_val, g_val),
                       official=o_val if k == "differing" else None,
                       generated=g_val if k == "differing" else None)
            for k, p, o_val, g_val in diffs]
        terms = list(dict.fromkeys(
            [_term(p[len(anchor):], anchor[-1]) for _, p, _, _ in diffs] +
            [str(v) for k, _, o_val, g_val in diffs if k == "differing" for v in (o_val, g_val)
             if v is not None and not isinstance(v, (dict, list)) and len(str(v)) <= 60]))
        kinds = defaultdict(int)
        for d in differences:
            kinds[d.kind] += 1
        counts = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        op_score = ops.get(owner)
        schema_score = schemas.get(owner.split(" ", 1)[1]) if owner.startswith("SCHEMA ") \
            else None
        facts = _facts(aspect, op_score, schema_score)
        if aspect == "placement":
            facts.append("generated defines it at " + ", ".join(
                join(at) for at in g_ats if _get(generated, *at) is not None))
        summary = "; ".join(facts + [counts])

        path = anchor[1] if anchor[0] == "paths" else ""
        method = anchor[2] if anchor[0] == "paths" and len(anchor) > 2 else ""
        names, external = _ref_hints(*[v for _, _, o_val, g_val in diffs
                                       for v in (o_val, g_val)])
        if owner.startswith("SCHEMA "):
            names = [owner.split(" ", 1)[1], *names]
        terms_hint = ([aspect.split(" ", 1)[1]] if aspect.startswith("callback ") else
                      [t for t in (_get(official, "paths", path, method, "operationId"),
                                   _get(official, "paths", path, method, "summary"))
                       if isinstance(t, str)] if method else [])
        part = Part(
            id=f"generator|{label}|{owner}|{aspect}", evaluation="generator", input=label,
            owner=owner, aspect=aspect, summary=summary, focus=focus,
            differences=differences, diff_terms=terms,
            official=_context(official, aspect, anchor, [anchor]),
            generated=_context(generated, aspect, anchor, g_ats),
            hints=SearchHints(path=path, method=method, schemas=list(dict.fromkeys(names)),
                              external_refs=external, terms=terms_hint))
        parts.append(part)
        locations[part.id] = focus

    _attach_issues(parts, locations, [f"{i.location}: {i.message}"
                                      for i in report.validity_generated.issues])
    return parts


def node_at(context: Any, location: str) -> Any:
    """The node at a display location ("paths./x.get.parameters[in=query,name=s]")
    inside a part's context ({display location of a whole piece: node}); None if the
    side does not have it."""
    if not isinstance(context, dict):
        return None
    for key, node in context.items():
        base = key.split(" (", 1)[0]
        if location == base:
            return node
        if not location.startswith((base + ".", base + "[")):
            continue
        rest = location[len(base):].lstrip(".")
        for step in _keys(rest):
            name, _, labels = step.partition("[")
            if name:
                node = _str_keys(node).get(name) if isinstance(node, dict) else None
            for label in re.findall(r"\[[^\]]*\]", "[" + labels) if labels else []:
                node = (_labelled(_parent_key(name), node).get(label)
                        if isinstance(node, list) else None)
            if node is None:
                return None
        return node
    return None


def _parent_key(name: str) -> Parts:
    return (name,) if name else ()


def document_owners(report: OpenAPIEvaluation, generated: dict, official: dict) -> list[str]:
    """Every owner of either document — operation, path item, schema, component,
    block — as generator_parts names them; an owner with no part is equal."""
    misplaced = {tuple(_keys(s.found_at)): s.name for s in report.schemas
                 if s.status == "misplaced"}
    owners: dict[str, None] = {}
    for doc in (official, generated):
        for p in flatten_parts(doc):
            owners[_unit(p, official, generated, misplaced)[0]] = None
    return list(owners)


REGIONS = ("endpoints", "data types", "other components", "document header")


def region(owner: str) -> str:
    """The region of the document an owner sits in:
      endpoints         paths — each operation (method + path) and its parameters,
                        request body, responses and callbacks
      data types        components.schemas — the data models the endpoints use
      other components  the rest of components, and blocks outside their place
      document header   info, servers, externalDocs, openapi, tags, security, x-*
                        — about the document, not the API (never scored)"""
    head = owner.split(" ", 1)[0]
    if head == "SCHEMA":
        return "data types"
    if head in ("COMPONENT", "COMPONENTS"):
        return "other components"
    if head == "DOCUMENT":
        return "document header"
    return "endpoints"


def leaf_census(report: OpenAPIEvaluation, generated: dict,
                official: dict) -> dict[str, dict[str, int]]:
    """{region: counts} over the VALUES of both documents — a value is one leaf, a field
    holding a final value (info.title, ...responses.200.description), as layer 1 counts
    them. Per region: official / generated (values in each), total (distinct values in
    either), equal, changed (both have it, other value), only_official, only_generated.
    total = equal + changed + only_official + only_generated."""
    misplaced = {tuple(_keys(s.found_at)): s.name for s in report.schemas
                 if s.status == "misplaced"}
    o, g = flatten_parts(official), flatten_parts(generated)
    keys = ("official", "generated", "total", "equal", "changed", "only_official",
            "only_generated")
    out = {r: dict.fromkeys(keys, 0) for r in REGIONS}
    for p in {*o, *g}:
        c = out[region(_unit(p, official, generated, misplaced)[0])]
        c["total"] += 1
        c["official"] += p in o
        c["generated"] += p in g
        if p in o and p in g:
            c["equal" if o[p] == g[p] else "changed"] += 1
        else:
            c["only_official" if p in o else "only_generated"] += 1
    return out


def nature(part: Part) -> str:
    """missing: all it differs by is absent from the generated side; extra: all of it
    is added by the generated side; changed: anything else."""
    kinds = {d.kind for d in part.differences}
    return "missing" if kinds == {"absent"} else "extra" if kinds == {"extra"} else "changed"


def _attach_issues(parts: list[Part], locations: dict[str, list[str]],
                   issues: list[str]) -> None:
    """Give each layer-2 issue to the most specific part that holds it.

    An issue belongs to a part when it sits inside the part's location, or sits on
    the part's DIRECT parent and names the part's key ("components: 'MoiChange' ...
    unexpected") — a deeper descendant with the same key name is another thing.
    """
    for issue in issues:
        where, _, message = issue.partition(": ")
        named: list[Part] = []                 # parts the issue names (direct children)
        best, best_len = None, -1               # else: the most specific part holding it
        for part in parts:
            for loc in locations[part.id]:
                key = _keys(loc)[-1]
                if loc == f"{where}.{join((key,))}" and f"'{key}'" in message:
                    if part not in named:
                        named.append(part)
                elif (where == loc or where.startswith((loc + ".", loc + "["))) \
                        and len(loc) > best_len:
                    best, best_len = part, len(loc)
        for part in named or ([best] if best is not None else []):
            part.invalid_issues.append(issue)


# ── rules bank ───────────────────────────────────────────────────────────────

def _address(rule: dict) -> str:
    m = rule.get("openapi_mapping") or {}
    return f"{rule.get('rule_type', '?')} {m.get('openapi_object', '')} · {m.get('openapi_field', '')}"


def _bank_side(rule: dict) -> dict:
    """What of a bank rule the judge sees: its address, value, origin and validation."""
    return {k: rule.get(k) for k in ("rule_type", "section_title", "source_name", "rule_text",
                                     "openapi_mapping", "validation_passed")}


def _path_method(obj: str) -> tuple[str, str]:
    m = re.match(rf"^paths\.(/[^.]*(?:\.[^.]+)*?)(?:\.({'|'.join(HTTP_METHODS)}))?(?:\.|$)", obj)
    if not m:
        return "", ""
    return m.group(1), (m.group(2) or "")


def _rule_part(label: str, owner: str, aspect: str, summary: str, official: dict | None,
               bank_rules: list[dict], suffix: str = "") -> Part:
    """One rule part. Its id holds the rule's full key (rule_key — for a request body,
    the media type is part of it) so two rules never share an id."""
    rule = official or (bank_rules[0] if bank_rules else {})
    suffix = "|" + "|".join(rule_key(rule)) + suffix
    mapping = rule.get("openapi_mapping") or {}
    obj = mapping.get("openapi_object", "")
    path, method = _path_method(obj)
    schema = obj.split("components/schemas/", 1)[1] if "components/schemas/" in obj else ""
    texts = [str((r.get("openapi_mapping") or {}).get("openapi_value", "")) for r in
             [*(bank_rules or []), *([official] if official else [])]]
    names, external = _ref_hints_in_text(*texts)
    clause = next((clause_of(r.get("section_title", "")) for r in bank_rules
                   if r.get("section_title")), "")
    generated: Any = ([_bank_side(r) for r in bank_rules] if len(bank_rules) > 1
                      else _bank_side(bank_rules[0]) if bank_rules else None)
    return Part(
        id=f"rulesbank|{label}|{owner}|{aspect}{suffix}", evaluation="rulesbank", input=label,
        owner=owner, aspect=aspect, summary=summary, official=official, generated=generated,
        hints=SearchHints(clause=clause, path=path, method=method,
                          schemas=list(dict.fromkeys(([schema] if schema else []) + names)),
                          external_refs=external,
                          terms=[t for t in {r.get("source_name", "") for r in bank_rules} if t]))


def rulesbank_parts(report: RulesBankEvaluation, bank: dict, input_label: str = "") -> list[Part]:
    """The divergent parts of a rules bank, from its evaluation report."""
    label = input_label or report.bank.label
    rules = [r for r in (bank.get("rules") or []) if isinstance(r, dict)]
    parts: list[Part] = []
    for m in report.matches:
        bank_rules = [rules[b.index] for b in m.bank]
        owner = _address(m.expected)
        if len(m.bank) > 1:
            parts.append(_rule_part(label, owner, "duplicate",
                                    f"{len(m.bank)} bank rules on one official address "
                                    f"(rules {[b.index for b in m.bank]}); first value: "
                                    f"{m.value_status}" + (f" — {m.note}" if m.note else ""),
                                    m.expected, bank_rules))
        elif m.value_status == "different":
            parts.append(_rule_part(label, owner, "different", f"value differs — {m.note}",
                                    m.expected, bank_rules))
    for r in report.missing:
        parts.append(_rule_part(label, _address(r), "missing",
                                "official rule with no bank rule on its address", r, []))
    for x in report.extra:
        rule = rules[x.rule.index]
        parts.append(_rule_part(label, _address(rule), "extra",
                                f"bank rule on no official address ({x.reason})", None, [rule],
                                suffix=f"#{x.rule.index}"))
    return parts
