"""Paths to the data this repo analyses. No side effects on import.

data/
  inputs/                    read-only, versioned — what every count is measured on
    manifest.json            provenance of every copied file (source, sha256, pairing)
    reference/<Service>/     the OFFICIAL OpenAPI YAMLs — the ground truth
    rulesbank/<Service>/     rules banks produced by openapi_rulesbank
    generated/<Service>/     OpenAPI documents produced by openapi_generator
  outputs/                   reports written by this repo (git-ignored, regenerable)
    rulesbank/<Service>/     evaluation 1 — one report per rules bank
    generator/<Service>/     evaluation 2 — one report per generated OpenAPI document

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
OUTPUTS_DIR = DATA_DIR / "outputs"
OUTPUTS_RULESBANK_DIR = OUTPUTS_DIR / "rulesbank"
OUTPUTS_GENERATOR_DIR = OUTPUTS_DIR / "generator"

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
