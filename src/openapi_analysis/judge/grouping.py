"""The LLM step of the alignment (docs/ALIGNMENT_PLAN.md): group what the exact,
deterministic steps (openapi/alignment.py) left over.

One call per FAMILY of blocks with leftovers, in order — endpoints (paths, operations,
callbacks: an operation and a callback may correspond, so they share a call), then
parameters, then request bodies and responses, then schemas, components and the header.
Blocks of different families never correspond, so no correspondence is lost by the
split; each call sees the groups the previous ones formed. Every call gets:
  - the two documents, WHOLE, as YAML — the ground for every decision (when they are
    too large, beyond MAX_DOCUMENTS_CHARS, each block's content is given instead);
  - the index of every group formed;
  - the leftovers of its family, and under each the blocks of the other side most
    alike it, free or ALREADY GROUPED — so an extra is set beside what it most
    resembles, wherever that is.
It may group leftovers together, or join a leftover to a group (a copy, a split).
The calls share their beginning (instructions and documents), which the API caches.

The grouper only says what corresponds; the judge says whether it is right. Its
answer is checked before anything is grouped — only ids it was given, one kind on each
side of a group (an operation on one side and a callback on the other the only mixed
pair), one media type per side, each block once, groups with both sides — and a
refused proposal groups nothing (the blocks stay leftovers). Answers are cached under
data/judgements/grouping/, keyed on the messages, the model and GROUPING_VERSION.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from openapi_analysis.judge.grouping_prompts import GROUPING_SYSTEM, GROUPING_VERSION
from openapi_analysis.openapi.alignment import Aligner, similarity
from openapi_analysis.schemas.alignment import (
    Alignment,
    BlockKind,
    GroupingAnswer,
    GroupingCall,
)

AskGrouping = Callable[[list[tuple[str, str]]], GroupingAnswer]
# kinds where no OpenAPI object covers several (R9: each media type is its own
# representation): a group holds at most one block of each side
ONE_PER_SIDE: set[BlockKind] = {"media_type", "header", "component", "block"}
# the only kinds that may correspond across: an endpoint declared as an operation under
# paths on one side and as a callback on the other (R11, R12) — never grouped
# deterministically, since the same method and body do not prove the same role
COMPATIBLE: frozenset[BlockKind] = frozenset({"operation", "callback"})
# one call each, in this order
FAMILIES: tuple[tuple[str, frozenset[BlockKind]], ...] = (
    ("endpoints (paths, operations, callbacks)", frozenset({"path", "operation", "callback"})),
    ("parameters", frozenset({"parameter"})),
    ("request bodies and responses", frozenset({"media_type", "response"})),
    ("schemas, other components and the document header",
     frozenset({"schema", "component", "block", "header"})),
)
CANDIDATES = 5                       # per leftover, the most alike of the other side
MAX_DOCUMENTS_CHARS = 300_000        # beyond it, block contents instead of the documents


def _kinds_agree(a: Aligner, official: list[str], generated: list[str]) -> bool:
    """One kind on each side of a group; the two sides of the same kind, or an
    operation on one side and a callback on the other — never a callback joined to an
    operation's group on the operation's own side."""
    by_side: dict[str, set[BlockKind]] = {}
    for b in [*official, *generated]:
        by_side.setdefault(a.blocks[b].side, set()).add(a.blocks[b].kind)
    if any(len(kinds) > 1 for kinds in by_side.values()):
        return False
    kinds = set().union(*by_side.values())
    return len(kinds) == 1 or kinds == COMPATIBLE


def _yaml(node: object, indent: str = "") -> str:
    text = yaml.safe_dump(node, sort_keys=False, allow_unicode=True, width=100).rstrip()
    return "\n".join(indent + line for line in text.splitlines())


def candidates_anywhere(a: Aligner, bid: str, owned: dict[str, int]) -> list[tuple[str, float]]:
    """The blocks of the other side most alike a leftover, of its kind (or the one
    compatible kind), free or grouped — only blocks that take part (active, holding a
    value or a group)."""
    b = a.blocks[bid]
    kinds = COMPATIBLE if b.kind in COMPATIBLE else {b.kind}
    scored = [(o.id, similarity(a.nodes[bid], a.nodes[o.id])) for o in a.blocks.values()
              if o.side != b.side and o.kind in kinds and a.active(o.id)
              and (o.id in a.group_of or owned.get(o.id))]
    scored.sort(key=lambda x: -x[1])
    return [(c, s) for c, s in scored if s > 0][:CANDIDATES]


def grouping_messages(a: Aligner, family: str, leftovers: list[str], owned: dict[str, int]
                      ) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """The message of one call (one family), and the ids it gives (A1/B1 → block,
    G1 → group)."""
    ids: dict[str, str] = {}
    for side, tag in (("official", "A"), ("generated", "B")):
        for i, bid in enumerate([b for b in leftovers if a.blocks[b].side == side], 1):
            ids[f"{tag}{i}"] = bid
    tag_of = {bid: t for t, bid in ids.items()}
    ids.update({g.id: g.id for g in a.groups})

    texts = {side: _yaml(doc) for side, doc in a.docs.items()}
    whole = sum(map(len, texts.values())) <= MAX_DOCUMENTS_CHARS
    lines: list[str] = []
    if whole:
        for side, text in texts.items():
            lines += [f"{side.upper()} DOCUMENT (YAML):", "```yaml", text, "```", ""]
    else:
        lines += [("THE DOCUMENTS ARE TOO LARGE TO BE GIVEN WHOLE: the content of each "
                  "block is given with it instead."), ""]
        lines += [f"{side} servers: {json.dumps(doc.get('servers') or '(none)')}"
                  for side, doc in a.docs.items()]
    lines += ["INDEX — GROUPS ALREADY FORMED (fixed):"]
    for g in a.groups:
        members = [f"{a.blocks[b].side} {a.blocks[b].location} ({a.blocks[b].identity})"
                   for b in [*g.official, *g.generated]]
        lines.append(f"{g.id} {g.kind}: " + " | ".join(members))
    lines += ["", f"THIS REQUEST: the leftovers of the family {family}."]
    for side in ("official", "generated"):
        lines += ["", (f"LEFTOVERS — {side.upper()} (in the {side} document only, "
                       "so far):")]
        for bid in [b for b in leftovers if a.blocks[b].side == side]:
            b = a.blocks[bid]
            lines.append(f"[{tag_of[bid]}] {b.kind} at {b.location} — {b.identity}")
            if not whole:
                lines += ["    content:", _yaml(a.nodes[bid], "      ")]
            cands = candidates_anywhere(a, bid, owned)
            if cands:
                lines.append("    most alike on the other side (similarity orders only):")
            for c, score in cands:
                cb = a.blocks[c]
                where = (f"[{tag_of[c]}] a leftover" if c in tag_of else
                         f"in group {a.group_of[c].id}" if c in a.group_of else "free")
                lines.append(f"      - {where}: {cb.kind} at {cb.location} "
                             f"(similarity {score})")
                if not whole and c not in tag_of:
                    lines.append(_yaml(a.nodes[c], "          "))
    return [("system", GROUPING_SYSTEM), ("human", "\n".join(lines))], ids


def _cache_key(msgs: list[tuple[str, str]], model: str) -> str:
    payload = {"messages": msgs, "model": model, "version": GROUPING_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _ask_cached(msgs: list[tuple[str, str]], ask: AskGrouping, model: str,
                cache_dir: Path | None, label: str) -> tuple[GroupingAnswer, str]:
    key = _cache_key(msgs, model)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label)[:80]
    path = cache_dir / "grouping" / safe / f"{key}.json" if cache_dir else None
    if path is not None and path.is_file():
        return GroupingAnswer.model_validate_json(path.read_text(encoding="utf-8")), key
    answer = ask(msgs)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(answer.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return answer, key


def apply_answer(a: Aligner, answer: GroupingAnswer, ids: dict[str, str]) -> list[str]:
    """Group what the answer proposes, after the checks; return what was refused."""
    refused: list[str] = []
    used: set[str] = set()

    def block(tag: str, side: str) -> str | None:
        bid = ids.get(tag.strip().upper())
        if bid is None or bid not in a.blocks or a.blocks[bid].side != side:
            refused.append(f"{tag}: not a {side} leftover id given")
            return None
        if bid in used or bid in a.group_of:
            refused.append(f"{tag}: already grouped")
            return None
        return bid

    for pg in answer.groups:
        official = [b for t in pg.official if (b := block(t, "official"))]
        generated = [b for t in pg.generated if (b := block(t, "generated"))]
        if not official or not generated:
            refused.append(f"group {pg.official}+{pg.generated}: needs both sides")
            continue
        kind = a.blocks[official[0]].kind
        if not _kinds_agree(a, official, generated):
            refused.append(f"group {pg.official}+{pg.generated}: blocks of different kinds")
            continue
        if kind in ONE_PER_SIDE and (len(official) > 1 or len(generated) > 1):
            refused.append(f"group {pg.official}+{pg.generated}: one {kind} per side")
            continue
        used.update([*official, *generated])
        a.new_group(official, generated, "llm", primary=False, reason=pg.reason)
    for j in answer.joins:
        bid = ids.get(j.block.strip().upper())
        target = next((g for g in a.groups if g.id == ids.get(j.group.strip().upper())), None)
        if bid is None or bid not in a.blocks or target is None:
            refused.append(f"join {j.block} -> {j.group}: unknown id")
        elif bid in used or bid in a.group_of:
            refused.append(f"join {j.block}: already grouped")
        elif not _kinds_agree(a, [*target.official, *target.generated], [bid]):
            refused.append(f"join {j.block} -> {j.group}: blocks of different kinds")
        elif target.kind in ONE_PER_SIDE and (target.official if a.blocks[bid].side ==
                                              "official" else target.generated):
            refused.append(f"join {j.block} -> {j.group}: one {target.kind} per side")
        else:
            used.add(bid)
            a.add_to(target, bid, "llm", reason=j.reason)
    answered = used | {ids.get(u.block.strip().upper()) for u in answer.ungrouped}
    missing = [t for t, b in ids.items()
               if b in a.blocks and b not in answered and b not in a.group_of]
    if missing:
        refused.append(f"not answered: {missing}")
    return refused


def run_grouping(a: Aligner, *, ask: AskGrouping | None = None, model: str = "",
                 cache_dir: Path | None = None) -> Alignment:
    """The LLM step on an aligner that went through the deterministic steps: one call
    per family with leftovers, in FAMILIES order."""
    if ask is None:
        from openapi_analysis.config import judge_settings as s
        from openapi_analysis.config.paths import JUDGEMENTS_DIR
        ask, model = default_ask(), model or s.MODEL
        cache_dir = cache_dir or JUDGEMENTS_DIR
    label = f"{a.labels[1]}__vs__{a.labels[0]}"
    calls: list[GroupingCall] = []
    for family, kinds in FAMILIES:
        owned = a.owned()
        left = [b for b in a.leftovers(owned) if a.blocks[b].kind in kinds]
        if not left:
            continue
        msgs, ids = grouping_messages(a, family, left, owned)
        answer, key = _ask_cached(msgs, ask, model, cache_dir, label)
        refused = apply_answer(a, answer, ids)
        calls.append(GroupingCall(area=family, blocks=ids, answer=answer, overrides=refused,
                                  cache_key=key, model=model, version=GROUPING_VERSION))
    out = a.result()
    out.calls = calls
    return out


def default_ask() -> AskGrouping:
    """The real grouper: the judge's model (config/judge_settings), structured output."""
    from openapi_analysis.config.llm_config import get_llm

    structured = get_llm().with_structured_output(GroupingAnswer)

    def ask(msgs: list[tuple[str, str]]) -> GroupingAnswer:
        return structured.invoke(msgs)

    return ask
