"""Paths to the data this repo analyses. No side effects on import.

data/
  inputs/                    read-only, versioned — what every count is measured on
    manifest.json            provenance of every copied file (source, sha256, pairing)
    reference/<Service>/     the OFFICIAL OpenAPI YAMLs — the ground truth
    rulesbank/<Service>/     rules banks produced by openapi_rulesbank
    generated/<Service>/     OpenAPI documents produced by openapi_generator
  outputs/reports/<Service>/ reports written by this repo (git-ignored, regenerable),
    generator/               one report per generated OpenAPI document and run,
                             named by when it was made: YYYY-MM-DD_HH-MM-SS.txt
                             (+ .json, its data); the input is stated inside
    rulesbank/               one report per rules bank and run, the same way

Inputs are COPIED here (scripts/sync_data.py) rather than read from the sibling
repos, so a measurement is reproducible from this repo alone and a pinned count
cannot move because a file changed somewhere else.
"""

import os
from pathlib import Path

# src/openapi_analysis/config/paths.py → three levels up is the repo root.
ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = ROOT.parent

DATA_DIR = Path(os.environ.get("OPENAPI_ANALYSIS_DATA_DIR", ROOT / "data"))
INPUTS_DIR = DATA_DIR / "inputs"
MANIFEST_PATH = INPUTS_DIR / "manifest.json"
REFERENCE_DIR = INPUTS_DIR / "reference"
RULESBANK_DIR = INPUTS_DIR / "rulesbank"
GENERATED_DIR = INPUTS_DIR / "generated"
SPECS_DIR = INPUTS_DIR / "specs"          # 3GPP spec markdown each bank came from
OUTPUTS_DIR = DATA_DIR / "outputs"
REPORTS_DIR = OUTPUTS_DIR / "reports"
# The judge's verdicts, one file per part — versioned (costly to regenerate; a rerun
# with the same part, evidence, model and prompt reads them back instead of the LLM).
JUDGEMENTS_DIR = DATA_DIR / "judgements"

# Sibling repos — read ONLY by scripts/sync_data.py, never by the analysis itself.
SIBLING_RULESBANK = WORKSPACE / "openapi_rulesbank"
SIBLING_GENERATOR = WORKSPACE / "openapi_generator"


def reference_yaml(service: str, version: str) -> Path:
    """The official YAML of `service` at `version` (its info.version, e.g. '18.2.0')."""
    return REFERENCE_DIR / service / f"TS28532_{service}_v{version}.yaml"


def rulesbank_dir(service: str) -> Path:
    return RULESBANK_DIR / service


def generated_dir(service: str) -> Path:
    return GENERATED_DIR / service


def report_dir(service: str, evaluation: str) -> Path:
    """Where the reports of one service and evaluation ('generator' | 'rulesbank') go."""
    return REPORTS_DIR / service / evaluation

