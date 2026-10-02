"""Extract the rules of an official OpenAPI YAML, in the rules-bank format.

Each rule is emitted exactly as openapi_rulesbank would write it — same rule_type,
same openapi_mapping address, and an openapi_value / references[] in the shapes
its extractor prompt asks for — so the official rules and a generated bank can be
compared rule by rule (comparison.py). The definition followed here is
rule_types.py; see docs/RULES.md for the decisions behind it.

  path_operation  paths.<path>                              · <method>        · "GET"
  path_parameter  paths.<path> | paths.<path>.<method>      · parameters[in=path,name=<n>]
  query_parameter paths.<path>.<method>                     · parameters[in=query,name=<n>]
                  (value: the schema — a type, or "$ref: '<ref>'")
  request_body    paths.<path>.<method>.requestBody         · content         · <mediaType>
  response        paths.<path>.<method>.responses           · <code>          · body schema
  callback        paths.<path>.<method>.callbacks.<name>    · <delivery method> · {expression}
  schema_property components/schemas/<Root>                 · properties.<n> | keyword
  A callback's own request body and responses continue its anchor:
                  paths.<path>.<method>.callbacks.<name>.<deliveryMethod>.requestBody / .responses

Counting choices (pinned by tests):
  - A parameter is addressed at the level the YAML declares it. Parameters
    in: header / cookie have no rule_type and are not extracted (docs/RULES.md).
  - Schema descent goes through oneOf / anyOf / allOf / properties / items /
    additionalProperties, always addressed by the ROOT schema. A $ref is a leaf: the
    reference is the value, its interior belongs to the referenced schema (§3.10).
  - A collection keyword (enum, required, oneOf, ...) is ONE rule whose value is the
    whole collection (§3.27).
  - A key met twice (the same property name at two nesting levels of one schema)
    is one rule; the first occurrence, in document order, gives its value.

Not descending into oneOf/allOf is the bug that once counted 54 targets where there
were more; the descent above is what the pinning tests guard.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any

from openapi_analysis.rulesbank.rule_types import HTTP_METHODS, SCHEMA_KEYWORDS, rule_key

# the keywords that also drive recursive descent into subschemas
COMPOSITION_KEYWORDS = ("oneOf", "anyOf", "allOf")
# parameter locations that have a rule_type
PARAMETER_RULE_TYPES = {"path": "path_parameter", "query": "query_parameter"}


# ── values, in the shapes the rules-bank extractor prompt asks for ───────────

def _ref_entry(ref: str) -> dict[str, str]:
    """'File.yaml#/components/schemas/X' → {"file": "File.yaml", "schema_name": "X"}."""
    file, _, pointer = ref.partition("#")
    return {"file": file, "schema_name": pointer.rsplit("/", 1)[-1]}


def _refs_in(node: Any) -> Iterator[str]:
    """The $refs the value of a rule points at — SHALLOW, never nested ones.

    A schema → its own $ref; an array schema → its element's $ref (an "array of X"
    is typed by X, which is what the bank writes); a list (oneOf/allOf members,
    several media types) → that of each member. A $ref nested deeper (a property
    inside an inline allOf member) belongs to the rule addressing that deeper
    element, not to this one — counting it here would make one missing ref fail
    two rules.
    """
    members = node if isinstance(node, list) else [node]
    for member in members:
        if not isinstance(member, dict):
            continue
        if isinstance(member.get("$ref"), str):
            yield member["$ref"]
        elif member.get("type") == "array" and isinstance(member.get("items"), dict) \
                and isinstance(member["items"].get("$ref"), str):
            yield member["items"]["$ref"]


def _references(node: Any) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    for ref in _refs_in(node):
        entry = _ref_entry(ref)
        if entry not in seen:
            seen.append(entry)
    return seen


def _schema_value(node: Any) -> str:
    """A schema as a short value: "$ref: '<ref>'", a type, or "" when it has neither."""
    if isinstance(node, bool):
        return str(node).lower()
    if not isinstance(node, dict):
        return ""
    if isinstance(node.get("$ref"), str):
        return f"$ref: '{node['$ref']}'"
    if isinstance(node.get("type"), str):
        return node["type"]
    for kw in COMPOSITION_KEYWORDS:
        if kw in node:
            return kw
    return ""


def _list_value(items: list) -> str:
    return "[" + ", ".join(_schema_value(i) if isinstance(i, dict) else str(i)
                           for i in items) + "]"


def _rule(rule_type: str, obj: str, field: str, value: str = "",
          refs_from: Any = None) -> dict[str, Any]:
    return {"rule_type": rule_type,
            "openapi_mapping": {"openapi_object": obj, "openapi_field": field,
                                "openapi_value": value,
                                "references": _references(refs_from)}}


# ── paths ────────────────────────────────────────────────────────────────────

def _resolve(node: Any, spec: dict) -> Any:
    """Follow a LOCAL $ref (#/...); an external one is returned as it is."""
    if isinstance(node, dict) and str(node.get("$ref", "")).startswith("#/"):
        target: Any = spec
        for part in node["$ref"][2:].split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        return target
    return node


def _emit_param(prm: Any, obj: str, spec: dict, out: list[dict]) -> None:
    prm = _resolve(prm, spec)
    if not isinstance(prm, dict):
        return
    rule_type = PARAMETER_RULE_TYPES.get(prm.get("in"))
    if rule_type is None:          # header / cookie: no rule_type covers them
        return
    schema = prm.get("schema")
    out.append(_rule(rule_type, obj, f"parameters[in={prm['in']},name={prm.get('name')}]",
                     _schema_value(schema), refs_from=schema))


def _response_value(resp: Any) -> tuple[str, Any]:
    """(value, node to take references from) for one response.

    The value is the body schema; a response with no body (204) has value "". When
    several media types carry different schemas, the value lists them all.
    """
    if not isinstance(resp, dict):
        return "", None
    if isinstance(resp.get("$ref"), str):
        return f"$ref: '{resp['$ref']}'", resp
    content = resp.get("content") or {}
    schemas = [mt.get("schema") for mt in content.values() if isinstance(mt, dict)]
    values = list(dict.fromkeys(_schema_value(s) for s in schemas if s is not None))
    if len(values) <= 1:
        return (values[0] if values else ""), schemas
    return "[" + ", ".join(values) + "]", schemas


def _emit_operation(obj_op: str, op: dict, spec: dict, out: list[dict]) -> None:
    """Rules for one operation object: its params, request body, responses.

    Used for both a top-level operation and a callback's delivery operation, since
    the bank addresses a callback's insides the same way (…callbacks.<n>.post.…).
    """
    for prm in op.get("parameters", []) or []:
        _emit_param(prm, obj_op, spec, out)
    rb = _resolve(op.get("requestBody"), spec)
    if isinstance(rb, dict):
        for mt, media in (rb.get("content") or {}).items():
            out.append(_rule("request_body", f"{obj_op}.requestBody", "content", mt,
                             refs_from=(media or {}).get("schema")))
    for code, resp in (op.get("responses") or {}).items():
        value, refs_from = _response_value(resp)
        out.append(_rule("response", f"{obj_op}.responses", str(code), value,
                         refs_from=refs_from))


def _emit_paths(spec: dict, out: list[dict]) -> None:
    for path, pitem in (spec.get("paths") or {}).items():
        if not isinstance(pitem, dict):
            continue
        obj_path = f"paths.{path}"
        for prm in pitem.get("parameters", []) or []:
            _emit_param(prm, obj_path, spec, out)
        for meth in HTTP_METHODS:
            op = pitem.get(meth)
            if not isinstance(op, dict):
                continue
            obj_op = f"{obj_path}.{meth}"
            out.append(_rule("path_operation", obj_path, meth, meth.upper()))
            _emit_operation(obj_op, op, spec, out)
            # callbacks hang off the operation where the consumer supplies its address
            for cb_name, cb in (op.get("callbacks") or {}).items():
                if not isinstance(cb, dict):
                    continue
                obj_cb = f"{obj_op}.callbacks.{cb_name}"
                for expr, cb_item in cb.items():
                    if not isinstance(cb_item, dict):
                        continue
                    for cb_meth in HTTP_METHODS:
                        cb_op = cb_item.get(cb_meth)
                        if not isinstance(cb_op, dict):
                            continue
                        # the callback itself: field = delivery method, value = expression
                        out.append(_rule("callback", obj_cb, cb_meth, str(expr)))
                        _emit_operation(f"{obj_cb}.{cb_meth}", cb_op, spec, out)


# ── schemas ──────────────────────────────────────────────────────────────────

def _keyword_value(kw: str, value: Any) -> str:
    if kw in ("enum", "required"):
        return "[" + ", ".join(str(v) for v in value) + "]"
    if kw in COMPOSITION_KEYWORDS:
        return _list_value(value)
    return _schema_value(value)     # items, additionalProperties


def _walk_schema(schema_name: str, node: Any, out: list[dict], seen: set[int]) -> None:
    """Collect the rules of one root schema, descending inline composition.

    schema_name stays the ROOT schema for every rule (the bank addresses a schema
    rule by its root). Recursion follows inline oneOf/anyOf/allOf, object
    properties, items and additionalProperties, and stops at any $ref.
    """
    if not isinstance(node, dict) or id(node) in seen or "$ref" in node:
        return
    seen.add(id(node))
    obj = f"components/schemas/{schema_name}"

    for kw in SCHEMA_KEYWORDS:
        if kw not in node:
            continue
        # additionalProperties: true/false is a switch, not an addressable schema
        if kw == "additionalProperties" and not isinstance(node[kw], dict):
            continue
        out.append(_rule("schema_property", obj, kw, _keyword_value(kw, node[kw]),
                         refs_from=node[kw] if kw not in ("enum", "required") else None))
        if kw in COMPOSITION_KEYWORDS:
            for sub in node[kw]:
                _walk_schema(schema_name, sub, out, seen)
        elif kw in ("items", "additionalProperties"):
            _walk_schema(schema_name, node[kw], out, seen)

    props = node.get("properties")
    if isinstance(props, dict):
        for pname, pnode in props.items():
            out.append(_rule("schema_property", obj, f"properties.{pname}",
                             _schema_value(pnode), refs_from=pnode))
            _walk_schema(schema_name, pnode, out, seen)


# ── public ───────────────────────────────────────────────────────────────────

def rules_from_yaml(spec: dict) -> list[dict[str, Any]]:
    """Every rule of a parsed OpenAPI document, in the rules-bank format, one per key.

    Deterministic order: paths (document order), then schemas (document order,
    depth-first).
    """
    out: list[dict] = []
    _emit_paths(spec, out)
    for sname, snode in ((spec.get("components") or {}).get("schemas") or {}).items():
        _walk_schema(sname, snode, out, seen=set())

    seen_keys: set[tuple] = set()
    unique: list[dict] = []
    for rule in out:
        if rule_key(rule) not in seen_keys:
            seen_keys.add(rule_key(rule))
            unique.append(rule)
    return unique


def summarize(rules: list[dict]) -> dict[str, int]:
    """Count of rules per rule_type, plus total."""
    counts = dict(Counter(r["rule_type"] for r in rules))
    counts["total"] = len(rules)
    return counts
