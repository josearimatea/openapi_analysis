"""Cut the divergences into PARTS for the judge.

Deterministic, no LLM, no retrieval: it only reads the evaluation reports and the
documents they were computed from. A part is small enough to aim a retrieval at it
(docs/JUDGE_PLAN.md §3) — what is equal to the official YAML never becomes a part.

Generator (both documents) — the parts come from the alignment of the two documents
(judge/group_parts.py); this module gives them the difference of two subtrees
(diff_documents, the same leaf identity as layer 1), node_at and the attachment of
layer-2 issues.

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
from typing import Any

from openapi_analysis.judge.spec_index import clause_of
from openapi_analysis.openapi.comparison import (
    SET_KEYWORDS,
    Parts,
    _item_label,
    flatten_parts,
    join,
)
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS, rule_key
from openapi_analysis.schemas.judge import Part, SearchHints
from openapi_analysis.schemas.rulesbank import RulesBankEvaluation

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


_MISSING = object()
Diff = tuple[str, Parts, Any, Any]      # (kind, path, official, generated)
# components sections whose entries are named, reusable objects (OAS 3.0)
_COMPONENT_SECTIONS = ("schemas", "responses", "parameters", "examples", "requestBodies",
                       "headers", "securitySchemes", "links", "callbacks")


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


def _attach_issues(parts: list[Part], locations: dict[str, list[str]],
                   issues: list[str], containers: dict[str, list[str]] | None = None) -> None:
    """Give each layer-2 issue to the most specific part that holds it.

    An issue belongs to a part when it sits inside the part's location, or sits on
    the part's DIRECT parent and names the part's key ("components: 'MoiChange' ...
    unexpected") — a deeper descendant with the same key name is another thing.
    `containers`: locations that hold a part's blocks without being a part (a path
    key holding a schema copy) — an issue naming one goes to that part too.
    """
    for issue in issues:
        where, _, message = issue.partition(": ")
        named: list[Part] = []                 # parts the issue names (direct children)
        best, best_len = None, -1               # else: the most specific part holding it
        for part in parts:
            own = locations[part.id]
            for loc in [*own, *(containers or {}).get(part.id, [])]:
                key = _keys(loc)[-1]
                if loc == f"{where}.{join((key,))}" and f"'{key}'" in message:
                    if part not in named:
                        named.append(part)
                elif loc in own and (where == loc or where.startswith((loc + ".", loc + "["))) \
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
