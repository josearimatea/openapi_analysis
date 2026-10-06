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
| **openapi** | the YAML from `openapi_generator` | the official YAML itself | document against document, leaves split into contract / metadata / prose, broken down per operation and schema; plus **validity**: is each document valid OpenAPI 3.0 (`openapi-spec-validator`)? |

Both measure **agreement** with the official YAML, deterministically. Agreement is
not correctness: where they diverge, which side is right (or which is an
improvement) needs reading the OpenAPI reference and the 3GPP spec — the planned
LLM judge (layer 3), reported apart from these numbers.

What a rule is, and every counting decision, is in [docs/RULES.md](docs/RULES.md).
What the validity check verifies — and what it does not — is in
[docs/VALIDATION.md](docs/VALIDATION.md). The history of the decisions is in
[docs/RASTREIO.md](docs/RASTREIO.md).

## Usage

```bash
uv sync
uv run pytest                                      # 61 tests, results pinned

uv run openapi-analysis all                        # every input → data/outputs/{rulesbank,generator}/<Service>/
uv run openapi-analysis rulesbank <bank.json> <official.yaml> [--json]
uv run openapi-analysis openapi   <generated.yaml> <official.yaml> [--json]
uv run openapi-analysis extract   <official.yaml> [-o official_rules.json]
```

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
  config/        paths, settings, logging
  rulesbank/     evaluation 1 — rule_types (definition), extraction, comparison
  openapi/       evaluation 2 — comparison
  schemas/       the reports (Pydantic)
  services/      entry points for callers (sibling repos, chat UI, CLI)
  reporting/     text rendering
  api/           optional HTTP adapter (FastAPI) — not built yet
  cli.py
data/
  inputs/        official YAMLs, banks, generated YAMLs + manifest.json (versioned)
  outputs/       reports (git-ignored): rulesbank/<Service>/ and generator/<Service>/
scripts/sync_data.py   copy inputs from the sibling repos, write the manifest
docs/RULES.md          the rule definition and its decisions
```
