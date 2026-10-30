"""The judge's parts for a generated document, from the alignment, and the two views of
the result (docs/ALIGNMENT_PLAN.md, steps 7–9).

    group     blocks of both documents that correspond (openapi/alignment.py and the
              LLM grouper, judge/grouping.py): ONE part, with what differs between them
              — inner differences (- absent, + extra, ~ differing) and, when a block
              sits elsewhere, the move itself (> moved). A group with no difference is
              equal and is not judged.
    leftover  a block in one document only: ONE part (missing / extra).

Every field (a leaf, as layer 1 counts them) of each document belongs to exactly one
block, so to at most one part, and takes the verdict of the most specific difference
holding it — never counted twice, never as missing plus extra. The two views count
each document on its own base:

    official   how much of the official the generated reproduces: same, different
               but right, better, wrong, missing, undecided
    generated  how much of the generated is right: same, different but right, better,
               wrong, extra useful, extra wrong, undecided
The document header (info, servers, tags, ...) is counted apart, never scored.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any

from openapi_analysis.judge.parts import _attach_issues, _keys, _ref_hints, diff_documents
from openapi_analysis.openapi.alignment import METHODS, Aligner, similarity
from openapi_analysis.openapi.comparison import _item_label, flatten_parts, join
from openapi_analysis.schemas.alignment import Group
from openapi_analysis.schemas.judge import Difference, Part, SearchHints, Verdict

OFFICIAL_ROWS = ("same", "different but right", "better", "wrong", "missing", "undecided")
GENERATED_ROWS = ("same", "different but right", "better", "wrong", "extra useful",
                  "extra wrong", "undecided")
INNER_OF_OPERATION = ("media_type", "response", "callback")


def _leaves(key: str, node: Any) -> int:
    return len(flatten_parts({key or "x": node})) or 1


def _pairs(a: Aligner, g: Group) -> list[tuple[str, str]]:
    """(official, generated) pairs to compare inside a group: each block with its
    counterpart — the most alike one when both sides hold several."""
    o, gen = g.official, g.generated
    if len(o) == 1:
        return [(o[0], x) for x in gen]
    if len(gen) == 1:
        return [(x, gen[0]) for x in o]
    pairs = [(max(o, key=lambda x, y=y: similarity(a.nodes[x], a.nodes[y])), y) for y in gen]
    paired = {x for x, _ in pairs}
    return pairs + [(x, max(gen, key=lambda y, x=x: similarity(a.nodes[x], a.nodes[y])))
                    for x in o if x not in paired]


def _remove(node: Any, rel: list[str]) -> None:
    """Drop the subtree at a relative location (list items by their label)."""
    for i, step in enumerate(rel):
        last = i == len(rel) - 1
        if isinstance(node, dict):
            key = next((k for k in node if str(k) == step), None)
            if key is None:
                return
            if last:
                del node[key]
                return
            node = node[key]
        elif isinstance(node, list):
            prev = rel[i - 1] if i else ""
            idx = next((j for j, v in enumerate(node) if _item_label((prev,), j, v) == step),
                       None)
            if idx is None:
                return
            if last:
                del node[idx]
                return
            node = node[idx]
        else:
            return


def own(a: Aligner, bid: str) -> Any:
    """A block without the blocks inside it that take part on their own (an operation
    without its parameters, bodies, responses, callbacks; a path item without its
    operations): what this block alone is compared by — never twice."""
    b = a.blocks[bid]
    n = len(b.loc)
    inner = [o for o in a.blocks.values() if o.side == b.side and o.id != bid
             and len(o.loc) > n and o.loc[:n] == b.loc and a.active(o.id)]
    node = copy.deepcopy(a.nodes[bid])
    for o in sorted(inner, key=lambda o: -len(o.loc)):
        _remove(node, o.loc[n:])
    return node


def _pair_differences(a: Aligner, o: str, g: str) -> list[Difference]:
    ob, gb = a.blocks[o], a.blocks[g]
    o_node, g_node = own(a, o), own(a, g)
    out = []
    if ob.loc != gb.loc:
        out.append(Difference(kind="moved", location=gb.location, official=ob.location,
                              generated=gb.location, official_location=ob.location,
                              leaves=_leaves(gb.loc[-1], g_node)))
    for kind, rel, o_val, g_val in diff_documents(o_node, g_node):
        o_loc, g_loc = join((*ob.loc, *rel)), join((*gb.loc, *rel))
        key = rel[-1] if rel else gb.loc[-1]
        if kind == "absent":
            out.append(Difference(kind="absent", location=o_loc, official_location=o_loc,
                                  leaves=_leaves(key, o_val)))
        elif kind == "extra":
            out.append(Difference(kind="extra", location=g_loc, leaves=_leaves(key, g_val)))
        else:
            out.append(Difference(kind="differing", location=g_loc, official_location=o_loc,
                                  official=o_val, generated=g_val))
    return out


def _term(location: str) -> str:
    """The element a location names: a key, a code, a parameter's name."""
    last = _keys(location)[-1]
    m = re.search(r"name=([^\],]+)\]$", last)
    return m.group(1) if m else re.sub(r"\[[^\]]*\]$", "", last)


def diff_terms(differences: list[Difference]) -> list[str]:
    """The concrete things in play, for the retrieval: what each difference is about
    (property, code, parameter, media type) and the short values that differ."""
    terms: list[str] = []
    for d in differences:
        locs = [d.location, d.official_location] + ([str(d.official)] if d.kind == "moved" else [])
        terms += [_term(loc) for loc in locs if loc]
        if d.kind == "differing":
            terms += [str(v) for v in (d.official, d.generated)
                      if v is not None and not isinstance(v, (dict, list)) and len(str(v)) <= 60]
    return [t for t in dict.fromkeys(terms) if t]


def _context(a: Aligner, bids: list[str]) -> dict[str, Any] | None:
    """The blocks as the judge reads them: an operation's parameter, body, response or
    callback inside the WHOLE operation; anything else whole on its own."""
    ctx: dict[str, Any] = {}
    for bid in bids:
        b = a.blocks[bid]
        parent = a.blocks.get(b.parent) if b.parent else None
        if parent is not None and parent.kind == "operation" and (
                b.kind in INNER_OF_OPERATION or b.kind == "parameter"):
            ctx[parent.location] = a.nodes[parent.id]
        else:
            ctx[b.location] = a.nodes[bid]
    return ctx or None


def _hints(a: Aligner, bids: list[str]) -> SearchHints:
    first = a.blocks[bids[0]]
    path = first.loc[1] if first.loc[0] == "paths" and len(first.loc) > 1 else ""
    method = first.loc[2] if path and len(first.loc) > 2 and first.loc[2] in METHODS else ""
    names, external = _ref_hints(*[a.nodes[b] for b in bids])
    schemas = [a.blocks[b].loc[-1] for b in bids if a.blocks[b].kind == "schema"]
    return SearchHints(path=path, method=method, schemas=list(dict.fromkeys(schemas + names)),
                       external_refs=external,
                       terms=list(dict.fromkeys(a.blocks[b].identity.split(" — ")[0]
                                                for b in bids)))


def group_parts(a: Aligner, label: str, issues: list[str] = ()
                ) -> tuple[list[Part], dict[str, str]]:
    """(parts, block id → the part it is judged in). One part per group that differs,
    one per leftover."""
    parts: list[Part] = []
    part_of: dict[str, str] = {}
    for g in a.groups:
        diffs = [d for o, gen in _pairs(a, g) for d in _pair_differences(a, o, gen)]
        if not diffs:
            continue
        members = [*g.official, *g.generated]
        how = ", ".join(sorted(set(g.how.values())))
        summary = (f"{len(g.official)} official and {len(g.generated)} generated "
                   f"{g.kind} block(s) that correspond, grouped by {how}"
                   + (f" — grouper: {' / '.join(g.reasons)}" if g.reasons else ""))
        part = Part(
            id=f"generator|{label}|{g.kind}|" + " + ".join(sorted(members)),
            evaluation="generator", input=label,
            owner=a.blocks[(g.official or g.generated)[0]].identity,
            aspect=f"{g.kind} — grouped by {how}", summary=summary,
            focus=[a.blocks[b].location for b in members], differences=diffs,
            diff_terms=diff_terms(diffs),
            official=_context(a, g.official), generated=_context(a, g.generated),
            hints=_hints(a, members))
        parts.append(part)
        part_of.update(dict.fromkeys(members, part.id))
    for bid in a.leftovers():
        b = a.blocks[bid]
        official = b.side == "official"
        part = Part(
            id=f"generator|{label}|{b.kind}|{bid}", evaluation="generator", input=label,
            owner=b.identity,
            aspect=f"{b.kind} — {'missing in' if official else 'extra in'} the generated",
            summary=(f"a {b.kind} present in the {b.side} document only: no block of the "
                     f"{'generated' if official else 'official'} document corresponds"),
            focus=[b.location], diff_terms=[_term(b.location)],
            differences=[Difference(kind="absent" if official else "extra",
                                    location=b.location,
                                    official_location=b.location if official else "",
                                    leaves=_leaves(b.loc[-1], own(a, bid)))],
            official=_context(a, [bid]) if official else None,
            generated=None if official else _context(a, [bid]),
            hints=_hints(a, [bid]))
        parts.append(part)
        part_of[bid] = part.id
    members: dict[str, list[str]] = {}
    for bid, pid in part_of.items():
        members.setdefault(pid, []).append(bid)
    containers = {pid: list(dict.fromkeys(join(tuple(a.blocks[b].loc[:n])) for b in bids
                                          for n in range(2, len(a.blocks[b].loc))))
                  for pid, bids in members.items()}
    _attach_issues(parts, {p.id: p.focus for p in parts}, list(issues), containers)
    return parts, part_of


# ── the two views ────────────────────────────────────────────────────────────

def _under(leaf: str, loc: str) -> bool:
    return leaf == loc or leaf.startswith((loc + ".", loc + "["))


def _covering(d: Difference, side: str) -> str | None:
    """The location a difference covers on one side (None: it covers nothing there)."""
    if side == "official":
        if d.kind == "extra":
            return None
        if d.kind == "moved":
            return str(d.official)
        return d.official_location or d.location
    return None if d.kind == "absent" else d.location


def _outcome(side: str, kind: str | None, verdict: str | None) -> str:
    if kind is None:
        return "same"
    if verdict in (None, "uncertain"):
        return "undecided"
    if side == "official" and kind == "absent":
        return {"equivalent": "different but right", "improvement": "better"}.get(
            verdict, "missing")
    if side == "generated" and kind == "extra":
        return "extra wrong" if verdict == "error" else "extra useful"
    return {"equivalent": "different but right", "improvement": "better",
            "error": "wrong"}[verdict]


def views(a: Aligner, parts: list[Part], part_of: dict[str, str],
          verdicts: list[Verdict]) -> dict[str, dict[str, int]]:
    """{"official": rows, "generated": rows, "header": counts}: every field of each
    document by outcome — the verdict of the most specific difference holding it."""
    by_id = {p.id: p for p in parts}
    judged = {v.part_id: v for v in verdicts}
    out = {"official": Counter(), "generated": Counter(), "header": Counter()}
    for (side, leaf), bid in a.leaf_owners().items():
        if bid is None or a.blocks[bid].kind == "header":
            out["header"][side] += 1
            continue
        part = by_id.get(part_of.get(bid, ""))
        kind, verdict = None, None
        if part is not None:
            where = join(leaf)
            v = judged.get(part.id)
            best = -1
            for i, d in enumerate(part.differences):
                loc = _covering(d, side)
                if loc is not None and _under(where, loc) and len(loc) > best:
                    best = len(loc)
                    kind = d.kind
                    verdict = (v.difference_verdicts[i] if v and v.difference_verdicts
                               else v.answer.verdict if v else None)
        out[side][_outcome(side, kind, verdict)] += 1
    rows = {"official": OFFICIAL_ROWS, "generated": GENERATED_ROWS}
    return {side: ({r: out[side].get(r, 0) for r in rows[side]} if side in rows
                   else dict(out[side])) for side in out}


def grouping_counts(a: Aligner) -> dict[str, int]:
    """Block memberships by how they were grouped: address, key (exact OpenAPI
    identity elsewhere), llm (the grouper) — and the leftovers."""
    counts = Counter(step for g in a.groups for step in g.how.values())
    counts["leftover"] = len(a.leftovers())
    return dict(counts)

