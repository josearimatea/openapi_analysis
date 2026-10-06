"""Retrieve what the 3GPP spec and the OpenAPI reference say about ONE part.

Several focused queries per part — never one query mixing everything (measured: a
query carrying the part's name together with every schema it references and generic
aspect words ranked the part's own definition 6th, behind look-alike types; the name
alone ranked it 1st). Each query keeps its best PER_QUERY chunks not already taken:

  spec (the main spec's fixed collection — normative text only, no annex), 3 queries:
    1. subject     the part's subject alone: "NotifyEvent", "HTTP PATCH"
    2. definition  how a spec states it: "Definition of type NotifyEvent",
                   "Notification notifyEvent"; for a bank rule, its own rule_text (a
                   sentence of the spec)
    3. difference  the subject with what concretely differs: response codes,
                   parameter names, media types, property names
    Spec hits are kept only inside the evaluated service's scope (two-level clause
    blocks read from the bank, e.g. ("11.1", "12.1")).

  OpenAPI reference (the OpenAPI 3.0.1 collection), 2 queries:
    1. object      the OpenAPI Object(s) the aspect is about: "Responses Object"
    2. concept     the concept in play, with the concrete values: "default response,
                   HTTP status code ranges 4XX 5XX, 200 204"

Building the queries is pure and tested without Qdrant; the search goes through a
`Search` callable, injectable for tests. Every chunk is kept as Evidence with the
query that brought it, so a verdict can be audited.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openapi_analysis.judge.spec_index import corpus_text, in_scope, split_by_heading
from openapi_analysis.schemas.judge import Evidence, Part

# (text, metadata) of each hit, best first
Search = Callable[[str, str, int, dict[str, str] | None], list[tuple[str, dict[str, Any]]]]

_RULE_TYPE_TOPIC = {
    "path_operation": "operation", "path_parameter": "parameters",
    "query_parameter": "parameters", "request_body": "request_body",
    "response": "responses", "callback": "callback", "schema_property": "definition",
}
# OpenAPI reference: (object query, concept query) per topic
_OPENAPI = {
    "parameters": ("Parameter Object Path Item Object parameters",
                   ("parameters applicable for all the operations under a path, overridden "
                   "at the operation level, query parameter")),
    "request_body": ("Request Body Object Media Type Object", "request body content media type"),
    "responses": ("Responses Object Response Object",
                  "default response, HTTP status code ranges 4XX 5XX, response code"),
    "callback": ("Callback Object", ("callback runtime expression URL of the notification "
                                    "request body")),
    "operation": ("Operation Object", "operation fields operationId summary"),
    "unexpected_keys": ("Path Item Object", "fixed fields of a path item, allowed operations"),
    "path_item": ("Path Item Object", "summary description servers of a path item"),
    "metadata": ("Info Object Server Object Tag Object",
                 ("document metadata: info version, servers url and variables, tags, "
                  "externalDocs, security, specification extensions x-")),
    "block": ("Components Object", "fixed fields of the components object, reusable objects"),
    "path": ("Paths Object", "relative path, path templating"),
    "definition": ("Schema Object", "allOf composition and inheritance, properties, required"),
    "placement": ("Components Object", "reusable schemas held in components schemas, $ref"),
    "missing": ("Components Object Schema Object", "reusable schemas in components schemas"),
    "extra": ("Reference Object", "$ref to a schema in another document"),
}
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


# ── what a part is about ─────────────────────────────────────────────────────

def _bank_rule(part: Part) -> dict:
    return (part.generated[0] if isinstance(part.generated, list) else part.generated) or {}


def topic(part: Part) -> str:
    """The aspect key: 'callback notifyEvent' → 'callback'; a bank rule → by its type."""
    if part.evaluation == "rulesbank":
        rule = part.official or _bank_rule(part)
        return _RULE_TYPE_TOPIC.get(rule.get("rule_type", ""), "operation")
    return part.aspect.split(" ", 1)[0]


def subject(part: Part) -> str:
    """The thing the part is about, as a spec names it."""
    if part.aspect.startswith("callback "):
        return part.aspect.split(" ", 1)[1]
    if part.owner.startswith(("SCHEMA ", "DOCUMENT ", "COMPONENTS ")):
        return part.owner.split(" ", 1)[1]
    if part.owner.startswith("COMPONENT "):                   # "COMPONENT parameters.N"
        return part.owner.split(" ", 1)[1].split(".", 1)[-1]
    if part.evaluation == "rulesbank":
        name = next((t for t in part.hints.terms if _IDENTIFIER.match(t)), "")
        if name:
            return name
        if part.hints.schemas and topic(part) == "definition":
            return part.hints.schemas[0]
    if part.hints.method:
        return f"HTTP {part.hints.method.upper()}"
    return " ".join(w for w in re.split(r"[{}=/]+", part.hints.path) if w)


def differing_terms(part: Part) -> list[str]:
    """The concrete values in play — what differs, not the whole context.

    A generator part names them itself (parts.py: the codes, parameters, media types,
    properties its differences are about, and the differing values); a bank rule
    gives its field and value."""
    if part.evaluation == "generator":
        return part.diff_terms[:12]
    terms = []
    for rule in [part.official, *(part.generated if isinstance(part.generated, list)
                                   else [part.generated])]:
        m = (rule or {}).get("openapi_mapping") or {}
        terms += [str(m.get("openapi_field", "")), str(m.get("openapi_value", ""))[:80]]
    return [x for x in dict.fromkeys(terms) if x]


# ── the queries ──────────────────────────────────────────────────────────────

_ASPECT_WORDS = {
    "responses": "response status codes", "parameters": "URI query parameters",
    "request_body": "request body media type", "callback": "notification",
    "definition": "attributes", "placement": "attributes", "missing": "attributes",
    "extra": "attributes", "operation": "operation", "unexpected_keys": "resource",
    "path": "resource URI", "path_item": "resource", "metadata": "", "block": "attributes",
}


def spec_queries(part: Part) -> list[str]:
    """3 queries on the spec: subject, definition, difference (see the module docstring)."""
    t, name = topic(part), subject(part)
    if part.evaluation == "rulesbank" and _bank_rule(part).get("rule_text"):
        definition = _bank_rule(part)["rule_text"]
    elif t == "callback":
        definition = f"Notification {name}"
    elif name.startswith("HTTP "):
        definition = f"{name} method {' '.join(re.split(r'[{}=/]+', part.hints.path)).strip()}"
    else:
        definition = f"Definition of type {name}"
    difference = " ".join([name, _ASPECT_WORDS.get(t, ""), *differing_terms(part)])
    return [q[:400] for q in dict.fromkeys([name, definition, difference]) if q.strip()]


def openapi_queries(part: Part) -> list[str]:
    """2 queries on the OpenAPI reference: the Object, and the concept with its values."""
    obj, concept = _OPENAPI.get(topic(part), _OPENAPI["operation"])
    values = " ".join(differing_terms(part)[:8])
    return [obj, f"{concept} {values}".strip()[:400]]


# ── the search ───────────────────────────────────────────────────────────────

def default_search() -> Search:
    """The real search: qdrant_3gpp_rag over the judge's Qdrant (needs the [judge] extra)."""
    from qdrant_3gpp_rag import QdrantFactory, retrieve

    from openapi_analysis.config import judge_settings as s

    factory = QdrantFactory.get_instance(host=s.QDRANT_HOST, port=s.QDRANT_PORT,
                                         model_name=s.EMBEDDING_MODEL,
                                         device=s.EMBEDDING_DEVICE)

    def search(query: str, collection: str, k: int,
               filters: dict[str, str] | None) -> list[tuple[str, dict[str, Any]]]:
        result = retrieve(query, factory=factory, collection_name=collection, k=k,
                          filters=filters)
        return [(d.page_content, dict(d.metadata or {})) for d in result.docs]

    return search


def _is_annex(clause: str) -> bool:
    """A clause of an annex ('A', 'A.1.1'). The index holds none; checked anyway."""
    return bool(re.match(r"^[A-Z](\.|$)", clause or ""))


_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class CorpusLayout:
    """What the shared corpus does not say in its metadata, read from its chunks:
    where the annexes begin, and the clause each chunk belongs to."""
    annex: tuple[int, int] | None = None
    clauses: dict[int, tuple[str, str]] = field(default_factory=dict)


def retrieve_evidence(part: Part, spec_collection: str, *, search: Search,
                      scope: tuple[str, ...] = (), per_query: int = 5, pool: int = 50,
                      openapi_collection: str = "openapi_reference",
                      layout: CorpusLayout | None = None) -> list[Evidence]:
    """The evidence for one part: each spec query's best chunks, then each reference
    query's — PER_QUERY new chunks per query, none repeated.

    A spec chunk is kept only as normative text (spec_index.corpus_text: no annex, no
    contents listing, no piece of an OpenAPI document). The shared corpus cuts by size,
    so one chunk may end a section and begin the next: it is split at its headings
    and each piece is evidence of its own clause — the piece before the first heading
    belongs to the section the chunk begins in (the layout). Only pieces inside the
    scope are kept; with a scope, a piece whose clause cannot be told is dropped."""
    layout = layout or CorpusLayout()
    evidence: list[Evidence] = []
    seen: set[str] = set()

    def take(source: str, collection: str, query: str,
             hits: list[tuple[str, dict[str, Any]]]) -> None:
        taken = 0
        for text, meta in hits:
            if taken >= per_query:
                return
            if source == "spec" and not meta.get("clause"):
                idx = meta.get("chunk_index")
                text = corpus_text(text, idx, layout.annex)
                begins_in = layout.clauses.get(idx) or ("", "")
                pieces = split_by_heading(text, begins_in) if text else []
            else:
                pieces = [(str(meta.get("clause", "")), str(meta.get("title", "")), text)]
            kept = 0
            for clause, title, piece in pieces:
                if source == "spec" and (_is_annex(clause) or not in_scope(clause, scope)
                                         or (scope and not clause)):
                    continue
                if piece in seen:
                    continue
                seen.add(piece)
                kept += 1
                title = title or next(iter(_HEADING.findall(piece)), "")
                evidence.append(Evidence(source=source, collection=collection, query=query,
                                         clause=clause, title=title, text=piece))
            taken += bool(kept)

    for q in spec_queries(part):
        take("spec", spec_collection, q, search(q, spec_collection, pool, None))
    for q in openapi_queries(part):
        take("openapi", openapi_collection, q, search(q, openapi_collection, pool, None))
    return evidence
