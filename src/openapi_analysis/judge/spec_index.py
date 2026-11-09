"""Index a 3GPP spec (markdown) for the judge's RAG, and read the clause of a section.

A spec version missing from the shared corpus gets a collection of its own here
(config.judge_settings.spec_collection), kept — the same question always searches the
same index. The cut is qdrant_3gpp_rag's (build_3gpp_segments → chunk_spec_sections),
the same openapi_rulesbank and openapi_generator use: one chunk per section, carrying
its clause and marked `annex` when it belongs to one.

NO ANNEX, EVER (docs/JUDGE_PLAN.md §4.1). Annex A of TS 28.532 IS the official YAML;
read by the judge, the verdict would be circular. The annex chunks are indexed (marked)
and kept out at search time: every spec search filters on annex = False
(judge/retrieval.spec_filters).

The clause, not a sequential section number, is what identifies a section: it is
written in the spec itself and in every bank rule's section_title, so a bank rule
can be traced to its clause whatever parser cut the document.
"""

from __future__ import annotations

import re
from pathlib import Path

# a clause number, segments possibly suffixed by a letter ("12.1.1.4.1a.7"), or an
# annex letter ("A.1.1", "A")
_CLAUSE = re.compile(
    r"^(?:Annex\s+)?(?P<clause>\d+[a-z]?(?:\.\d+[a-z]?)*|[A-Z](?:\.\d+[a-z]?)+|[A-Z]\b)")


def clause_of(title: str) -> str:
    """The clause number a section title starts with, '' if none ('Foreword')."""
    m = _CLAUSE.match(title.strip().strip("*").strip())
    return m.group("clause") if m else ""


def block_of(clause: str) -> str:
    """The two-level block of a clause: '12.1.1.4.1a.7' → '12.1'."""
    return ".".join(clause.split(".")[:2]) if clause else ""


def index_spec(path: Path, collection: str) -> int:
    """Index one spec version here, the way the shared corpus is indexed (qdrant_3gpp_rag:
    same sections and metadata, so the same search works on it). A re-run embeds only
    what changed. Returns the chunks written."""
    from qdrant_3gpp_rag import QdrantFactory, index_segments
    from qdrant_3gpp_rag.index_3gpp_all import _clean_markdown, build_3gpp_segments

    from openapi_analysis.config import judge_settings as s

    factory = QdrantFactory.get_instance(host=s.QDRANT_HOST, port=s.QDRANT_PORT,
                                         model_name=s.EMBEDDING_MODEL,
                                         device=s.EMBEDDING_DEVICE)
    doc = {"release": "", "series": "", "spec": path.stem, "file": path.name,
           "processed_text": _clean_markdown(path.read_text(encoding="utf-8"))}
    exists = factory.client.collection_exists(collection)
    return index_segments(build_3gpp_segments([doc]), factory=factory,
                          collection_name=collection, chunk_size=None,
                          embedding_dim=s.EMBEDDING_DIM, recreate=not exists, prune=exists)
