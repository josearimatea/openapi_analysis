"""Cut the divergences into PARTS for the judge.

Deterministic, no LLM, no retrieval: it only reads the evaluation reports and the
documents they were computed from. A part is small enough to aim a retrieval at it
(docs/JUDGE_PLAN.md §3) — what is equal to the official YAML never becomes a part.

Generator (both documents) — the parts come from the alignment of the two documents
(judge/group_parts.py); this module gives them the difference of two subtrees
(diff_documents, the same leaf identity as layer 1), node_at and the attachment of
layer-2 issues.

Rules bank (RulesBankEvaluation + the bank) — one part per rule:
    different  a bank rule on an official address, with another value — or with a value
               the official does not have (not_comparable in layer 1): not equal, judged
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

from openapi_analysis.judge.rules import (
    ERROR_RESPONSES,
    BankFacts,
    error_field,
    error_plan,
    is_error_response,
    ref_fact,
    worst,
)
from openapi_analysis.judge.spec_index import clause_of
from openapi_analysis.openapi.comparison import (
    SET_KEYWORDS,
    Parts,
    _item_label,
    flatten_parts,
    join,
)
from openapi_analysis.rulesbank.rule_types import HTTP_METHODS, rule_key
from openapi_analysis.schemas.judge import Difference, Part, SearchHints
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


# OpenAPI maps whose keys are names (a property may well be called "title"); what is under
# a data key is data, whatever its keys are called
_NAMED_MAPS = frozenset({"paths", "schemas", "properties", "patternProperties", "responses",
                         "parameters", "examples", "requestBodies", "headers", "securitySchemes",
                         "links", "callbacks", "variables", "content", "encoding", "mapping",
                         "scopes"})
_DATA_KEYS = frozenset({"example", "default", "enum", "value", "const"})
PROSE_KEYS = frozenset({"description", "summary", "title"})


def is_prose(location: str) -> bool:
    """Whether a location ends in text for a reader: the OpenAPI keyword description, summary
    or title, never a property or another named entry that happens to be called so."""
    keys = _keys(location)
    name = False
    for i, key in enumerate(keys):
        last = i == len(keys) - 1
        if name:                         # this key is a name in a map, not a keyword
            name = False
            if last:
                return False
            continue
        if last:
            return key in PROSE_KEYS
        if key in _DATA_KEYS or key.startswith("x-"):
            return False
        name = key in _NAMED_MAPS
    return False


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
        if at and ("$ref" in official) != ("$ref" in generated):
            return [("differing", at, official, generated)]    # one field written two ways
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


_NOT_COMPARED = ("the official holds no value at this address, so it was not compared: "
                 "the bank's value is judged")


# (part, holds an official rule, bank rule indexes, aspect, key in an "error responses"
# part: "official" or a bank rule index — "" elsewhere)
Item = tuple["Part | None", bool, list[int], str, str]


def _object(rule: dict) -> str:
    return (rule.get("openapi_mapping") or {}).get("openapi_object", "")


def _error_groups(report: RulesBankEvaluation, rules: list[dict]) -> dict[str, tuple]:
    """The operations whose error responses (default, 1XX-5XX) are judged together, one
    "error responses" part each (docs/FIX_PLAN.md, step 4): openapi_object -> (the official
    default or None, {bank index: rule}, the bank indexes layer 1 matched with it).

    Only by structure: the same openapi_object (the responses of one operation or
    callback) and a key of the Responses Object that covers a set of codes. Left out: an
    operation where the bank declares only a default (judged as any rule), and one where
    the official itself declares a range (the criterion speaks of an official default)."""
    official: dict[str, list[dict]] = {}
    bank: dict[str, dict[int, dict]] = {}
    matched: dict[str, set[int]] = {}
    for m in report.matches:
        if is_error_response(m.expected):
            obj = _object(m.expected)
            official.setdefault(obj, []).append(m.expected)
            for b in m.bank:
                bank.setdefault(obj, {})[b.index] = rules[b.index]
                matched.setdefault(obj, set()).add(b.index)
    for r in report.missing:
        if is_error_response(r):
            official.setdefault(_object(r), []).append(r)
    for x in report.extra:
        rule = rules[x.rule.index]
        if is_error_response(rule):
            bank.setdefault(_object(rule), {})[x.rule.index] = rule
    groups = {}
    for obj, held in bank.items():
        fields = sorted(error_field(r) for r in held.values())
        off = official.get(obj, [])
        if fields == ["default"] or any(error_field(r) != "default" for r in off) \
                or len(off) > 1:
            continue
        groups[obj] = (off[0] if off else None, held, matched.get(obj, set()))
    return groups


def _rulesbank_items(report: RulesBankEvaluation, bank: dict, label: str) -> list[Item]:
    """Every official rule and every bank rule, once: (part, official, bank rule indexes,
    aspect). part is None when the rule is equal to the official — nothing to judge;
    official says whether the item holds an official rule (False: an extra). A duplicate
    whose first rule has the official value is aspect "duplicate=" (that address is the
    same as the official; only the further rules are judged).

    Layer 1 only SORTS here: equal to the official, or not. Everything that is not equal
    — a different value, an official address with no value to compare (not_comparable),
    a duplicate, a missing rule, an extra — is a part for the judge."""
    rules = [r for r in (bank.get("rules") or []) if isinstance(r, dict)]
    facts = BankFacts(bank)

    def _part(owner: str, aspect: str, summary: str, official: dict | None,
              bank_rules: list[dict], suffix: str = "") -> Part:
        """A rule part, with what the bank's local $refs point to said in its summary: a
        fact of the bank the judge cannot see in the rule (judge/rules.py)."""
        fact = "; ".join(dict.fromkeys(f for f in (ref_fact(r, facts) for r in bank_rules)
                                       if f))
        return _rule_part(label, owner, aspect, summary + (f" — {fact}" if fact else ""),
                          official, bank_rules, suffix)

    groups = _error_groups(report, rules)

    def grouped(rule: dict) -> bool:
        return is_error_response(rule) and _object(rule) in groups

    items: list[Item] = []
    for m in report.matches:
        if grouped(m.expected):
            continue
        idx = [b.index for b in m.bank]
        bank_rules = [rules[i] for i in idx]
        owner = _address(m.expected)
        if m.shared():
            part = _part(owner, "duplicate",
                         f"{len(m.bank)} bank rules on one official address "
                         f"(rules {idx}); first value: "
                         f"{m.value_status}" + (f" — {m.note}" if m.note else ""),
                         m.expected, bank_rules)
            items.append((part, True, idx,
                          "duplicate=" if m.value_status == "equal" else "duplicate", ""))
        elif m.value_status == "different":
            items.append((_part(owner, "different", f"value differs — {m.note}",
                                m.expected, bank_rules), True, idx, "different", ""))
        elif m.value_status == "not_comparable":
            items.append((_part(owner, "different", _NOT_COMPARED, m.expected, bank_rules),
                          True, idx, "different", ""))
        else:
            items.append((None, True, idx, "equal", ""))
    for r in report.missing:
        if grouped(r):
            continue
        why = report.missing_note(r)
        items.append((_part(_address(r), "missing",
                            "official rule with no bank rule on its address"
                            + (f" — {why}" if why else ""), r, []), True, [], "missing", ""))
    for x in report.extra:
        rule = rules[x.rule.index]
        if grouped(rule):
            continue
        items.append((_part(_address(rule), "extra",
                            f"bank rule on no official address ({x.reason})"
                            + (f" — {x.note}" if x.note else ""), None, [rule],
                            suffix=f"#{x.rule.index}"),
                      False, [x.rule.index], "extra", ""))
    for obj, (official, held, matched) in groups.items():
        items += _error_items(label, obj, official, held, matched, facts, _part)
    return items


def _error_items(label: str, obj: str, official: dict | None, held: dict[int, dict],
                 matched: set[int], facts: BankFacts, make) -> list[Item]:
    """The "error responses" part of one operation and its items: the official default (if
    any) and each bank rule, each with its own key — every rule still counted once.

    The part says the CASE, what the form decides by rule (judge/rules.error_plan) and the
    question; its differences are only the rules the judge rules on."""
    plan = error_plan(official, held, facts)
    side = (official or {}).get("openapi_mapping", {}).get("openapi_value") if official else None
    decided = " ".join(f"{'official default' if k == 'official' else 'rule #' + k}: "
                       f"{v} ({plan.reasons[k]})." for k, v in plan.fixed.items())
    summary = (f"CASE: {plan.case} — the bank's error responses of this operation, judged "
               "together." + (f" Decided by their form: {decided}" if decided else "")
               + (f" QUESTION: {plan.question}" if plan.question else ""))
    owner = f"response {obj} · {ERROR_RESPONSES}"
    ordered = sorted(held.items())
    part = make(owner, ERROR_RESPONSES, summary, official, [r for _, r in ordered])
    differences = []
    for k in plan.asked:
        rule = held[int(k)]
        both = official is not None and int(k) in (
            [i for i, r in held.items() if error_field(r) == "default"] or matched)
        differences.append(Difference(
            kind="differing" if both else "extra",
            location=f"{error_field(rule)} (rule #{k})",
            official=side if both else None,
            generated=(rule.get("openapi_mapping") or {}).get("openapi_value")))
    default = [i for i, r in ordered if error_field(r) == "default"]
    counterpart = [] if official is None else default or sorted(matched)
    part = part.model_copy(update={
        "id": f"rulesbank|{label}|{owner}",
        "generated": [{**_bank_side(r), "rule_index": i,
                       "stands_for_official_default": i in counterpart} for i, r in ordered],
        "differences": differences})
    items: list[Item] = []
    if official is not None:
        items.append((part, True, counterpart, "group", "official"))
    for i, _ in ordered:
        items.append((part, False, [i], "group", str(i)))
    return items


def rulesbank_parts(report: RulesBankEvaluation, bank: dict, input_label: str = "") -> list[Part]:
    """The parts of a rules bank to judge: every rule not equal to the official."""
    label = input_label or report.bank.label
    return list({p.id: p for p, *_ in _rulesbank_items(report, bank, label)
                 if p is not None}.values())


def rule_outcome(side: str, aspect: str, verdict: str | None) -> str:
    """The row a rule takes in a view — the rows and the reading of the generated
    document's report (judge/group_parts._outcome), a rule in the place of a field."""
    if aspect == "equal":
        return "same"
    if verdict in (None, "uncertain"):
        return "undecided"
    if side == "official" and aspect == "missing":
        return {"equivalent": "different but right", "improvement": "better"}.get(
            verdict, "missing")
    if side == "generated" and aspect in ("extra", "duplicate"):
        return {"error": "extra wrong", "improvement": "better"}.get(verdict, "extra useful")
    return {"equivalent": "different but right", "improvement": "better",
            "error": "wrong"}.get(verdict, "undecided")


def rulesbank_views(report: RulesBankEvaluation, bank: dict, verdicts: list,
                    input_label: str = "") -> dict[str, dict[str, int]]:
    """{"official": rows, "generated": rows}: every official rule and every bank rule by
    outcome, as in the generated document's report. Each rule takes the verdict of its part;
    a rule equal to the official is "same" without the judge.

    official side — the official rules: the bank's rule on the address carries the verdict
    (a missing one, judged error, stays "missing").
    generated side — the bank rules: a rule on an official address takes the same row as
    that address (both rules of a 4XX + 5XX pair too); the second and further rules on one
    address (a duplicate) and the rules on no official address (extra) take the row of an
    extra: better, extra useful or extra wrong."""
    label = input_label or report.bank.label
    by_id = {v.part_id: v for v in verdicts}
    official: dict[str, int] = {}
    generated: dict[str, int] = {}

    def add(view: dict[str, int], row: str) -> None:
        view[row] = view.get(row, 0) + 1

    items = _rulesbank_items(report, bank, label)
    groups = {p.id: p for p, *_ in items if p is not None and p.aspect == ERROR_RESPONSES}
    for part, has_official, idx, aspect, key in items:
        v = by_id.get(part.id) if part else None
        verdict = v.answer.verdict if v else None
        if aspect == "group":
            per = dict(getattr(v, "rule_verdicts", None) or {}) if v else {}
            mine = [per.get(str(i), verdict) for i in idx]
            if key == "official":
                got = per.get("official") or worst(mine) or (
                    "same" if mine and all(m == "same" for m in mine) else verdict)
                add(official, "same" if got == "same" else
                    rule_outcome("official", "different" if idx else "missing", got))
            else:
                got = per.get(key, verdict)
                counterpart = _counterpart(groups[part.id], int(key))
                add(generated, "same" if got == "same" else
                    rule_outcome("generated", "different" if counterpart else "extra", got))
            continue
        if has_official:
            duplicate = aspect.startswith("duplicate")
            row = ("same" if aspect == "duplicate=" else
                   rule_outcome("official", "different" if duplicate else aspect, verdict))
            add(official, row)
            for n, _ in enumerate(idx):
                add(generated, rule_outcome("generated", "duplicate", verdict)
                    if duplicate and n else row)
        else:
            add(generated, rule_outcome("generated", "extra", verdict))
    return {"official": official, "generated": generated}


def _counterpart(part: Part, index: int) -> bool:
    """Whether a bank rule of an "error responses" part stands for the official default
    (its default, or — with no default in the bank — the ranges layer 1 matched with it):
    its row is then on an official address, else an extra's."""
    return any(r.get("rule_index") == index and r.get("stands_for_official_default")
               for r in part.generated or [])
