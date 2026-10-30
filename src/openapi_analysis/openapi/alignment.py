"""Align the two documents: which block of the generated one CORRESPONDS to which block
of the official one (docs/ALIGNMENT_PLAN.md, the deterministic steps). No LLM.

Grouping never says a block is right — the judge does, on every group. A group only
says "compare these together", so the same content at another address is looked at
once, instead of as one missing plus one extra.

Blocks (one object of a fixed kind):
    global   header (info, servers, ...), path (path item), operation, schema (in
             components.schemas, or a copy anywhere else), component (another
             components section), block (anything else at the top)
    inner    parameter (of a path item or an operation), media_type (of a request
             body), response, callback — aligned only inside a group of their owner
Every value (leaf, as layer 1 counts them) of each document is owned by exactly one
ACTIVE block: the deepest one holding it. Inner blocks are active only when their
owner is the primary pair of a group; otherwise they stay inside it (a missing
operation is one block, with its parameters and responses).

Steps, each on what the previous left over — only what is EXACT is grouped here;
whatever needs interpretation is left to the LLM steps (judge/grouping.py): a server
prefix repeated in a path, default vs 4XX / 5XX, a renamed media type, the same
content under another key (two status codes with one body are two responses):
    1 address  the same location, same kind
    2 key      the same OpenAPI identity elsewhere: an operation by method + path with
               template names erased (R2), or by operationId (R3); a path likewise; a
               schema by name (R13); a parameter by (operation, in, name) at any level
               (R5); a callback by what it delivers (R12). A second block with the key
               of a block already grouped JOINS that group: a copy, a level split.
    3 candidates  for each official leftover, the generated leftovers of its area,
               ranked by similarity — ranking only, nothing is grouped
The document header (info, servers, tags, ...) is aligned by address only and never
used to align anything else.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from openapi_analysis.openapi.comparison import (
    METADATA_ROOTS,
    Parts,
    _all_refs,
    _item_label,
    flatten_parts,
    join,
)
from openapi_analysis.schemas.alignment import Alignment, Block, BlockKind, Group, Side, Step

COMPONENT_SECTIONS = ("schemas", "responses", "parameters", "examples", "requestBodies",
                      "headers", "securitySchemes", "links", "callbacks")
# keys that make a mapping a Schema Object
SCHEMA_KEYWORDS = frozenset({"type", "properties", "allOf", "oneOf", "anyOf", "enum", "items",
                             "$ref", "additionalProperties", "required"})
GLOBAL_KINDS: tuple[BlockKind, ...] = ("header", "path", "operation", "schema", "component",
                                       "block")
INNER_KINDS: tuple[BlockKind, ...] = ("media_type", "response", "callback")
# every operation an OpenAPI 3.0 path item may hold (Path Item Object) — the document
# is aligned as written, not only what the rules bank contract asks for
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
CANDIDATES_PER_BLOCK = 5


# ── helpers ──────────────────────────────────────────────────────────────────

def node_at_loc(doc: Any, loc: Iterable[str]) -> Any:
    """The node at a location given as layer-1 parts (list items by their label)."""
    node, prev = doc, ""
    for step in loc:
        if isinstance(node, dict):
            node = {str(k): v for k, v in node.items()}.get(step)
        elif isinstance(node, list):
            node = next((v for i, v in enumerate(node)
                         if _item_label((prev,), i, v) == step), None)
        else:
            return None
        if node is None:
            return None
        prev = step
    return node


def _schema_like(value: Any) -> bool:
    return isinstance(value, dict) and bool(SCHEMA_KEYWORDS & {str(k) for k in value})


def path_key(path: str) -> str:
    """A path with its template names erased (R2: /{a} and /{b} are the same path) —
    the path alone: servers are the document header, never used to align."""
    return re.sub(r"/+", "/", re.sub(r"\{[^}]*\}", "{}", str(path))).strip("/")


def parameter_identity(doc: dict, node: Any) -> tuple[str, str] | None:
    """(in, name) of a parameter (R4) — a local $ref resolved to the parameter it points
    to (R14), a header name lower-cased (header names are case insensitive)."""
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        target = node_at_loc(doc, ref[2:].split("/")) if ref.startswith("#/") else None
        if not isinstance(target, dict):
            return ("$ref", ref)
        node = target
    if not isinstance(node, dict) or "in" not in node or "name" not in node:
        return None
    where, name = str(node["in"]), str(node["name"])
    return (where, name.lower() if where == "header" else name)


def _leaf_pairs(node: Any) -> set[tuple[str, str]]:
    return {(join(p), json.dumps(v, sort_keys=True, default=str))
            for p, v in flatten_parts(node).items()}


def _jaccard(a: set, b: set) -> float | None:
    return len(a & b) / len(a | b) if a or b else None


def similarity(a: Any, b: Any) -> float:
    """How alike two blocks are, 0–1: shared leaves (relative path + value), shared
    relative paths, shared $refs (when either has one). Ranks candidates only."""
    pa, pb = _leaf_pairs(a), _leaf_pairs(b)
    scores = [_jaccard(pa, pb), _jaccard({p for p, _ in pa}, {p for p, _ in pb}),
              _jaccard(set(_all_refs(a)), set(_all_refs(b)))]
    scores = [s for s in scores if s is not None]
    return round(sum(scores) / len(scores), 3) if scores else 0.0


# ── the blocks of one document ───────────────────────────────────────────────

class _Blocks:
    """Every block of one document, with its node."""

    def __init__(self, doc: dict, side: Side, schema_names: set[str]) -> None:
        self.doc, self.side, self.names = doc, side, schema_names
        self.blocks: list[Block] = []
        self.nodes: dict[str, Any] = {}
        self._walk()

    def _add(self, kind: BlockKind, loc: Parts, identity: str, parent: str | None,
             node: Any) -> str:
        bid = f"{self.side}:{join(loc)}"
        if bid not in self.nodes:
            self.blocks.append(Block(id=bid, side=self.side, kind=kind, loc=list(loc),
                                     location=join(loc), identity=identity, parent=parent))
            self.nodes[bid] = node
        return bid

    def _copies(self, node: Any, loc: Parts, parent: str | None) -> None:
        """Schemas defined outside components.schemas: a schema-like mapping under a
        known schema name, or under a 'schemas' / 'components' key (never a property)."""
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            here = (*loc, str(key))
            if loc and loc[-1] != "properties" and _schema_like(value) and (
                    str(key) in self.names or loc[-1] in ("schemas", "components")):
                self._add("schema", here, str(key), None, value)
            else:
                self._copies(value, here, parent)

    def _params(self, owner: Any, loc: Parts, parent: str, where: str) -> None:
        params = owner.get("parameters") if isinstance(owner, dict) else None
        if not isinstance(params, list):
            return
        for i, p in enumerate(params):
            label = _item_label(("parameters",), i, p)
            ident = parameter_identity(self.doc, p)
            text = " ".join(ident) if ident else str(p)
            self._add("parameter", (*loc, "parameters", label), f"{text} ({where})", parent, p)

    def _operation(self, path: str, method: str, op: dict, path_id: str) -> None:
        loc = ("paths", path, method)
        name = f"{method.upper()} {path}"
        ident = name + (f" — operationId {op['operationId']}" if op.get("operationId") else "")
        refs = sorted(set(_all_refs(op.get("requestBody"))))
        ident += f" — body {', '.join(refs)}" if refs else ""
        oid = self._add("operation", loc, ident, path_id, op)
        self._params(op, loc, oid, f"on {name}")
        rb = op.get("requestBody")
        content = rb.get("content") if isinstance(rb, dict) else None
        for mt, node in (content.items() if isinstance(content, dict) else ()):
            self._add("media_type", (*loc, "requestBody", "content", str(mt)),
                      f"request body {mt} — {name}", oid, node)
        responses = op.get("responses")
        for code, node in (responses.items() if isinstance(responses, dict) else ()):
            self._add("response", (*loc, "responses", str(code)), f"response {code} — {name}",
                      oid, node)
        callbacks = op.get("callbacks")
        for cb, node in (callbacks.items() if isinstance(callbacks, dict) else ()):
            self._add("callback", (*loc, "callbacks", str(cb)),
                      f"callback {cb} — {_deliveries(node)} — registered by {name}", oid, node)

    def _walk(self) -> None:
        for root, value in self.doc.items():
            root = str(root)
            if root == "paths" and isinstance(value, dict):
                for path, item in value.items():
                    path = str(path)
                    pid = self._add("path", ("paths", path),
                                    f"PATH {path}",
                                    None, item)
                    if isinstance(item, dict):
                        self._params(item, ("paths", path), pid, f"on path {path}")
                        for m in METHODS:
                            if isinstance(item.get(m), dict):
                                self._operation(path, m, item[m], pid)
                    self._copies(item, ("paths", path), pid)
            elif root == "components" and isinstance(value, dict):
                for section, block in value.items():
                    section = str(section)
                    loc = ("components", section)
                    if section in COMPONENT_SECTIONS and isinstance(block, dict):
                        for name, node in block.items():
                            kind: BlockKind = "schema" if section == "schemas" else "component"
                            ident = str(name) if section == "schemas" else f"{section}.{name}"
                            self._add(kind, (*loc, str(name)), ident, None, node)
                    elif _schema_like(block):
                        self._add("schema", loc, section, None, block)
                    else:
                        self._add("block", loc, join(loc), None, block)
                        self._copies(block, loc, None)
            elif root in METADATA_ROOTS or root.startswith("x-"):
                self._add("header", (root,), root, None, value)
            else:
                self._add("block", (root,), root, None, value)
                self._copies(value, (root,), None)


def _deliveries(callback: Any) -> str:
    """What a callback delivers: 'POST {expression} body <$ref>' per request."""
    out = []
    for expr, item in (callback.items() if isinstance(callback, dict) else ()):
        for m in (METHODS if isinstance(item, dict) else ()):
            if isinstance(item.get(m), dict):
                refs = sorted(set(_all_refs(item[m].get("requestBody"))))
                out.append(f"{m.upper()} {expr}" + (f" body {', '.join(refs)}" if refs else ""))
    return "; ".join(out) or "no request"


def _delivery_key(callback: Any) -> frozenset[tuple[str, tuple[str, ...]]] | None:
    """R12: a callback corresponds by what it delivers — method + request body $refs —
    not by its name or how its expression is written."""
    out = set()
    for item in (callback.values() if isinstance(callback, dict) else ()):
        for m in (METHODS if isinstance(item, dict) else ()):
            if isinstance(item.get(m), dict):
                out.add((m, tuple(sorted(set(_all_refs(item[m].get("requestBody")))))))
    return frozenset(out) or None


# ── the aligner ──────────────────────────────────────────────────────────────

class Aligner:
    """Steps 1–4 (deterministic), and the operations the LLM steps use to add groups."""

    def __init__(self, official: dict, generated: dict, *, official_label: str = "",
                 generated_label: str = "") -> None:
        names = {str(n) for doc in (official, generated)
                 for n in ((doc.get("components") or {}).get("schemas") or {})}
        self.docs = {"official": official, "generated": generated}
        self.labels = (official_label, generated_label)
        sides = [_Blocks(official, "official", names), _Blocks(generated, "generated", names)]
        self.blocks: dict[str, Block] = {b.id: b for s in sides for b in s.blocks}
        self.nodes: dict[str, Any] = {k: v for s in sides for k, v in s.nodes.items()}
        self.groups: list[Group] = []
        self.group_of: dict[str, Group] = {}
        self.leaves = {side: flatten_parts(doc) for side, doc in self.docs.items()}

    # groups
    def new_group(self, official: list[str], generated: list[str], step: Step, *,
                  primary: bool = True, reason: str = "") -> Group:
        kind = self.blocks[(official or generated)[0]].kind
        g = Group(id=f"G{len(self.groups) + 1}", kind=kind)
        self.groups.append(g)
        for bid in [*official, *generated]:
            self.add_to(g, bid, step)
        if primary and official and generated:
            g.primary = [official[0], generated[0]]
        if reason:
            g.reasons.append(reason)
        return g

    def add_to(self, g: Group, bid: str, step: Step, reason: str = "") -> None:
        assert bid not in self.group_of, f"{bid} is already in {self.group_of[bid].id}"
        (g.official if self.blocks[bid].side == "official" else g.generated).append(bid)
        g.how[bid] = step
        self.group_of[bid] = g
        if reason:
            g.reasons.append(reason)

    # which blocks take part
    def active(self, bid: str) -> bool:
        """A global block always; an inner block when its owner is the primary pair of
        its group (otherwise it stays inside the owner, as one block)."""
        b = self.blocks[bid]
        if b.kind in GLOBAL_KINDS:
            return True
        parent = b.parent
        return parent is not None and self.active(parent) and parent in (
            self.group_of[parent].primary if parent in self.group_of else ())

    def _free(self, side: Side, kinds: Iterable[BlockKind], parent: str | None = None
              ) -> list[str]:
        kinds = set(kinds)
        return [b.id for b in self.blocks.values()
                if b.side == side and b.kind in kinds and b.id not in self.group_of
                and (parent is None or b.parent == parent) and self.active(b.id)]

    # steps 1–3 on a set of blocks
    def _match(self, official: list[str], generated: list[str], key: Callable[[str], Any],
               step: Step, *, join_grouped: Iterable[str] = ()) -> None:
        """Group the free blocks of both sides that share a key; then let a free block
        whose key is that of an already grouped block (`join_grouped`) join its group.
        A key two official blocks share decides nothing (which one? — the LLM's call)."""
        gen: dict[Any, list[str]] = defaultdict(list)
        for bid in generated:
            if bid not in self.group_of and (k := key(bid)) is not None:
                gen[k].append(bid)
        shared: dict[Any, int] = defaultdict(int)
        for bid in {*official, *(b for b in join_grouped if self.blocks[b].side == "official")}:
            if (k := key(bid)) is not None:
                shared[k] += 1
        for bid in official:
            if bid in self.group_of or (k := key(bid)) is None or not gen.get(k) \
                    or shared[k] > 1:
                continue
            free = [g for g in gen.pop(k) if g not in self.group_of]
            if free:
                self.new_group([bid], free, step)
        grouped: dict[Any, Group] = {}
        for bid in join_grouped:
            if bid in self.group_of and (k := key(bid)) is not None:
                grouped.setdefault(k, self.group_of[bid])
        for bid in [*official, *generated]:
            if bid not in self.group_of and (k := key(bid)) is not None and k in grouped \
                    and shared[k] <= 1 and grouped[k].kind == self.blocks[bid].kind:
                self.add_to(grouped[k], bid, step)

    def _steps(self, kinds: Iterable[BlockKind], keyf: Callable[[str], Any] | None,
               parent_pair: tuple[str, str] | None = None) -> None:
        for kind in kinds:
            o_parent, g_parent = parent_pair or (None, None)
            o = self._free("official", [kind], o_parent)
            g = self._free("generated", [kind], g_parent)
            everyone = [b.id for b in self.blocks.values() if b.kind == kind and (
                parent_pair is None or b.parent in parent_pair)]
            rel = (lambda bid: tuple(self.blocks[bid].loc[len(self.blocks[
                self.blocks[bid].parent].loc):])) if parent_pair else \
                (lambda bid: tuple(self.blocks[bid].loc))
            self._match(o, g, rel, "address")
            if keyf is not None:
                self._match(self._free("official", [kind], o_parent),
                            self._free("generated", [kind], g_parent), keyf, "key",
                            join_grouped=everyone)
            # no grouping by content: the same content under another key is not the
            # same object (two status codes with one body are two responses, two media
            # types with one schema two representations, R9) — the candidates show it
            # to the LLM with similarity 1.0

    def _global_key(self, bid: str) -> Any:
        b = self.blocks[bid]
        if b.kind == "operation":
            return ("operation", b.loc[2], path_key(b.loc[1]))
        if b.kind == "path":
            return ("path", path_key(b.loc[1]))
        if b.kind == "schema":
            return ("schema", b.loc[-1])
        if b.kind == "component":
            return ("component", b.loc[1], b.loc[2])
        return None

    def _operation_id(self, bid: str) -> Any:
        """R3: operationId is unique among the operations of an API."""
        op_id = self.nodes[bid].get("operationId") if isinstance(self.nodes[bid], dict) else None
        return ("operationId", op_id) if isinstance(op_id, str) and op_id else None

    def _inner_key(self, bid: str) -> Any:
        b = self.blocks[bid]
        return ("callback", _delivery_key(self.nodes[bid])) if b.kind == "callback" else None

    def align_inner(self, g: Group) -> None:
        """Align the inner blocks of a group's primary pair (an operation's media types,
        responses and callbacks), then the parameters of every primary pair."""
        if g.kind == "operation" and len(g.primary) == 2:
            self._steps(INNER_KINDS, self._inner_key, (g.primary[0], g.primary[1]))
        self.align_parameters()

    def align_parameters(self) -> None:
        """R5: a parameter is the same parameter at any level — keyed by (the group of
        each operation it applies to, in, name). Blocks of both sides sharing a key are
        one group (one path-level parameter and its copies on four operations)."""
        keys: dict[str, set[tuple]] = {}
        for b in self.blocks.values():
            if b.kind != "parameter" or b.id in self.group_of or not self.active(b.id):
                continue
            ident = parameter_identity(self.docs[b.side], self.nodes[b.id])
            if ident is None:
                continue
            owner = self.blocks[b.parent]
            ops = ([owner.id] if owner.kind == "operation" else
                   [o.id for o in self.blocks.values()
                    if o.kind == "operation" and o.parent == owner.id])
            k = {(self.group_of[o].id, *ident) for o in ops
                 if o in self.group_of and o in self.group_of[o].primary}
            if owner.kind == "path" and owner.id in self.group_of:
                k.add((self.group_of[owner.id].id, "path-level", *ident))
            if k:
                keys[b.id] = k
        parent = {bid: bid for bid in keys}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        by_key: dict[tuple, str] = {}
        for bid, ks in keys.items():
            for k in ks:
                if k in by_key:
                    parent[find(bid)] = find(by_key[k])
                else:
                    by_key[k] = bid
        components: dict[str, list[str]] = defaultdict(list)
        for bid in keys:                                   # document order
            components[find(bid)].append(bid)
        for members in components.values():
            o = [m for m in members if self.blocks[m].side == "official"]
            gen = [m for m in members if self.blocks[m].side == "generated"]
            if not o or not gen:
                continue
            # "address" for the members at the place of a member of the other side,
            # "key" for those found elsewhere (another level, another operation)
            locs = {side: {tuple(self.blocks[m].loc) for m in members
                           if self.blocks[m].side == side}
                    for side in ("official", "generated")}

            def step(m: str, locs: dict = locs) -> Step:
                other = "generated" if self.blocks[m].side == "official" else "official"
                return "address" if tuple(self.blocks[m].loc) in locs[other] else "key"

            g = self.new_group(o[:1], [], step(o[0]), primary=False)
            for m in [*o[1:], *gen]:
                self.add_to(g, m, step(m))

    def deterministic(self) -> None:
        """Steps 1–2: the global blocks, then inside every group formed. An endpoint
        declared as a callback on one side and as an operation on the other is NOT
        grouped here: the same method and body do not prove the same role (an API may
        well receive what a callback sends) — the LLM decides."""
        self._steps(GLOBAL_KINDS, self._global_key)
        operations = [b.id for b in self.blocks.values() if b.kind == "operation"]
        self._match(self._free("official", ["operation"]), self._free("generated", ["operation"]),
                    self._operation_id, "key", join_grouped=operations)
        for g in list(self.groups):
            if g.kind == "operation":
                self.align_inner(g)
        self.align_parameters()

    # step 4 and the result
    def area(self, bid: str) -> str:
        """Where a leftover looks for its counterpart: its owner's group for an inner
        block, the whole document for a global one."""
        b = self.blocks[bid]
        if b.kind in GLOBAL_KINDS:
            return f"document — {b.kind}"
        owner = self.blocks[b.parent] if b.parent else None
        if b.kind == "parameter" and owner is not None and owner.kind == "operation":
            owner = self.blocks[owner.parent]    # a parameter's area is its path (R5)
        if owner is not None and owner.id in self.group_of:
            g = self.group_of[owner.id]
            return f"{g.id} ({self._group_name(g)}) — {b.kind}"
        return f"document — {b.kind}"

    def _group_name(self, g: Group) -> str:
        return self.blocks[(g.official or g.generated)[0]].identity.split(" — ")[0]

    def owned(self) -> dict[str, int]:
        """block id → how many values it owns: each leaf goes to the deepest active
        block holding it — the invariant that no value is counted twice or lost."""
        active = {(b.side, tuple(b.loc)): b.id for b in self.blocks.values()
                  if self.active(b.id)}
        out: dict[str, int] = defaultdict(int)
        for side, leaves in self.leaves.items():
            for leaf in leaves:
                for n in range(len(leaf), 0, -1):
                    bid = active.get((side, leaf[:n]))
                    if bid is not None:
                        out[bid] += 1
                        break
                else:
                    out[f"{side}:(no block)"] += 1
        return dict(out)

    def leftovers(self, owned: dict[str, int] | None = None) -> list[str]:
        owned = self.owned() if owned is None else owned
        return [b.id for b in self.blocks.values()
                if self.active(b.id) and b.id not in self.group_of and owned.get(b.id, 0)]

    def candidates(self, leftovers: list[str]) -> dict[str, list[tuple[str, float]]]:
        """Step 4: per official leftover, the generated leftovers of its area and kind,
        by similarity (> 0), at most CANDIDATES_PER_BLOCK."""
        gen = [b for b in leftovers if self.blocks[b].side == "generated"]
        out = {}
        for bid in leftovers:
            if self.blocks[bid].side != "official":
                continue
            area = self.area(bid)
            scored = sorted(((g, similarity(self.nodes[bid], self.nodes[g])) for g in gen
                             if self.area(g) == area), key=lambda x: -x[1])
            out[bid] = [(g, s) for g, s in scored if s > 0][:CANDIDATES_PER_BLOCK]
        return out

    def result(self) -> Alignment:
        owned = self.owned()
        left = self.leftovers(owned)
        return Alignment(official_label=self.labels[0], generated_label=self.labels[1],
                         blocks=self.blocks, groups=self.groups, leftovers=left,
                         owned=owned, candidates=self.candidates(left))


def align(official: dict, generated: dict, **labels: str) -> Alignment:
    """Steps 1–4 only (no LLM)."""
    a = Aligner(official, generated, **labels)
    a.deterministic()
    return a.result()
