"""The grouper's prompt (docs/ALIGNMENT_PLAN.md, steps 5 and 6).

The grouper decides which block of the generated document CORRESPONDS to which block of
the official one — never whether it is right; that is the judge's job. It gets no RAG:
what OpenAPI says about the identity of each object is fixed here, extracted once from
the OpenAPI 3.0.1 specification (the version of the openapi_reference collection).

Each rule names the reference section it comes from, and the grouper cites the rule ids
(R1, R2, ...) in its reasons, so every grouping can be traced to the text it rests on.

Versioned: GROUPING_VERSION is part of every grouping's cache key. Bump it on any change
to this file.
"""

from __future__ import annotations

GROUPING_VERSION = "grouping-v8"

# (id, reference section, rule) — what makes two objects the SAME object in OpenAPI 3.0.
OPENAPI_IDENTITY_RULES: tuple[tuple[str, str, str], ...] = (
    # endpoints
    ("R1", "OpenAPI Object (servers); Server Object; Paths Object",
     ("The full URL of an endpoint is the server url with the path APPENDED to it (no "
     "relative resolution). Without servers, the server url is '/'. Path items and "
     "operations may declare their own servers, which override the ones above them. Two "
     "endpoints correspond when their full URLs are the same, even if the split between "
     "server url and path differs: server '{Root}/Svc' + path '/{id}' and no server + path "
     "'/{Root}/Svc/{id}' are the same endpoint. Within ONE document, two paths that give "
     "the same full URL are the same endpoint declared twice.")),
    ("R2", "Paths Object; Path Templating Matching",
     ("Templated paths with the same hierarchy but different template names are identical "
     "(/pets/{petId} and /pets/{name} are the same path). A concrete segment is not the "
     "same as a templated one (/pets/mine is not /pets/{petId}).")),
    ("R3", "Path Item Object; Operation Object",
     ("An operation is identified by its path and its HTTP method. operationId MUST be "
     "unique among all operations of the API: the same operationId on both sides points to "
     "the same operation.")),
    # parameters
    ("R4", "Parameter Object; Path Item Object; Operation Object",
     ("A parameter is identified by the combination of its name and its location (in): "
     "path, query, header or cookie. Parameter names are case sensitive; header names are "
     "case insensitive (RFC 7230).")),
    ("R5", "Path Item Object (parameters); Operation Object (parameters)",
     ("Parameters declared on the path item apply to EVERY operation of that path; an "
     "operation may override one (same name and in) but can never remove it. The same "
     "parameter declared on the path item on one side and on one or several operations on "
     "the other side is the same parameter, at another level.")),
    ("R6", "Parameter Object (name, in=path)",
     ("A path parameter's name MUST match a template segment of the path: a template "
     "segment renamed together with its path parameter is the same parameter.")),
    ("R7", "Parameter Object (schema, content)",
     ("A parameter is described by either a schema or a content map with one media type, "
     "never both: the same parameter may be written either way.")),
    ("R8", "Header Object",
     ("A header follows the Parameter Object, but its name is the key of the headers map "
     "and its location is implicitly header: a response header and a header parameter "
     "with the same name describe the same header.")),
    # request bodies and responses
    ("R9", "Request Body Object; Response Object (content); Media Type Object",
     ("content maps a media type (or a media type range such as text/*) to its schema; for "
     "a request that matches several keys, the most specific key applies. Media types "
     "SHOULD follow RFC 6838: a vendor-tree name (application/vnd.<org>.<x>+json) and the "
     "plain or differently-named media type for the same payload format (the same schema, "
     "the same purpose) describe the same representation under another name.")),
    ("R10", "Responses Object",
     ("A response is identified by its HTTP status code. A range (1XX, 2XX, 3XX, 4XX, 5XX) "
     "covers every code in it, and an explicit code takes precedence over its range. "
     "default covers every code not declared individually. So default on one side and "
     "error ranges or explicit error codes on the other side may describe the same "
     "responses (one block for several).")),
    # callbacks
    ("R11", "Operation Object (callbacks); Callback Object",
     ("A callback's key in callbacks is only a unique identifier: its name carries no "
     "meaning. Inside it, each key is a runtime expression that gives the URL of the "
     "callback request, and its value is a Path Item describing that request (method, "
     "request body, responses).")),
    ("R12", "Callback Object (Key Expression); Runtime Expressions",
     ("A runtime expression ($request.body#/url, $request.query.x, $response.header.y, "
     "...) is evaluated on the actual HTTP message. Two callbacks with different names or "
     "differently written expressions correspond when they describe the same delivery: "
     "the same method and the same request body schema, triggered by the same operation.")),
    # components and schemas
    ("R13", "Components Object",
     ("Objects under components have no effect on the API unless referenced from outside "
     "components. A component is identified by its section (schemas, responses, "
     "parameters, ...) and its name; names match ^[a-zA-Z0-9.\\-_]+$.")),
    ("R14", "Reference Object; Schema Object",
     ("A $ref stands for the object it points to: an inline definition and a $ref to a "
     "definition with that content describe the same thing. Properties written next to a "
     "$ref are ignored. A $ref is resolved as a JSON Reference: #/components/schemas/X "
     "resolves only to components.schemas.X, never to a schema of the same name defined "
     "elsewhere (that one is a copy at another place, of the same data type).")),
    ("R15", "Schema Object; Composition and Inheritance (Polymorphism)",
     ("allOf takes schemas that are validated independently but together compose ONE "
     "object; their order does not matter. The same data type may be written as an allOf "
     "of members, or with the members' contents merged into one schema (properties, "
     "required and type moved up or down): those are the same schema written another "
     "way. allOf members correspond by their $ref, else by their content.")),
    ("R16", "Schema Object (oneOf, anyOf, discriminator)",
     ("oneOf / anyOf list alternative schemas; their order does not matter. A discriminator "
     "only works with named (referenced) schemas, so an alternative written inline and one "
     "written as a $ref are the same alternative for grouping, though not for polymorphism.")),
    ("R17", "Schema Object (properties, items, additionalProperties, enum, required)",
     ("A property is identified by its name inside the schema that holds it; items by the "
     "array holding it. enum and required are sets of values: their order does not matter.")),
)


def _rules_block() -> str:
    return "\n".join(f"[{rid}] ({section}) {text}" for rid, section, text in
                     OPENAPI_IDENTITY_RULES)


_COMMON = f"""\
You align two OpenAPI 3.0 documents describing the same 3GPP API: the OFFICIAL one and a
GENERATED one. You decide which blocks CORRESPOND — which block of the generated document
plays the role of which block of the official one. You do NOT judge whether a block is
right, better or worse: a reviewer judges every group you form afterwards, with the 3GPP
specification and the OpenAPI reference. Grouping two blocks never means they are equal;
it means they must be compared with each other.

A block is one object of a fixed kind: an operation, a parameter, a request body media
type, a response, a callback, a schema, a composition member (allOf / oneOf / anyOf
item), another component. Each block has an id (A1, A2, ... official; B1, B2, ...
generated), its kind, its location in its document and its content.

What makes two objects the same object in OpenAPI 3.0 (from the OpenAPI 3.0.1
specification — cite these ids in your reasons):
{_rules_block()}

How to decide:
- Two blocks correspond when they play the SAME ROLE in the API: the same endpoint, the
  same parameter of the same operations, the same request or response payload, the same
  notification delivery, the same data type. Look at what the block is for — its
  identity under the rules above, its $refs, its properties, the operation it belongs
  to — not at how similar the text looks.
- Correspondence survives a change of location, level, name, order or form: a parameter
  moved from the path item to the operations (R5), a media type renamed (R9), default
  replaced by 4XX / 5XX (R10), a callback renamed (R11, R12), a schema copied elsewhere
  (R14) or flattened out of its allOf (R15).
- Correspondence also survives a malformed address. R1 and R2 tell when two URLs are
  the SAME; a different URL alone does not rule a block out. An endpoint whose path is
  wrong or partial but that does the same thing as one on the other side — the same
  method, operationId, parameters, bodies and responses — corresponds to it (a broken
  copy is still a copy; the reviewer judges the address).
- Only group blocks of the same kind, with one exception: an endpoint declared as an
  operation under paths on one side and as a callback on the other (R11, R12). They
  correspond when the operation plays the role of that callback's request — what it
  delivers (the method and the request body schema) and what it is for. When the
  delivery and the name point to different callbacks (an operationId of one
  notification, the body of another), say so in the reason and follow the delivery;
  when nothing decides between several callbacks, leave the operation ungrouped.
- Similar is not the same: two schemas with similar properties that describe different
  data, or two responses with the same body for different codes that are both declared
  on each side, do NOT correspond.
- A group may join one block with several on the other side only where OpenAPI makes ONE
  object cover several: a path-level parameter and its copies in each operation (R5),
  default and the ranges or codes it plays the role of (R10 — by what the response
  describes: a default described as an error corresponds to error codes such as 4XX /
  5XX, never to a success code such as 200 or 204), a schema and its copies (R14), a
  composition and its merged form (R15). Otherwise each block is one object: two media
  types are two representations (R9) and two status codes are two responses, so one
  generated media type never stands for two official ones — group it with the one it
  corresponds to best and leave the other ungrouped. Every block is in at most one group.
- Only use ids you were given.
- When no block on the other side plays the role of a block, leave it ungrouped: it is
  then reviewed as present on one side only. Do not force a group to leave nothing out.
- Give every group and every ungrouped block a short reason, naming the rules (R1, R2,
  ...) it rests on and what in the blocks shows it.
- Answer in English.
"""

GROUPING_SYSTEM = _COMMON + """
The exact correspondences (the same address, the same OpenAPI identity elsewhere) were
already grouped. You get:
- the OFFICIAL and the GENERATED documents, whole, as YAML. They are the ground for
  every decision: look up in them whatever you need — what an operation holds, where a
  schema is defined, what the servers say. Never assume what a document holds: read it;
- the INDEX of the groups already formed (G1, G2, ...), by location and identity. They
  are fixed: do not split or change them;
- the LEFTOVERS of ONE family of blocks (named in THIS REQUEST): the blocks, on both
  sides, with no counterpart so far (A1, A2, ... official; B1, B2, ... generated), by
  kind and location in their document;
- under each leftover, the blocks of the other side most alike it, of its kind — other
  leftovers (by id) and blocks already grouped (by group id). The similarity only
  orders them: a high one does not make a correspondence and a low one does not forbid
  it.
The inside of every grouped operation was already aligned block by block: a leftover
parameter, media type, response or callback is EXACTLY what was not found in the
operation of the other side. A leftover never joins the group of the operation that
holds it — that group is the operation itself, not its parameters, bodies, responses
or callbacks.
Decide, for every leftover of this request, one of:
- GROUP it with leftovers of the other side it corresponds to;
- JOIN it to an existing group, by the group id, when it is another form or copy of
  what that group already holds (a duplicated endpoint, a copy of a schema, the codes
  a default plays the role of) — never a different object of the same kind that merely
  sits next to it (a second media type, another status code);
- leave it UNGROUPED: it is then reviewed as present on one side only.
"""
