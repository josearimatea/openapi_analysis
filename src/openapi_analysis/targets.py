"""Enumerate the extractable TARGETS of an official OpenAPI YAML.

A *target* is one addressable thing the rules bank is expected to produce a rule
for, identified exactly as the GENERATOR addresses its rules. Coverage is measured
by matching bank rules against this set, so the enumeration must mirror the
generator's contract (openapi_rulesbank/utils/rules_check.py), not an independent
reading of the YAML — otherwise a rule and its target would never line up.

This module also replaces the ad-hoc extractors that mis-counted targets three
times (see Problems_ProvMnS.txt "LIÇÃO DE INSTRUMENTO"): the worst found 54 where
there were more, by not descending into oneOf/allOf. The counting rules below are
explicit and pinned by a test.

THE GENERATOR'S ADDRESSING CONTRACT (from rules_check.py — mirror it here):

  path_operation  object "paths.<path>"                       field "<method>"
  path_parameter  object "paths.<path>[.<method>]"            field "parameters[in=path,name=<n>]"
  query_parameter object "paths.<path>[.<method>]"            field "parameters[in=query,name=<n>]"
  request_body    object "paths.<path>.<method>.requestBody"  field "content"   value "<mediaType>"
  response        object "paths.<path>.<method>.responses"    field "<code>"
  callback        object "paths.<path>.<method>.callbacks.<name>"  field "<method>"
  schema_property object "components/schemas/<Name>"          field "properties.<n>" | keyword

  A parameter at the PATH level applies to every method; at the OPERATION level only
  to that method. Both are modelled, because a rule that puts an operation param at
  path level is the §3.22 defect and coverage can only catch it if the target is at
  the operation level.

  For request_body the generator puts the media type in openapi_VALUE (field is
  always "content"). So the media type is part of the target's IDENTITY here — four
  media types on one operation are four distinct targets — while for every other
  rule_type the value is content to be checked later, not identity.

  Schema descent goes through oneOf / anyOf / allOf / properties / items. A $ref
  (internal or external) is a leaf: the reference is the target, its interior is not
  enumerated (§3.10). A collection-valued keyword (enum, required, oneOf, anyOf,
  allOf, items, additionalProperties) is ONE target — its value is the whole
  collection (§3.27).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

# schema-level keywords the generator accepts as a schema_property field
# (rules_check.py _VALID_SCHEMA_KEYWORDS). Each is one target.
SCHEMA_KEYWORDS = ("enum", "required", "oneOf", "anyOf", "allOf", "items",
                   "additionalProperties")
# the subset that also drives recursive descent into subschemas
COMPOSITION_KEYWORDS = ("oneOf", "anyOf", "allOf")


@dataclass(frozen=True)
class Target:
    """One addressable expectation in the official YAML.

    `value` is part of the identity ONLY for request_body (the generator encodes the
    media type there with a constant field of "content"); it is "" for every other
    rule_type, so it never splits their keys.
    """
    rule_type: str
    openapi_object: str
    openapi_field: str
    value: str = ""

    def key(self) -> tuple[str, str, str, str]:
        return (self.rule_type, self.openapi_object, self.openapi_field, self.value)


def _emit_param(prm: dict, obj: str, out: list[Target]) -> None:
    if not isinstance(prm, dict):
        return
    loc = prm.get("in")
    nm = prm.get("name")
    rule_type = "path_parameter" if loc == "path" else "query_parameter"
    out.append(Target(rule_type, obj, f"parameters[in={loc},name={nm}]"))


def _emit_operation(obj_op: str, op: dict, out: list[Target]) -> None:
    """Targets for one operation object: its params, request body, responses.

    Used for both a top-level operation and a callback's delivery operation, since
    the generator addresses a callback's insides the same way (…callbacks.<n>.post.…).
    """
    for prm in op.get("parameters", []) or []:
        _emit_param(prm, obj_op, out)
    rb = op.get("requestBody")
    if isinstance(rb, dict):
        for mt in (rb.get("content") or {}):
            out.append(Target("request_body", f"{obj_op}.requestBody", "content", value=mt))
    for code in (op.get("responses") or {}):
        out.append(Target("response", f"{obj_op}.responses", str(code)))


def _walk_schema(schema_name: str, node, out: list[Target], seen: set[int]) -> None:
    """Collect schema targets for one root schema, descending inline composition.

    schema_name stays the ROOT schema for every target (the generator addresses a
    schema rule by its root). Recursion follows inline oneOf/anyOf/allOf, object
    properties, and array items, but stops at any $ref — a ref is a leaf.
    """
    if not isinstance(node, dict):
        return
    nid = id(node)
    if nid in seen:
        return
    seen.add(nid)

    if "$ref" in node:            # ref leaf: no target of its own here
        return

    obj = f"components/schemas/{schema_name}"

    for kw in SCHEMA_KEYWORDS:
        if kw in node:
            # additionalProperties=true (a bool) is not an addressable schema element
            if kw == "additionalProperties" and not isinstance(node[kw], dict):
                continue
            out.append(Target("schema_property", obj, kw))
            if kw in COMPOSITION_KEYWORDS:
                for sub in node[kw]:
                    _walk_schema(schema_name, sub, out, seen)
            elif kw in ("items", "additionalProperties"):
                _walk_schema(schema_name, node[kw], out, seen)

    props = node.get("properties")
    if isinstance(props, dict):
        for pname, pnode in props.items():
            out.append(Target("schema_property", obj, f"properties.{pname}"))
            if isinstance(pnode, dict) and "$ref" not in pnode:
                _walk_schema(schema_name, pnode, out, seen)


def targets_from_yaml(spec: dict) -> list[Target]:
    """Enumerate every target in a loaded OpenAPI document, deduplicated.

    Deterministic order: paths (document order), then schemas (document order,
    depth-first). Duplicate keys collapse — a target is a position, expected once
    however many times it appears structurally.
    """
    out: list[Target] = []

    for path, pitem in (spec.get("paths") or {}).items():
        if not isinstance(pitem, dict):
            continue
        obj_path = f"paths.{path}"
        for prm in pitem.get("parameters", []) or []:
            _emit_param(prm, obj_path, out)
        for meth in HTTP_METHODS:
            op = pitem.get(meth)
            if not isinstance(op, dict):
                continue
            obj_op = f"{obj_path}.{meth}"
            out.append(Target("path_operation", obj_path, meth))
            _emit_operation(obj_op, op, out)
            # callbacks hang off the operation where the consumer supplies its address
            for cb_name, cb in (op.get("callbacks") or {}).items():
                if not isinstance(cb, dict):
                    continue
                obj_cb = f"{obj_op}.callbacks.{cb_name}"
                for _expr, cb_item in cb.items():
                    if not isinstance(cb_item, dict):
                        continue
                    for cb_meth in HTTP_METHODS:
                        cb_op = cb_item.get(cb_meth)
                        if not isinstance(cb_op, dict):
                            continue
                        # the callback rule itself: field is the delivery method
                        out.append(Target("callback", obj_cb, cb_meth))
                        # its request body + responses, addressed under the callback
                        _emit_operation(f"{obj_cb}.{cb_meth}", cb_op, out)

    schemas = (spec.get("components") or {}).get("schemas") or {}
    for sname, snode in schemas.items():
        _walk_schema(sname, snode, out, seen=set())

    seen_keys: set[tuple] = set()
    unique: list[Target] = []
    for t in out:
        if t.key() not in seen_keys:
            seen_keys.add(t.key())
            unique.append(t)
    return unique


def summarize(targets: list[Target]) -> dict[str, int]:
    """Count of targets per rule_type, plus total, for reports and the pinning test."""
    counts = dict(Counter(t.rule_type for t in targets))
    counts["total"] = len(targets)
    return counts
