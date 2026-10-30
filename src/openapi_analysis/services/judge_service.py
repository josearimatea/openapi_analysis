"""Service for layer 3: judge the divergences of one evaluated input (needs [judge]).

    judge_openapi(generated_yaml, official_yaml)  -> JudgeReport
    judge_rules_bank(rules_bank, official_yaml)   -> JudgeReport

Flow per input: layer 1/2 report → parts — for a generated document, from the
alignment of the two documents (openapi/alignment.py, judge/grouping.py,
judge/group_parts.py); for a rules bank, one per rule (judge/parts.py) → for each part, retrieval
from the spec and the OpenAPI reference (judge/retrieval.py) → the LLM (judge/judge.py,
cached under data/judgements/) → a JudgeReport, saved as ONE report under
data/outputs/reports/<service>/<evaluation>/YYYY-MM-DD_HH-MM-SS.txt|.json.

Which spec and service apply is read from data/inputs/manifest.json — a generated
document → the bank it was built from → the spec that bank was extracted from — or
given explicitly (`spec_document`, `service`) for an input outside data/inputs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openapi_analysis.config import judge_settings as s
from openapi_analysis.config.paths import JUDGEMENTS_DIR, ROOT
from openapi_analysis.judge.group_parts import group_parts, grouping_counts, views
from openapi_analysis.judge.grouping import AskGrouping, run_grouping
from openapi_analysis.judge.judge import AskLLM, default_ask, judge_part
from openapi_analysis.judge.parts import rulesbank_parts
from openapi_analysis.judge.retrieval import CorpusLayout, Search, default_search, retrieve_evidence
from openapi_analysis.judge.spec_index import annex_cut, block_of, chunk_clauses, clause_of
from openapi_analysis.openapi.alignment import Aligner
from openapi_analysis.reporting.final import render_final
from openapi_analysis.reporting.text import render_judge
from openapi_analysis.schemas.judge import JudgeReport, Part
from openapi_analysis.schemas.rulesbank import SourceInfo, now
from openapi_analysis.services.inputs import Source, load, manifest, save_report
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
           save: bool, validity: tuple | None = None,
           official: SourceInfo | None = None,
           view: Callable[[list], dict] | None = None,
           grouping: dict[str, int] | None = None,
           since: dict | None = None) -> JudgeReport:
    from openapi_analysis.config.llm_config import usage_tracker

    collection = _collection(spec_document)
    search = search or default_search()
    ask = ask or default_ask()
    chosen = [p for p in parts if select is None or select(p)][:limit]
    before = since or usage_tracker.as_dict()      # since: the grouping's calls count too

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
                         parts_total=len(parts),
                         validity_generated=validity[0] if validity else None,
                         validity_official=validity[1] if validity else None,
                         official=official, views=view(verdicts) if view else {},
                         grouping=grouping or {})
    if save:            # ONE report per input and run: for a generated document, the
        # final analysis (validation, the two views of the fields, the detail)
        text = render_final(report) if evaluation == "generator" else render_judge(report)
        save_report(report, service, evaluation, Path(label).stem, text)
    return report


def judge_openapi(generated_yaml: Source, official_yaml: Source, *,
                  service: str | None = None, spec_document: Path | None = None,
                  scope: tuple[str, ...] | None = None,
                  select: Select | None = None, limit: int | None = None,
                  ask: AskLLM | None = None, search: Search | None = None,
                  group_ask: AskGrouping | None = None,
                  save: bool = True) -> JudgeReport:
    """Judge a generated OpenAPI document against the official one: align the two
    documents (exact steps, then the LLM grouper), judge every group that differs and
    every leftover, and count each document's fields by outcome.

    The scope comes from the bank the document was built from (manifest), unless given.
    """
    from openapi_analysis.config.llm_config import usage_tracker

    generated, label = load(generated_yaml)
    official, _ = load(official_yaml)
    if service is None or spec_document is None or scope is None:
        service_m, spec_m, bank_path = _origin(label, "generated")
        service, spec_document = service or service_m, spec_document or spec_m
        if scope is None:
            scope = scope_of_bank(load(bank_path)[0])
    report = evaluate_openapi(generated_yaml, official_yaml)     # sources: keeps their labels
    since = usage_tracker.as_dict()
    stem = Path(label).stem
    aligner = Aligner(official, generated, generated_label=stem,
                      official_label=f"{service} v{report.official.version}")
    aligner.deterministic()
    run_grouping(aligner, ask=group_ask, model="" if group_ask else s.MODEL,
                 cache_dir=None if group_ask else JUDGEMENTS_DIR)
    parts, part_of = group_parts(aligner, stem, [f"{i.location}: {i.message}"
                                                 for i in report.validity_generated.issues])
    return _judge(parts, "generator", label, service, spec_document, scope, select=select,
                  limit=limit, ask=ask, search=search, save=save,
                  validity=(report.validity_generated, report.validity_official),
                  official=report.official,
                  view=lambda verdicts: views(aligner, parts, part_of, verdicts),
                  grouping=grouping_counts(aligner), since=since)


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


def judge_all_generated(*, save: bool = True) -> list[JudgeReport]:
    """Semantic review of every generated document in data/inputs (per the manifest),
    against its service's official YAML — cached verdicts are read back."""
    from openapi_analysis.config.paths import reference_yaml
    from openapi_analysis.config.settings import OFFICIAL_REFERENCE

    reports = []
    for entry in manifest()["generated"]:
        service = entry["service"]
        if service in OFFICIAL_REFERENCE:
            reports.append(judge_openapi(ROOT / entry["path"],
                                         reference_yaml(service, OFFICIAL_REFERENCE[service]),
                                         save=save))
    return reports

