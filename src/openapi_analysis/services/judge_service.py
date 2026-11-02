"""Service for layer 3: judge the divergences of one evaluated input (needs [judge]).

    judge_openapi(generated_yaml, official_yaml, spec)  -> JudgeReport
    judge_rules_bank(rules_bank, official_yaml, spec)   -> JudgeReport

Flow per input: layer 1/2 report → parts — for a generated document, from the
alignment of the two documents (openapi/alignment.py, judge/grouping.py,
judge/group_parts.py); for a rules bank, one per rule (judge/parts.py) → for each part, retrieval
from the spec and the OpenAPI reference (judge/retrieval.py) → the LLM (judge/judge.py,
cached under data/judgements/) → a JudgeReport, saved as ONE report under
data/outputs/reports/<service>/<evaluation>/YYYY-MM-DD_HH-MM-SS.txt|.json.

The spec is an input: the version the analysis is based on. The input and the official
YAML are checked against it, and a difference is an error unless allow_other_version is
given (then the report states it). A spec version no collection holds is indexed on the
spot. Which service applies is read from data/inputs/manifest.json — or given (`service`)
for an input outside data/inputs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openapi_analysis.config import judge_settings as s
from openapi_analysis.config.paths import JUDGEMENTS_DIR, ROOT
from openapi_analysis.judge.group_parts import group_parts, grouping_counts, regroup, views
from openapi_analysis.judge.grouping import AskGrouping, run_grouping
from openapi_analysis.judge.judge import AskLLM, default_ask, judge_part
from openapi_analysis.judge.parts import rulesbank_parts
from openapi_analysis.judge.retrieval import Search, default_search, retrieve_evidence
from openapi_analysis.judge.spec_index import block_of, clause_of, index_spec
from openapi_analysis.openapi.alignment import Aligner
from openapi_analysis.reporting.final import render_final
from openapi_analysis.reporting.text import render_judge
from openapi_analysis.schemas.judge import JudgeReport, Part
from openapi_analysis.schemas.rulesbank import SourceInfo, now
from openapi_analysis.services.inputs import (
    Source,
    check_versions,
    load,
    manifest,
    official_of,
    save_report,
)
from openapi_analysis.services.inputs import (
    spec_document as spec_path,
)
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


def _spec_in(collection: str, stem: str) -> bool:
    """Whether a collection holds this exact version of a spec ("28532-i00")."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(host=s.QDRANT_HOST, port=s.QDRANT_PORT)
    return client.collection_exists(collection) and client.count(collection, count_filter=models.Filter(must=[
        models.FieldCondition(key="metadata.spec", match=models.MatchValue(value=stem))])).count > 0


def _collection(spec_document: Path) -> str:
    """The shared corpus collection of the spec an input comes from ('28532-i20' →
    '3gpp_rel18_28_28532')."""
    spec = spec_document.stem.partition("-")[0]
    if spec in s.SPEC_CORPUS and _spec_in(s.SPEC_CORPUS[spec], spec_document.stem):
        return s.SPEC_CORPUS[spec]
    code = spec_document.stem.partition("-")[2]
    own = s.spec_collection(spec, code)
    index_spec(spec_document, own)
    return own


def _judge(parts: list[Part], evaluation: str, label: str, service: str,
           spec_document: Path, scope: tuple[str, ...], *, select: Select | None,
           limit: int | None, ask: AskLLM | None, search: Search | None,
           save: bool, validity: tuple | None = None,
           official: SourceInfo | None = None,
           view: Callable[[list], dict] | None = None,
           grouping: Callable[[], dict[str, int]] | None = None,
           regroup: Callable[[list], tuple[list[Part], list[str]] | None] | None = None,
           version_notes: list[str] | None = None,
           since: dict | None = None) -> JudgeReport:
    from openapi_analysis.config.llm_config import usage_tracker

    collection = _collection(spec_document)
    search = search or default_search()
    ask = ask or default_ask()
    chosen = [p for p in parts if select is None or select(p)][:limit]
    before = since or usage_tracker.as_dict()      # since: the grouping's calls count too

    release_notes: list[str] = []

    def retrieve(part: Part):
        return retrieve_evidence(part, collection, search=search, scope=scope,
                                 per_query=s.PER_QUERY, per_definition=s.PER_DEFINITION,
                                 openapi_collection=s.OPENAPI_COLLECTION,
                                 external_collection=s.EXTERNAL_COLLECTION,
                                 release=spec_document.stem.partition("-")[2][:1],
                                 notes=release_notes)

    def judge_all(chosen: list[Part]) -> list:
        return [judge_part(p, retrieve=retrieve, ask=ask, model=s.MODEL,
                           cache_dir=JUDGEMENTS_DIR) for p in chosen]

    verdicts = judge_all(chosen)
    taken: list[str] = []
    again = regroup(verdicts) if regroup else None   # blocks the judge took out of a
    if again is not None:                           # group: cut again, judge once more
        parts, taken = again                        # (unchanged parts: from the cache)
        chosen = [p for p in parts if select is None or select(p)][:limit]
        verdicts = judge_all(chosen)
    after = usage_tracker.as_dict()
    usage = {k: round(after[k] - before[k], 6) for k in after}
    report = JudgeReport(evaluation=evaluation, input=label, spec_collection=collection,
                         spec=spec_document.stem,
                         service=service, scope=list(scope), model=s.MODEL,
                         prompt_version=verdicts[0].prompt_version if verdicts else "",
                         evaluated_at=now(), verdicts=verdicts, usage=usage,
                         parts_total=len(parts),
                         validity_generated=validity[0] if validity else None,
                         validity_official=validity[1] if validity else None,
                         official=official, views=view(verdicts) if view else {},
                         grouping=grouping() if grouping else {}, regrouped=taken,
                         version_notes=[*(version_notes or []),
                                        *dict.fromkeys(release_notes)])
    if save:            # ONE report per input and run: for a generated document, the
        # final analysis (validation, the two views of the fields, the detail)
        text = render_final(report) if evaluation == "generator" else render_judge(report)
        save_report(report, service, evaluation, Path(label).stem, text)
    return report


def judge_openapi(generated_yaml: Source, official_yaml: Source, spec: str | Path, *,
                  service: str | None = None, scope: tuple[str, ...] | None = None,
                  allow_other_version: bool = False,
                  select: Select | None = None, limit: int | None = None,
                  ask: AskLLM | None = None, search: Search | None = None,
                  group_ask: AskGrouping | None = None,
                  save: bool = True) -> JudgeReport:
    """Judge a generated OpenAPI document against the official one, based on `spec`: align
    the two documents (exact steps, then the LLM grouper), judge every group that differs
    and every leftover, and count each document's fields by outcome.

    The scope comes from the bank the document was built from (manifest), unless given.
    """
    from openapi_analysis.config.llm_config import usage_tracker

    spec_document = spec_path(spec)
    generated, label = load(generated_yaml)
    official, official_label = load(official_yaml)
    notes = check_versions(spec_document, label, "generated", official, official_label,
                           service=service, allow_other_version=allow_other_version)
    if service is None or scope is None:
        service_m, _, bank_path = _origin(label, "generated")
        service = service or service_m
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
    issues = [f"{i.location}: {i.message}" for i in report.validity_generated.issues]
    parts, part_of = group_parts(aligner, stem, issues)
    cut = {"parts": parts, "part_of": part_of}     # the parts as last cut (see regroup)

    def again(verdicts: list) -> tuple[list[Part], list[str]] | None:
        new = regroup(aligner, cut["parts"], cut["part_of"], verdicts, stem, issues)
        if new is None:
            return None
        cut["parts"], cut["part_of"], taken = new
        return cut["parts"], taken

    return _judge(parts, "generator", label, service, spec_document, scope, select=select,
                  limit=limit, ask=ask, search=search, save=save,
                  validity=(report.validity_generated, report.validity_official),
                  official=report.official,
                  view=lambda verdicts: views(aligner, cut["parts"], cut["part_of"], verdicts),
                  grouping=lambda: grouping_counts(aligner), regroup=again, since=since,
                  version_notes=notes)


def judge_rules_bank(rules_bank: Source, official_yaml: Source, spec: str | Path, *,
                     service: str | None = None, scope: tuple[str, ...] | None = None,
                     allow_other_version: bool = False,
                     select: Select | None = None, limit: int | None = None,
                     ask: AskLLM | None = None, search: Search | None = None,
                     save: bool = True) -> JudgeReport:
    """Judge the divergent rules of a rules bank, based on `spec` (scope read from the
    bank itself)."""
    spec_document = spec_path(spec)
    bank, label = load(rules_bank)
    official, official_label = load(official_yaml)
    notes = check_versions(spec_document, label, "rulesbank", official, official_label,
                           service=service, allow_other_version=allow_other_version)
    if service is None:
        service = _origin(label, "rulesbank")[0]
    scope = scope if scope is not None else scope_of_bank(bank)
    report = evaluate_rules_bank(bank, official)
    parts = rulesbank_parts(report, bank, Path(label).stem)
    return _judge(parts, "rulesbank", label, service, spec_document, scope, select=select,
                  limit=limit, ask=ask, search=search, save=save, version_notes=notes)


def judge_all_generated(*, save: bool = True) -> list[JudgeReport]:
    """Semantic review of every generated document in data/inputs (per the manifest),
    against the official YAML of its spec version — cached verdicts are read back."""
    reports = []
    for entry in manifest()["generated"]:
        official = official_of(entry)
        if official is not None:
            spec = _origin(entry["path"], "generated")[1]
            reports.append(judge_openapi(ROOT / entry["path"], official, spec, save=save))
    return reports

