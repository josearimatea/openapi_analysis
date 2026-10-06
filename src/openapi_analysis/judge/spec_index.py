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
from functools import lru_cache
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


@lru_cache(maxsize=8)
def outline(path: Path) -> tuple[tuple[str, str, bool], ...]:
    """(clause, title, indexed) of every heading of a spec's normative text.

    Headings without text of their own are kept (indexed=False): a title naming the
    subject ("11.1.1.10 Notification notifyEvent") often has its text in children
    ("11.1.1.10.1 Definition") whose titles do not repeat the name.
    """
    return tuple((s.clause, s.title, _indexable(s))
                 for s in _all_sections(path.read_text(encoding="utf-8")))


def service_of(spec: str, clause: str) -> str:
    """The management service a clause belongs to ('' for clauses common to all)."""
    from openapi_analysis.config.judge_settings import SPEC_SERVICE_CLAUSES

    for service, prefixes in SPEC_SERVICE_CLAUSES.get(spec, {}).items():
        if any(clause == p or clause.startswith(p + ".") for p in prefixes):
            return service
    return ""


def segments(path: Path, spec: str, code: str) -> list[dict]:
    """The sections of one spec file as qdrant_3gpp_rag segments (text + metadata)."""
    return [{"text": f"{s.title}\n\n{s.content}", "spec": spec, "code": code,
             "clause": s.clause, "title": s.title, "service": service_of(spec, s.clause)}
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
