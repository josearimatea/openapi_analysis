"""Split a 3GPP spec (markdown) into sections and index it for the judge's RAG.

One collection per spec version (config.judge_settings.spec_collection), built once
by scripts/index_specs.py and kept — the same question always searches the same
index. Every chunk carries the section it came from:

    spec    "28532"            code   "i20"
    clause  "12.1.1.1.1"       title  "12.1.1.1.1 Introduction"

The clause, not a sequential section number, is what identifies a section: it is
written in the spec itself and in every bank rule's section_title, so a bank rule
can be traced to its clause whatever parser cut the document.

NO ANNEX, EVER (docs/JUDGE_PLAN.md §4.1). A 3GPP spec closes with annexes that hold
the finished OpenAPI documents — Annex A of TS 28.532 IS the official YAML. Indexed,
it would let the judge "read the spec" and find the answer it is judging against,
making the verdict circular. So the text is reduced to its normative part first, the
way openapi_generator does it (utils/parsers.normative_only): the contents listing
is dropped, then everything from the first annex heading on. As a second guard, any
section still holding an `openapi: <n>` line is dropped too.

Then the text is cut at every heading (setext level-2 headings normalised to ATX
first, as openapi_rulesbank does).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Setext level-2 heading: a text line followed by a line of dashes (as rulesbank).
_SETEXT_H2 = re.compile(r"^(?P<title>[^\n]+)\n-{2,}[ \t]*$", re.MULTILINE)
_ATX = re.compile(r"^#{1,9}[ \t]+(?P<title>.+?)[ \t#]*$", re.MULTILINE)
# a clause number, segments possibly suffixed by a letter ("12.1.1.4.1a.7"), or an
# annex letter ("A.1.1", "A")
_CLAUSE = re.compile(
    r"^(?:Annex\s+)?(?P<clause>\d+[a-z]?(?:\.\d+[a-z]?)*|[A-Z](?:\.\d+[a-z]?)+|[A-Z]\b)")
_OPENAPI_LINE = re.compile(r"^\s*(?:```\w*\s*)?openapi:\s*\d", re.MULTILINE)
_TOC_LINK = re.compile(r"\]\(#")
_ANCHOR = re.compile(r"\s*\{#[^}]*\}\s*$")
# As openapi_generator/utils/parsers.py: an annex heading (in the contents listing
# and where the annex begins), and a contents entry ending in a page reference.
_ANNEX_HEADING = re.compile(r"^#*\s*Annex\s+[A-Z]\b", re.IGNORECASE | re.MULTILINE)
_CONTENTS_ENTRY = re.compile(r"\[\d+\]\(#[^)]*\)\s*$", re.MULTILINE)


def normative_only(md_text: str) -> str:
    """The spec's normative text: no contents listing, no annexes.

    Same cut as openapi_generator's normative_only, in the same order: the contents
    listing names every annex before the body begins, so it goes first (everything
    up to its last entry); then the body is cut at the first annex heading left.
    """
    body = md_text
    entries = list(_CONTENTS_ENTRY.finditer(body))
    if entries:
        body = body[entries[-1].end():]
    annexes = list(_ANNEX_HEADING.finditer(body))
    return body[: annexes[0].start()] if annexes else body


@dataclass(frozen=True)
class Section:
    clause: str       # "12.1.1.1.1", "A.1.1", "" when the title has none
    title: str
    content: str


def clause_of(title: str) -> str:
    """The clause number a section title starts with, '' if none ('Foreword')."""
    m = _CLAUSE.match(title.strip().strip("*").strip())
    return m.group("clause") if m else ""


def _is_openapi_annex(title: str, content: str) -> bool:
    return "openapi document" in title.lower() or bool(_OPENAPI_LINE.search(content))


def _is_toc(content: str) -> bool:
    lines = [ln for ln in content.splitlines() if ln.strip()]
    return len(lines) >= 5 and sum(bool(_TOC_LINK.search(ln)) for ln in lines) > len(lines) / 2


def _all_sections(md_text: str) -> list[Section]:
    """Every heading of the normative text, with its own text (possibly empty)."""
    text = _SETEXT_H2.sub(lambda m: f"## {m.group('title').strip()}", normative_only(md_text))
    heads = list(_ATX.finditer(text))
    sections = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        title = _ANCHOR.sub("", head.group("title")).strip()   # drop pandoc "{#id}"
        sections.append(Section(clause=clause_of(title), title=title,
                                content=text[head.end():end].strip()))
    return sections


def _indexable(s: Section) -> bool:
    return bool(s.content) and not _is_openapi_annex(s.title, s.content) \
        and not _is_toc(s.content)


def split_sections(md_text: str) -> list[Section]:
    """Cut a spec's NORMATIVE text into sections (no contents listing, no annex)."""
    return [s for s in _all_sections(md_text) if _indexable(s)]


def block_of(clause: str) -> str:
    """The two-level block of a clause: '12.1.1.4.1a.7' → '12.1'."""
    return ".".join(clause.split(".")[:2]) if clause else ""


def in_scope(clause: str, scope: tuple[str, ...]) -> bool:
    """Whether a clause falls in one of the scope's blocks (empty scope: everything)."""
    return not scope or any(clause == b or clause.startswith(b + ".") for b in scope)


def segments(path: Path, spec: str, code: str) -> list[dict]:
    """The sections of one spec file as qdrant_3gpp_rag segments (text + metadata)."""
    return [{"text": f"{s.title}\n\n{s.content}", "spec": spec, "code": code,
             "clause": s.clause, "title": s.title}
            for s in split_sections(path.read_text(encoding="utf-8"))]


def index_spec(path: Path, spec: str, code: str, *, force: bool = False) -> tuple[str, int]:
    """Index one spec version into its fixed collection. Returns (collection, chunks).

    Skips (returns its current size) when the collection already holds vectors,
    unless force=True.
    """
    from qdrant_3gpp_rag import QdrantFactory, index_segments

    from openapi_analysis.config import judge_settings as s

    factory = QdrantFactory.get_instance(host=s.QDRANT_HOST, port=s.QDRANT_PORT,
                                         model_name=s.EMBEDDING_MODEL,
                                         device=s.EMBEDDING_DEVICE)
    collection = s.spec_collection(spec, code)
    if not force and factory.client.collection_exists(collection):
        count = factory.client.count(collection).count
        if count:
            return collection, count
    chunks = index_segments(segments(path, spec, code), factory=factory,
                            collection_name=collection, chunk_size=s.SPEC_CHUNK_SIZE,
                            chunk_overlap=s.SPEC_CHUNK_OVERLAP,
                            embedding_dim=s.EMBEDDING_DIM, recreate=True)
    return collection, chunks


# ── the shared corpus (qdrant_3gpp_rag): cut its annexes out at retrieval ─────

# an annex heading where the annex begins — not a contents entry, which ends in a page
_ANNEX_START = re.compile(r"^#*\s*Annex\s+[A-Z]\b[^\n]*?(?<![\d\s])\s*$",
                          re.IGNORECASE | re.MULTILINE)
# a table the corpus extracted and appended after the text ("**Spec 28532-i00, ...")
EXTRACTED_TABLE = re.compile(r"^\*\*Spec \S+, Release")
# a line of an OpenAPI document ("  $ref: ...", "- name: scope", "responses:")
_OPENAPI_KEY = re.compile(
    r"^\s*(?:\\?-\s+)?(?:openapi|info|paths|components|schemas|parameters|responses|"
    r"requestBody|content|schema|\\?\$ref|type|properties|items|required|in|name|"
    r"description|allOf|oneOf|anyOf|enum|format|servers|callbacks):(?:\s|$)", re.MULTILINE)
# a contents-listing line: "12.1.1 Title ...... 123"
_CONTENTS_LINE = re.compile(r"^\s*(?:Annex\s+)?[\dA-Z][\d.a-z]*\s+\S.*\s\d{1,3}\s*$",
                            re.MULTILINE)


def _is_contents(text: str) -> bool:
    """A chunk of the contents listing (its entries end in a page number)."""
    return len(_CONTENTS_LINE.findall(text)) >= 5


def annex_cut(chunks: dict[int, str]) -> tuple[int, int] | None:
    """(chunk_index, offset) where the annexes begin in a corpus collection that holds
    one spec as consecutive chunks — the same cut as normative_only, on chunks: the
    first annex heading outside the contents listing. Everything after it in the text
    is annex; the tables the corpus extracted and appended after the text are not."""
    for idx in sorted(chunks):
        text = chunks[idx]
        if EXTRACTED_TABLE.match(text) or _is_contents(text):
            continue
        m = _ANNEX_START.search(text)
        if m:
            return idx, m.start()
    return None


def corpus_text(text: str, chunk_index: int | None,
                cut: tuple[int, int] | None) -> str:
    """A corpus chunk reduced to its normative text — '' when nothing of it is:
    an annex chunk, a contents listing, or a piece of an OpenAPI document."""
    if cut is not None and isinstance(chunk_index, int) and not EXTRACTED_TABLE.match(text):
        if chunk_index > cut[0]:
            return ""
        if chunk_index == cut[0]:
            text = text[:cut[1]]
    if len(_OPENAPI_KEY.findall(text)) >= 4 or _OPENAPI_LINE.search(text):
        return ""
    if _is_contents(text):
        return ""
    return text if text.strip() else ""


# a table or figure caption names its clause: "Table 12.5.1.3.2.1.3.2-2: ..."
_CAPTION = re.compile(r"\b(?:Table|Figure)\s+(?P<clause>\d+[a-z]?(?:\.\d+[a-z]?)+)-\d+")


def heading_clause(text: str) -> tuple[str, str]:
    """(clause, title) of a corpus chunk — the corpus carries no clause in its
    metadata: the first numbered heading in the chunk, else the clause its first
    table or figure caption names; ('', '') if neither."""
    for m in _ATX.finditer(text):
        title = _ANCHOR.sub("", m.group("title")).strip()
        clause = clause_of(title)
        if clause:
            return clause, title
    m = _CAPTION.search(text)
    if m:
        return m.group("clause"), f"(caption) {m.group(0)}"
    return "", ""


def _headings(text: str) -> list[tuple[str, str]]:
    out = []
    for m in _ATX.finditer(text):
        title = _ANCHOR.sub("", m.group("title")).strip()
        if clause_of(title):
            out.append((clause_of(title), title))
    return out


def chunk_clauses(chunks: dict[int, str]) -> dict[int, tuple[str, str]]:
    """{chunk_index: (clause, title)} in effect where each chunk BEGINS, for a corpus
    collection holding one spec as consecutive chunks: the last heading before it.
    (The corpus cuts by size, not by section: a chunk may end one section and begin
    the next — split_by_heading gives each piece its own clause.) An extracted table,
    appended after the text, has only its caption's clause."""
    out: dict[int, tuple[str, str]] = {}
    current = ("", "")
    for idx in sorted(chunks):
        text = chunks[idx]
        if EXTRACTED_TABLE.match(text):
            out[idx] = heading_clause(text)
            continue
        out[idx] = current
        heads = _headings(text)
        if heads:
            current = heads[-1]
    return out


def split_by_heading(text: str, begins_in: tuple[str, str]) -> list[tuple[str, str, str]]:
    """A chunk cut at its numbered headings: [(clause, title, text)] — the text before
    the first heading belongs to the section the chunk begins in (`begins_in`)."""
    cuts = [(m.start(), _ANCHOR.sub("", m.group("title")).strip()) for m in _ATX.finditer(text)]
    cuts = [(pos, title) for pos, title in cuts if clause_of(title)]
    pieces: list[tuple[str, str, str]] = []
    start, (clause, title) = 0, begins_in
    for pos, head in cuts:
        if text[start:pos].strip():
            pieces.append((clause, title, text[start:pos].strip()))
        start, clause, title = pos, clause_of(head), head
    if text[start:].strip():
        pieces.append((clause, title, text[start:].strip()))
    return pieces
