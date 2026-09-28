# openapi_analysis

A versioned instrument to measure a generated **rules bank** against the
**official OpenAPI YAML**. Analysis only — this project never generates rules.

It exists because the coverage/fidelity numbers used to judge the generator were
measured ad-hoc and proved wrong more than once (a target extractor that counted
54 targets where there were more by not descending into `oneOf`/`allOf`; a ref
count taken from log lines rather than from rule fields). The measurement itself
has to be trustworthy, so it lives here, versioned and pinned by tests.

## What it measures

- **Positional coverage** — does a bank rule exist for each target of the YAML,
  matched by `(rule_type, openapi_object, openapi_field)` (and media type for
  request bodies)?
- **Value fidelity** — where measurable, does `openapi_value` match the YAML?
- **Defect catalogue** — external `$ref` gone internal, operation parameters
  addressed at path level, duplicate `(object, field)` on collection fields,
  force-included invalid rules.

## Design principle

The target enumeration **mirrors the generator's addressing contract**
(`openapi_rulesbank/utils/rules_check.py`): a target and a bank rule are addressed
identically, or they would never line up. Changing the contract on either side is
a deliberate edit reflected in both.

## Layout

```
src/openapi_analysis/
  targets.py    # enumerate the YAML's targets (recursive descent; pinned by tests)
tests/
  test_targets.py
```

## Usage

```bash
uv sync
uv run pytest
```
