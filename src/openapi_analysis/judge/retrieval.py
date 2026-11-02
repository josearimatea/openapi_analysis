"""Retrieve what the 3GPP spec and the OpenAPI reference say about ONE part.

Several focused queries per part — never one query mixing everything (measured: a
query carrying the part's name together with every schema it references and generic
aspect words ranked the part's own definition 6th, behind look-alike types; the name
alone ranked it 1st):

  spec (the main spec's collection — normative text of the evaluated service only,
  filtered on the server: no annex, clause inside the scope read from the bank):
    0. defining   for a type or a notification, the sections whose `defines` holds it
    1. subject    the part's subject alone: "NotifyEvent", "HTTP PATCH"
    2. definition how a spec states it: "Definition of type NotifyEvent",
                  "Notification notifyEvent"; for a bank rule, its own rule_text (a
                  sentence of the spec)
    3. difference the subject with what concretely differs: response codes,
                  parameter names, media types, property names

    4. elsewhere  for a block found on another path, the names of that path
    then the clauses of other specs the passages found refer to ("TS 32.158 [15], clause
    6.1"), and the definitions of $refs to other files, in the corpus of all specs. A spec
    of a later Release than the evaluated one is left out; an earlier one, reported.

  OpenAPI reference (the OpenAPI 3.0.1 collection), 2 queries:
    1. object     the OpenAPI Object(s) the aspect is about: "Responses Object"
    2. concept    the concept in play, with the concrete values: "default response,
                  HTTP status code ranges 4XX 5XX, 200 204"

Building the queries is pure and tested without Qdrant; the search goes through a
`Search` callable, injectable for tests. Every chunk is kept as Evidence with the
query that brought it, so a verdict can be audited.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

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
# a generator part's block kind (judge/group_parts.py: aspect "<kind> — ...") → topic
_KIND_TOPIC = {"response": "responses", "parameter": "parameters", "media_type": "request_body",
               "callback": "callback", "operation": "operation", "schema": "definition",
               "header": "metadata", "path": "path", "component": "block", "block": "block"}


def _kind(part: Part) -> str:
    return part.aspect.split(" — ", 1)[0] if " — " in part.aspect else ""


# ── what a part is about ─────────────────────────────────────────────────────

def _bank_rule(part: Part) -> dict:
    return (part.generated[0] if isinstance(part.generated, list) else part.generated) or {}


def topic(part: Part) -> str:
    """The aspect key: 'callback notifyEvent' → 'callback'; a bank rule → by its type."""
    if part.evaluation == "rulesbank":
        rule = part.official or _bank_rule(part)
        return _RULE_TYPE_TOPIC.get(rule.get("rule_type", ""), "operation")
    if _kind(part) in _KIND_TOPIC:
        return _KIND_TOPIC[_kind(part)]
    return part.aspect.split(" ", 1)[0]


def subject(part: Part) -> str:
    """The thing the part is about, as a spec names it."""
    kind = _kind(part)
    if kind == "schema" and part.hints.schemas:
        return part.hints.schemas[0]
    if kind == "callback":                       # "callback notifyX — POST ... — registered by"
        return part.owner.split(" — ", 1)[0].removeprefix("callback ").strip()
    if kind in ("header", "component", "block"):
        return part.owner.split(" — ", 1)[0]
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


# Only what is SEARCHED WITH is limited, never what the judge reads: the query becomes one
# vector, and the more it mixes the less it points to the right section (see the docstring).
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
    elsewhere = [" ".join(w for w in re.split(r"[{}=/]+", p) if w) + " resource URI"
                 for p in part.hints.other_paths]
    return [q[:400] for q in dict.fromkeys([name, definition, difference, *elsewhere]) if q.strip()]


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


_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def spec_filters(scope: tuple[str, ...]) -> list[dict[str, Any]]:
    """The filters of a spec search, one per block of the scope: no annex, inside the
    block. Applied by the server, so every chunk returned counts."""
    return [{"annex": False, "clause_ancestors": b} for b in scope] or [{"annex": False}]


def defined_names(part: Part) -> list[str]:
    """What a section may DEFINE for this part: a type, or a notification."""
    t = topic(part)
    if t == "definition":
        return part.hints.schemas[:1]
    return [subject(part)] if t == "callback" else []


_EXTERNAL = re.compile(r"^TS(?P<spec>\d+)_[^#]*#/components/[A-Za-z]+/(?P<name>[^/]+)$")


# "TS 32.158 [15], clause 6.1" as a spec writes it, the brackets escaped in Markdown
_CITED = re.compile(r"TS\s+(?P<a>\d\d)\.(?P<b>\d{3})\s*(?:\\?\[\d+\\?\])?\s*,?\s*"
                    r"clause\s+(?P<clause>\d[\dA-Za-z.]*[\dA-Za-z])")


def cited_clauses(texts: list[str]) -> list[tuple[str, str]]:
    """(spec number, clause) of each clause of another spec the passages refer to."""
    return list(dict.fromkeys((m["a"] + m["b"], m["clause"])
                              for text in texts for m in _CITED.finditer(text)))


def _release_of(meta: dict[str, Any]) -> str:
    """The Release letter of a chunk ('28623-i40' -> 'i'), '' when not recorded."""
    return str(meta.get("spec", "")).partition("-")[2][:1]


def external_targets(part: Part) -> list[tuple[str, str, str]]:
    """(reference, spec number, schema name) of each $ref to another 3GPP file."""
    found = ((r, _EXTERNAL.match(r)) for r in part.hints.external_refs)
    return [(r, m["spec"], m["name"]) for r, m in found if m]


def retrieve_evidence(part: Part, spec_collection: str, *, search: Search,
                      scope: tuple[str, ...] = (), per_query: int = 5,
                      per_definition: int = 3,
                      openapi_collection: str = "openapi_reference",
                      external_collection: str = "", release: str = "",
                      notes: list[str] | None = None) -> list[Evidence]:
    """The evidence for one part, none repeated: the sections that define its subject,
    then each spec query's chunks, then each reference query's.

    Measured on real parts (docs/RASTREIO.md): filtering on the server and asking for
    the defining sections first finds the same clauses as searching unfiltered and
    cutting afterwards, higher up and with about 20% fewer chunks; a larger k, only
    more noise. Annexes stay out: the annex of a spec holds the official YAML itself."""
    evidence: list[Evidence] = []
    seen: set[str] = set()

    def take(source: str, collection: str, query: str, hits: list[tuple[str, dict[str, Any]]],
             filters: dict[str, Any] | None = None) -> None:
        for text, meta in hits:
            if text in seen:
                continue
            seen.add(text)
            title = str(meta.get("title", "")) or next(iter(_HEADING.findall(text)), "")
            evidence.append(Evidence(source=source, collection=collection, query=query,
                                     filters={k: str(v) for k, v in (filters or {}).items()},
                                     clause=str(meta.get("clause", "")), title=title,
                                     path=str(meta.get("path", "")), text=text))

    def take_external(title: str, query: str, hits: list[tuple[str, dict[str, Any]]],
                      f: dict[str, Any]) -> None:
        """Of another spec, the same Release or an earlier one: a non-specific reference is
        to the latest version in the same Release, and a later one did not exist yet."""
        for text, meta in hits:
            other, spec = _release_of(meta), str(meta.get("spec", ""))
            if release and other and other > release:
                if notes is not None:
                    notes.append(f"{spec} left out: later than Release '{release}'")
                continue
            if release and other and other < release and notes is not None:
                notes.append(f"{spec} used: earlier than Release '{release}', no later one found")
            before = len(evidence)
            take("spec", external_collection, query, [(text, meta)], f)
            for e in evidence[before:]:
                e.title = f"{title}{f' ({spec})' if spec else ''} — {e.title}"

    filters = spec_filters(scope)
    for name in defined_names(part):
        for f in filters:
            f = {**f, "defines": name}
            take("spec", spec_collection, name, search(name, spec_collection, per_definition, f), f)
    for q in spec_queries(part):
        for f in filters:
            take("spec", spec_collection, q, search(q, spec_collection, per_query, f), f)
    for ref, spec, name in external_targets(part) if external_collection else ():
        # the definition itself, in the spec the file belongs to — annexes included: for a
        # common schema, that is where the definition is
        f = {"spec_number": spec, "defines": name}
        take_external(f"definition of {ref}", ref,
                      search(name, external_collection, per_definition, f), f)
    # a referred clause may be long: searched by the part's subject and by what differs
    asked = list(dict.fromkeys([subject(part), *spec_queries(part)[2:]]))
    for spec, clause in (cited_clauses([e.text for e in evidence]) if external_collection else ()):
        f = {"spec_number": spec, "clause_ancestors": clause}
        for q in asked:
            take_external(f"cited as TS {spec} clause {clause}", q,
                          search(q, external_collection, per_definition, f), f)
    for q in openapi_queries(part):
        take("openapi", openapi_collection, q, search(q, openapi_collection, per_query, None))
    return evidence
