# openapi_analysis

A versioned instrument to evaluate what the two generators of this workspace
produce, against the **official 3GPP OpenAPI YAML**. Analysis only — this project
never generates rules or documents.

It exists because the numbers used to judge the generators were measured ad-hoc
and proved wrong more than once (a target extractor that did not descend into
`oneOf`/`allOf`; a ref count taken from log lines; rules indexed by a key that
could repeat). The measurement itself has to be trustworthy, so it lives here,
versioned and pinned by tests.

## Two evaluations

| | Evaluates | Against | How |
|---|---|---|---|
| **rulesbank** | the rules bank from `openapi_rulesbank` | rules extracted from the official YAML, in the same rules-bank format | rule by rule: **coverage** (address) and **fidelity** (value) |
| **openapi** | the YAML from `openapi_generator` | the official YAML itself | document against document: the two documents are aligned block by block, then every difference is judged |

## Three layers

1. **Agreement** (deterministic) — does it diverge from the official YAML?
   Agreement is not correctness: the official can be wrong, or worse than the
   generated one.
2. **Validity** (deterministic) — is each document valid OpenAPI 3.0
   (`openapi-spec-validator`)? See [docs/VALIDATION.md](docs/VALIDATION.md).
3. **Judgement** (LLM) — on each divergence, an LLM judge reads the 3GPP spec and
   the OpenAPI 3.0 reference (RAG, no annex of the evaluated spec) and rules:
   equivalent, improvement, error or uncertain, citing what it read. Verdicts are
   cached, so a run is reproducible. See [docs/JUDGE_PLAN.md](docs/JUDGE_PLAN.md).

**A document is compared within its own spec version.** The spec is a required input
(`--spec 28532-i00`): the version of the document and of the official YAML is checked
against it, and a mismatch is an error unless `--allow-other-version` is given (the
report then says so). If no collection holds that exact version, the spec is indexed
on the spot. The official version of each spec is in `OFFICIAL_BY_SPEC`
(`config/settings.py`).

For a generated document, the judgement works on an **alignment** of the two
documents ([docs/ALIGNMENT_PLAN.md](docs/ALIGNMENT_PLAN.md)) — grouping is not
judging:

```
official ┐  exact correspondences      LLM grouper (one call per       judge each group
         ├─ (deterministic: address, ─ family of blocks, with both  ─ that differs and
generated┘  OpenAPI identity)           YAMLs whole as ground)          each leftover
```

- **Deterministic grouping** — only what is exact by OpenAPI's own definition:
  the same address, the same path with other template names, the same
  `operationId`, a schema by name (copies included), a parameter by `in` + `name`
  at any level, a renamed callback with the same delivery.
- **LLM grouping** — what needs reading (`default` vs `4XX`/`5XX`, a path that
  repeats the server prefix, a callback declared as a path), with a fixed prompt
  of 17 OpenAPI 3.0.1 identity rules and deterministic checks on its answer.
- **Judging** — each group of corresponding blocks is one part; a block found
  elsewhere is one "moved" difference, never one missing plus one extra; an `allOf`
  member written at the root of its schema is compared field by field. Prose
  (descriptions, summaries, titles) is never an error or an improvement.
- **Definitions in other files** — a `$ref` to another 3GPP file is searched for in
  that spec, and a local schema with the exact name of such a definition is judged
  against it: it is an error or equivalent, never an improvement.

The report gives two views, each on its own base: how much of the **official**
the generated reproduces, and how much of the **generated** is right. A field is
one line of the YAML that holds a value; the document header is listed apart,
never scored.

What a rule is, and every counting decision, is in [docs/RULES.md](docs/RULES.md).
The history of the decisions is in [docs/RASTREIO.md](docs/RASTREIO.md).

## Usage

```bash
uv sync                                            # layers 1 and 2
uv sync --extra judge                              # + layer 3 (LLM, Qdrant, torch CPU)
uv run pytest                                      # 184 tests, results pinned

uv run openapi-analysis all [--no-judge]           # every input → data/outputs/reports/
uv run openapi-analysis rulesbank <bank.json> <official.yaml> --spec <spec> [--json]
uv run openapi-analysis openapi   <generated.yaml> <official.yaml> --spec <spec> [--json]
uv run openapi-analysis judge     generator|rulesbank <input> <official.yaml> --spec <spec> [--limit N]
uv run openapi-analysis extract   <official.yaml> [-o official_rules.json]
```

Layer 3 needs the Qdrant server of the workspace (`qdrant_3gpp_rag` collections)
and an LLM key in `.env` (`OPENROUTER_API_KEY` or `OPENAI_API_KEY`).

From another repo (the siblings, the chat UI):

```python
from openapi_analysis.services import evaluate_rules_bank, evaluate_openapi

report = evaluate_rules_bank(bank_dict_or_path, official_yaml_dict_or_path)
report.totals.coverage, report.totals.fidelity
report.model_dump_json()          # the report is a Pydantic model
```

## Layout

```
src/openapi_analysis/
  config/        paths, settings, judge settings (LLM, Qdrant), logging
  rulesbank/     evaluation 1 — rule_types (definition), extraction, comparison
  openapi/       evaluation 2 — comparison, validation (layer 2),
                 alignment (the deterministic grouping of the two documents)
  judge/         layer 3 — grouping (the LLM grouper) and its fixed prompt,
                 group_parts (parts and the two views), parts (rules bank),
                 retrieval, the judge and its prompt
  schemas/       the reports and records (Pydantic)
  services/      entry points for callers (sibling repos, chat UI, CLI)
  reporting/     text rendering; final.py: the final analysis of a generated document
  api/           optional HTTP adapter (FastAPI) — not built yet
  cli.py
data/
  inputs/        official YAMLs, banks, generated YAMLs + manifest.json (versioned)
  judgements/    cached verdicts and grouper answers (versioned: a run is reproducible)
  outputs/       reports (git-ignored): reports/<Service>/{generator,rulesbank}/
                 YYYY-MM-DD_HH-MM-SS.txt|.json, one per run, never overwritten
scripts/sync_data.py   copy inputs from the sibling repos, write the manifest
docs/                  RULES, VALIDATION, JUDGE_PLAN, ALIGNMENT_PLAN, RASTREIO
```
