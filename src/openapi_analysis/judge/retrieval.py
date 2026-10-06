"""Retrieve what the spec and the OpenAPI reference say about ONE part.

The search is aimed by the part itself (docs/JUDGE_PLAN.md §4.4), never generic.
Spec chunks come from the main spec's fixed collection (normative text only — no
annex), in three passes, each adding only what the earlier ones did not bring:

  1. by title   the sections whose TITLE names what the part is about — the schema
                ("Type NotifyEvent"), the notification ("Notification notifyEvent"),
                the IS operation ("Operation modifyMOIAttributes") — fetched by
                clause. Exact names beat similarity: a query about NotifyEvent
                otherwise ranks the other Notify* types first.
  2. by clause  a bank rule's own clause (the section it was extracted from).
  3. by meaning a similarity search with the part's names and aspect.

All spec passes are restricted to the evaluated SERVICE's clauses (metadata
`service`; TS 28.532 holds six services side by side). The OpenAPI 3.0.1 reference
is searched with the Object(s) the aspect is about.

Building queries, filters and title targets is pure and tested without Qdrant; the
search goes through a `Search` callable, injectable for tests.

Out of scope for now: $refs to OTHER specs (TS28623_ComDefs.yaml#/...). The types
they import are defined only in those specs' annexes, and no annex is read — see
docs/JUDGE_PLAN.md §11.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from openapi_analysis.schemas.judge import Evidence, Part

# (text, metadata) of each hit
Search = Callable[[str, str, int, dict[str, str] | None], list[tuple[str, dict[str, Any]]]]

# The OpenAPI Objects an aspect is about — the words the reference is searched with.
_OPENAPI_TOPIC = {
    "parameters": "Parameter Object parameters Path Item Object Operation Object "
                  "path level operation level in query path required",
    "request_body": "Request Body Object content Media Type Object media type",
    "responses": "Responses Object Response Object status code default response "
                 "HTTP status code ranges 4XX 5XX",
    "callback": "Callback Object runtime expression callbacks notification",
    "operation": "Operation Object operationId summary fields",
    "unexpected_keys": "Path Item Object fields allowed operations",
    "path": "Paths Object path templating relative path",
    "definition": "Schema Object allOf oneOf anyOf composition inheritance properties",
    "placement": "Components Object schemas reusable objects $ref Reference Object",
    "missing": "Components Object schemas Schema Object",
    "extra": "Components Object schemas Reference Object $ref external document",
}
_RULE_TYPE_TOPIC = {
    "path_operation": "operation", "path_parameter": "parameters",
    "query_parameter": "parameters", "request_body": "request_body",
    "response": "responses", "callback": "callback", "schema_property": "definition",
}
# Words the spec uses for an aspect (similarity search on the spec).
_SPEC_TOPIC = {
    "parameters": "query parameters URI variables",
    "request_body": "request body message body media type",
    "responses": "response status codes error response",
    "callback": "notification notify",
    "definition": "data type attributes",
    "placement": "data type", "missing": "data type", "extra": "data type",
}
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
# the label words of a 3GPP heading that DEFINES something ("Type MoiChange")
_DEFINING = "Type|Enumeration|Notification|Operation|IOC|Class|Attribute"
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _bank_rule(part: Part) -> dict:
    return (part.generated[0] if isinstance(part.generated, list) else part.generated) or {}


def _topic(part: Part) -> str:
    """The aspect key of a part ('callback notifyEvent' → 'callback'; bank rule → by type)."""
    if part.evaluation == "rulesbank":
        rule = part.official or _bank_rule(part)
        return _RULE_TYPE_TOPIC.get(rule.get("rule_type", ""), "operation")
    return part.aspect.split(" ", 1)[0]


def _words(*items: str) -> str:
    return " ".join(dict.fromkeys(w for i in items if i for w in str(i).split()))


def names(part: Part) -> list[str]:
    """The exact names a part is about — its own subject first (the notification, the
    schema it owns, the IS operation / attribute of a bank rule), then the schemas it
    references — so a title-target limit never drops the subject itself."""
    subject = []
    if part.aspect.startswith("callback "):
        subject.append(part.aspect.split(" ", 1)[1])
    if part.owner.startswith("SCHEMA "):
        subject.append(part.owner.split(" ", 1)[1])
    found = [*subject, *part.hints.terms, *part.hints.schemas]
    return [n for n in dict.fromkeys(found) if _IDENTIFIER.match(n)]


def title_targets(part: Part, outline: Sequence[tuple[str, str, bool]], service: str = "",
                  spec: str = "28532", limit: int = 4, children: int = 2) -> list[str]:
    """Indexed clauses that DEFINE the part's subject, in the service — or, for such a
    title without text of its own, its first indexed sub-clauses.

    A name counts only in a defining heading, the 3GPP convention "Type X",
    "Enumeration X", "Notification X", "Operation X": a bare word match would take
    "Resource structure on the MnS producer" for the schema Resource.
    """
    from openapi_analysis.judge.spec_index import service_of

    indexed = [c for c, _, ok in outline if ok and c]
    clauses: list[str] = []
    for name in names(part):
        word = re.compile(rf"\b(?:{_DEFINING})\s+{re.escape(name)}(?![A-Za-z0-9])")
        for clause, title, ok in outline:
            if not clause or not word.search(title) \
                    or (service and service_of(spec, clause) != service):
                continue
            found = [clause] if ok else [c for c in indexed if c.startswith(clause + ".")][:children]
            clauses += [c for c in found if c not in clauses]
    return clauses[:limit]


def spec_query(part: Part) -> str:
    """Similarity query over the spec, from the part's own names and its aspect."""
    h = part.hints
    rule_text = _bank_rule(part).get("rule_text", "") if part.evaluation == "rulesbank" else ""
    return _words(rule_text, *h.terms, h.method.upper(), re.sub(r"[{}=/]", " ", h.path),
                  *h.schemas, _SPEC_TOPIC.get(_topic(part), ""))[:500]


def openapi_query(part: Part) -> str:
    """Query over the OpenAPI reference: the Objects the aspect is about."""
    return _OPENAPI_TOPIC.get(_topic(part), _OPENAPI_TOPIC["operation"])


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


def retrieve_evidence(part: Part, spec_collection: str, *, search: Search,
                      service: str = "", titles: Sequence[tuple[str, str, bool]] = (),
                      spec_k: int = 6, openapi_k: int = 3,
                      openapi_collection: str = "openapi_reference") -> list[Evidence]:
    """The evidence for one part (see the module docstring for the passes)."""
    evidence: list[Evidence] = []
    seen: set[str] = set()

    def take(source: str, collection: str, query: str, filters: dict | None,
             hits: list[tuple[str, dict[str, Any]]], limit: int) -> None:
        for text, meta in hits:
            if sum(e.source == source for e in evidence) >= limit:
                return
            clause = str(meta.get("clause", ""))
            if text in seen or (source == "spec" and _is_annex(clause)):
                continue
            seen.add(text)
            title = str(meta.get("title", "")) or next(iter(_HEADING.findall(text)), "")
            evidence.append(Evidence(source=source, collection=collection, query=query,
                                     filters=filters or {}, clause=clause, title=title,
                                     text=text))

    query = spec_query(part)
    scope = {"service": service} if service else {}
    for clause in title_targets(part, titles, service):                       # 1. title
        f = {"clause": clause}
        take("spec", spec_collection, query, f, search(query, spec_collection, 2, f), spec_k)
    if part.hints.clause:                                                     # 2. clause
        f = {"clause": part.hints.clause}
        take("spec", spec_collection, query, f, search(query, spec_collection, 2, f), spec_k)
    take("spec", spec_collection, query, scope or None,                       # 3. meaning
         search(query, spec_collection, spec_k + 2, scope or None), spec_k)
    oquery = openapi_query(part)
    take("openapi", openapi_collection, oquery, None,
         search(oquery, openapi_collection, openapi_k, None), openapi_k)
    return evidence
