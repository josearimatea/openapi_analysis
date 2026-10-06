"""Cut the divergences found by layers 1 and 2 into PARTS for the judge.

Deterministic, no LLM, no retrieval: it only reads the evaluation reports and the
documents they were computed from. A part is small enough to aim a retrieval at it
(docs/JUDGE_PLAN.md §3) — what is equal to the official YAML never becomes a part.

Generator (OpenAPIEvaluation + both documents) — one part per aspect of an owner:
    operation  owner "PATCH /x"   aspects: parameters | request_body | responses |
                                           callbacks | operation (missing / extra op)
    path item  owner "PATH /x"    aspects: parameters | unexpected_keys | path
    schema     owner "SCHEMA N"   aspects: definition | placement | missing | extra
Rules bank (RulesBankEvaluation + the bank) — one part per rule:
    different  a bank rule on an official address, with another value
    duplicate  several bank rules on one official address (covers their values too)
    missing    an official rule the bank does not have
    extra      a bank rule on no official address

Layer-2 issues (not valid OpenAPI 3.0) are attached to the part they fall in — the
most specific one whose location contains them, or whose key they name — so a part
already invalid can be ruled an error without asking the LLM.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from openapi_analysis.judge.spec_index import clause_of
from openapi_analysis.openapi.comparison import join
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS, rule_key
from openapi_analysis.schemas.judge import Part, SearchHints
from openapi_analysis.schemas.openapi import OpenAPIEvaluation
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

def _keys(element: str) -> list[str]:
    """Split a display path ("callbacks.'$request.body#/x'.post") into its keys,
    keeping a quoted key — one holding dots — whole."""
    return [a or b for a, b in re.findall(r"'([^']*)'|([^.]+)", element)]


def _detail_aspect(owner: str, element: str) -> str:
    head = _keys(element)[0].split("[")[0]
    if owner.startswith("PATH "):
        return "parameters" if head == "parameters" else "unexpected_keys"
    if owner.startswith("SCHEMA "):
        return "definition"
    return _OP_ASPECTS.get(head, "operation")


def _counts(details: list) -> str:
    kinds = defaultdict(int)
    for d in details:
        kinds[d.kind] += d.leaves
    return ", ".join(f"{n} leaves {k}" for k, n in sorted(kinds.items()))


def generator_parts(report: OpenAPIEvaluation, generated: dict, official: dict,
                    input_label: str = "") -> list[Part]:
    """The divergent parts of a generated document, from its evaluation report."""
    label = input_label or report.generated.label
    by_owner_aspect: dict[tuple[str, str], list] = defaultdict(list)
    for d in report.details:
        if d.owner != "OTHER":
            by_owner_aspect[(d.owner, _detail_aspect(d.owner, d.element))].append(d)

    parts: list[Part] = []
    locations: dict[str, list[str]] = {}       # part id → document locations it covers

    def add(part: Part, locs: list[str]) -> None:
        parts.append(part)
        locations[part.id] = locs

    for op in report.operations:
        verb, path = op.operation.split(" ", 1)
        p_loc = f"paths.{join((path,))}"
        o_item, g_item = _get(official, "paths", path), _get(generated, "paths", path)

        if verb == "PATH":
            if op.status != "present":
                node_o, node_g = o_item, g_item
                add(_gen_part(label, op.operation, "path",
                              f"path item {op.status} in the generated document",
                              node_o, node_g, path=path), [p_loc])
                continue
            details = by_owner_aspect.get((op.operation, "parameters"), [])
            if op.params_missing or op.params_extra or details:
                summary = "; ".join(filter(None, [
                    op.params_missing and f"missing {op.params_missing}",
                    op.params_extra and f"extra {op.params_extra}",
                    _counts(details)]))
                add(_gen_part(label, op.operation, "parameters",
                              f"path-level parameters: {summary}",
                              _get(o_item, "parameters"), _get(g_item, "parameters"),
                              path=path), [f"{p_loc}.parameters"])
            odd = by_owner_aspect.get((op.operation, "unexpected_keys"), [])
            if odd:
                keys = sorted({_keys(d.element)[0] for d in odd})
                add(_gen_part(label, op.operation, "unexpected_keys",
                              f"keys in the path item that are not operations: {keys}",
                              None, {k: _get(g_item, k) for k in keys}, path=path), [p_loc])
            continue

        method = verb.lower()
        o_op, g_op = _get(o_item, method), _get(g_item, method)
        op_loc = f"{p_loc}.{method}"
        if op.status != "present":
            add(_gen_part(label, op.operation, "operation",
                          f"operation {op.status} in the generated document",
                          o_op, g_op, path=path, method=method), [op_loc])
            continue
        # callbacks: one part per notification — each is read in its own clause
        cb_details: dict[str, list] = defaultdict(list)
        for d in by_owner_aspect.get((op.operation, "callbacks"), []):
            keys = _keys(d.element)
            cb_details[keys[1] if len(keys) > 1 else ""].append(d)
        for name, details in sorted(cb_details.items()):
            o_cb, g_cb = _get(o_op, "callbacks", name), _get(g_op, "callbacks", name)
            state = ("missing in the generated document" if g_cb is None else
                     "not in the official document" if o_cb is None else "differs")
            add(_gen_part(label, op.operation, f"callback {name}",
                          f"callback {name} {state}: {_counts(details)}", o_cb, g_cb,
                          path=path, method=method, terms=[name]),
                [f"{op_loc}.callbacks.{join((name,))}"])
        for key, aspect in _OP_ASPECTS.items():
            if aspect == "callbacks":
                continue
            details = by_owner_aspect.get((op.operation, aspect), [])
            facts = {
                "parameters": [op.params_missing and f"missing {op.params_missing}",
                               op.params_extra and f"extra {op.params_extra}",
                               op.params_at_path_level and
                               f"declared on the path item, not on this operation: "
                               f"{op.params_at_path_level}"],
                "request_body": [op.media_missing and f"media types missing {op.media_missing}",
                                 op.media_extra and f"media types extra {op.media_extra}"],
                "responses": [op.responses_missing and f"codes missing {op.responses_missing}",
                              op.responses_extra and f"codes extra {op.responses_extra}"],
            }[aspect]
            facts = [f for f in facts if f]
            if not (facts or details):
                continue
            if aspect == "parameters":
                off_side = {"path_level": _get(o_item, "parameters"),
                            "operation": _get(o_op, "parameters")}
                gen_side = {"path_level": _get(g_item, "parameters"),
                            "operation": _get(g_op, "parameters")}
            else:
                off_side, gen_side = _get(o_op, key), _get(g_op, key)
            summary = "; ".join(facts + ([_counts(details)] if details else []))
            add(_gen_part(label, op.operation, aspect, f"{key}: {summary}",
                          off_side, gen_side, path=path, method=method,
                          terms=[t for t in (_get(o_op, "operationId"),
                                             _get(o_op, "summary")) if t]),
                [f"{op_loc}.{key}"])
        other = by_owner_aspect.get((op.operation, "operation"), [])
        if other:
            add(_gen_part(label, op.operation, "operation",
                          f"other operation fields: {_counts(other)}",
                          {k: v for k, v in (o_op or {}).items() if k not in _OP_ASPECTS},
                          {k: v for k, v in (g_op or {}).items() if k not in _OP_ASPECTS},
                          path=path, method=method), [op_loc])

    o_schemas = _get(official, "components", "schemas") or {}
    g_schemas = _get(generated, "components", "schemas") or {}
    for s in report.schemas:
        owner = f"SCHEMA {s.name}"
        loc = f"components.schemas.{join((s.name,))}"
        leaves = s.leaves
        changed = leaves.absent or leaves.differing or leaves.extra \
            or s.shape_official != s.shape_generated
        if s.status == "present" and not changed:
            continue
        aspect = {"present": "definition", "misplaced": "placement",
                  "missing": "missing", "extra": "extra"}[s.status]
        gen_node = g_schemas.get(s.name)
        locs = [loc]
        if s.status == "misplaced":
            gen_node = _node_at(generated, s.found_at)
            locs.append(s.found_at)
        summary = "; ".join(filter(None, [
            f"schema {s.status}" + (f" (at {s.found_at})" if s.found_at else ""),
            s.shape_official != s.shape_generated and
            f"shape official {s.shape_official or '—'} vs generated {s.shape_generated or '—'}",
            s.note,
            (leaves.absent or leaves.differing or leaves.extra) and
            f"{leaves.absent} leaves absent, {leaves.differing} differing, {leaves.extra} extra",
        ]))
        add(_gen_part(label, owner, aspect, summary, o_schemas.get(s.name), gen_node,
                      schemas=[s.name]), locs)

    _attach_issues(parts, locations, [f"{i.location}: {i.message}"
                                      for i in report.validity_generated.issues])
    return parts


def _node_at(doc: dict, dotted: str) -> Any:
    return _get(doc, *[k.strip("'") for k in dotted.split(".")])


def _gen_part(label: str, owner: str, aspect: str, summary: str, official: Any,
              generated: Any, *, path: str = "", method: str = "",
              schemas: list[str] | None = None, terms: list[str] | None = None) -> Part:
    names, external = _ref_hints(official, generated)
    return Part(
        id=f"generator|{label}|{owner}|{aspect}", evaluation="generator", input=label,
        owner=owner, aspect=aspect, summary=summary, official=official, generated=generated,
        hints=SearchHints(path=path, method=method,
                          schemas=list(dict.fromkeys((schemas or []) + names)),
                          external_refs=external, terms=terms or []))


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
