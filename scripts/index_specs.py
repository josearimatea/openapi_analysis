"""Index the specs the judge reads, once per version (layer 3; needs the [judge] extra).

    uv run python scripts/index_specs.py            # index what is not indexed yet
    uv run python scripts/index_specs.py --force    # rebuild every collection

Reads the specs listed in data/inputs/manifest.json ("specs"), keeps those whose
version is in judge_settings.JUDGE_SPEC_CODES, and indexes each into its own fixed
collection (analysis_spec_<spec>_<code>) — NORMATIVE TEXT ONLY: the contents listing
and every annex are cut first (judge/spec_index.py; docs/JUDGE_PLAN.md §4.1).
Qdrant must be running (judge_settings.QDRANT_HOST/PORT).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from openapi_analysis.config import judge_settings as s
from openapi_analysis.config.paths import MANIFEST_PATH, ROOT
from openapi_analysis.judge.spec_index import index_spec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="drop and rebuild each collection")
    args = ap.parse_args(argv)

    specs = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["specs"]
    for entry in specs:
        if entry["code"] not in s.JUDGE_SPEC_CODES:
            print(f"skip   {entry['path']}  (version {entry['code']} not judged)")
            continue
        collection, chunks = index_spec(ROOT / entry["path"], entry["spec"], entry["code"],
                                        force=args.force)
        print(f"ok     {entry['path']}  ->  {collection}  ({chunks} chunks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
