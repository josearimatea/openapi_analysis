"""Service for layer 3: judge the divergences of one evaluated input (needs [judge]).

    judge_openapi(generated_yaml, official_yaml)  -> JudgeReport
    judge_rules_bank(rules_bank, official_yaml)   -> JudgeReport

Flow per input: layer 1/2 report → parts (judge/parts.py) → for each part, retrieval
from the spec and the OpenAPI reference (judge/retrieval.py) → the LLM (judge/judge.py,
cached under data/judgements/) → a JudgeReport, saved under
data/outputs/judge/<evaluation>/<service>/<input>.json|.txt, and the short
final analysis <input>_final.md.

Which spec and service apply is read from data/inputs/manifest.json — a generated
document → the bank it was built from → the spec that bank was extracted from — or
given explicitly (`spec_document`, `service`) for an input outside data/inputs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openapi_analysis.config import judge_settings as s
from openapi_analysis.config.paths import JUDGEMENTS_DIR, OUTPUTS_JUDGE_DIR, ROOT
from openapi_analysis.judge.judge import AskLLM, default_ask, judge_part
from openapi_analysis.judge.parts import (
    document_owners,
    generator_parts,
    leaf_census,
    rulesbank_parts,
)
from openapi_analysis.judge.retrieval import CorpusLayout, Search, default_search, retrieve_evidence
from openapi_analysis.judge.spec_index import annex_cut, block_of, chunk_clauses, clause_of
from openapi_analysis.reporting.markdown import render_judge_final
from openapi_analysis.reporting.text import render_judge
from openapi_analysis.schemas.judge import JudgeReport, Part
from openapi_analysis.schemas.rulesbank import now
from openapi_analysis.services.inputs import Source, load, manifest
from openapi_analysis.services.openapi_service import evaluate_openapi
from openapi_analysis.services.rulesbank_service import evaluate_rules_bank

Select = Callable[[Part], bool]


def scope_of_bank(bank: dict) -> tuple[str, ...]:
    """The spec blocks a service occupies, read from its bank: the two-level blocks of
    the clauses the bank's rules were extracted from ('12.1.1.1.3 …' → '12.1').

    Generic: no table per spec — whatever spec and service the rules bank processed,
    its own rules say where in that spec the service lives.
    """
    blocks = {block_of(clause_of(r.get("section_title", "")))
              for r in bank.get("rules") or [] if isinstance(r, dict)}
    return tuple(sorted(b for b in blocks if b))


def _origin(label: str, kind: str) -> tuple[str, Path, Path]:
    """(service, spec markdown, rules bank) of an input in data/inputs — a generated
    document leads to the bank it was built from, and that bank to its spec."""
    m = manifest()
    entry = next((e for e in m[kind] if e["path"] == label), None)
    if entry is None:
        raise ValueError(f"{label} is not in data/inputs/manifest.json — pass "
                         "spec_document=, service= and scope= explicitly")
    bank = entry if kind == "rulesbank" else next(b for b in m["rulesbank"]
                                                  if b["path"] == entry["rules_bank"])
    return entry["service"], ROOT / bank["spec_document"], ROOT / bank["path"]


def _collection(spec_document: Path) -> str:
    """The shared corpus collection of the spec an input comes from ('28532-i20' →
    '3gpp_rel18_28_28532')."""
    spec = spec_document.stem.partition("-")[0]
    if spec not in s.SPEC_CORPUS:
        raise ValueError(f"{spec_document.name}: spec {spec} has no corpus collection "
                         f"(SPEC_CORPUS = {s.SPEC_CORPUS})")
    return s.SPEC_CORPUS[spec]


def _corpus_layout(collection: str) -> CorpusLayout:
    """Where the annexes begin and which clause each chunk belongs to, in a corpus
    collection — read from the collection itself, once per run."""
    from qdrant_client import QdrantClient

    client = QdrantClient(host=s.QDRANT_HOST, port=s.QDRANT_PORT)
    chunks: dict[int, str] = {}
    offset = None
    while True:
        points, offset = client.scroll(collection, limit=1000, offset=offset,
                                       with_payload=True, with_vectors=False)
        for p in points:
            payload = p.payload or {}
            idx = (payload.get("metadata") or {}).get("chunk_index")
            if isinstance(idx, int):
                chunks[idx] = payload.get("page_content", "")
        if offset is None:
            return CorpusLayout(annex=annex_cut(chunks), clauses=chunk_clauses(chunks))


def _judge(parts: list[Part], evaluation: str, label: str, service: str,
           spec_document: Path, scope: tuple[str, ...], *, select: Select | None,
           limit: int | None, ask: AskLLM | None, search: Search | None,
           save: bool, owners: list[str] | None = None,
           leaves: dict[str, dict[str, int]] | None = None) -> JudgeReport:
    from openapi_analysis.config.llm_config import usage_tracker

    collection = _collection(spec_document)
    search = search or default_search()
    ask = ask or default_ask()
    chosen = [p for p in parts if select is None or select(p)][:limit]
    before = usage_tracker.as_dict()

    layout = _corpus_layout(collection)

    def retrieve(part: Part):
        return retrieve_evidence(part, collection, search=search, scope=scope,
                                 per_query=s.PER_QUERY, pool=s.SEARCH_POOL,
                                 openapi_collection=s.OPENAPI_COLLECTION, layout=layout)

    verdicts = [judge_part(p, retrieve=retrieve, ask=ask, model=s.MODEL,
                           cache_dir=JUDGEMENTS_DIR) for p in chosen]
    after = usage_tracker.as_dict()
    usage = {k: round(after[k] - before[k], 6) for k in after}
    report = JudgeReport(evaluation=evaluation, input=label, spec_collection=collection,
                         service=service, scope=list(scope), model=s.MODEL,
                         prompt_version=verdicts[0].prompt_version if verdicts else "",
                         evaluated_at=now(), verdicts=verdicts, usage=usage,
                         parts_total=len(parts), owners_total=len(owners or []),
                         leaves=leaves or {},
                         owners_equal=[o for o in owners or []
                                       if o not in {p.owner for p in parts}])
    if save:
        out = OUTPUTS_JUDGE_DIR / evaluation / service
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(label).stem
        (out / f"{stem}.json").write_text(report.model_dump_json(indent=2) + "\n",
                                          encoding="utf-8")
        (out / f"{stem}.txt").write_text(render_judge(report) + "\n", encoding="utf-8")
        (out / f"{stem}_final.md").write_text(render_judge_final(report), encoding="utf-8")
    return report


def judge_openapi(generated_yaml: Source, official_yaml: Source, *,
                  service: str | None = None, spec_document: Path | None = None,
                  scope: tuple[str, ...] | None = None,
                  select: Select | None = None, limit: int | None = None,
                  ask: AskLLM | None = None, search: Search | None = None,
                  save: bool = True) -> JudgeReport:
    """Judge the divergent parts of a generated OpenAPI document.

    The scope comes from the bank the document was built from (manifest), unless given.
    """
    generated, label = load(generated_yaml)
    official, _ = load(official_yaml)
    if service is None or spec_document is None or scope is None:
        service_m, spec_m, bank_path = _origin(label, "generated")
        service, spec_document = service or service_m, spec_document or spec_m
        if scope is None:
            scope = scope_of_bank(load(bank_path)[0])
    report = evaluate_openapi(generated, official)
    parts = generator_parts(report, generated, official, Path(label).stem)
    return _judge(parts, "generator", label, service, spec_document, scope, select=select,
                  limit=limit, ask=ask, search=search, save=save,
                  owners=document_owners(report, generated, official),
                  leaves=leaf_census(report, generated, official))


def judge_rules_bank(rules_bank: Source, official_yaml: Source, *,
                     service: str | None = None, spec_document: Path | None = None,
                     scope: tuple[str, ...] | None = None,
                     select: Select | None = None, limit: int | None = None,
                     ask: AskLLM | None = None, search: Search | None = None,
                     save: bool = True) -> JudgeReport:
    """Judge the divergent rules of a rules bank (scope read from the bank itself)."""
    bank, label = load(rules_bank)
    official, _ = load(official_yaml)
    if service is None or spec_document is None:
        service_m, spec_m, _ = _origin(label, "rulesbank")
        service, spec_document = service or service_m, spec_document or spec_m
    scope = scope if scope is not None else scope_of_bank(bank)
    report = evaluate_rules_bank(bank, official)
    parts = rulesbank_parts(report, bank, Path(label).stem)
    return _judge(parts, "rulesbank", label, service, spec_document, scope, select=select,
                  limit=limit, ask=ask, search=search, save=save)
