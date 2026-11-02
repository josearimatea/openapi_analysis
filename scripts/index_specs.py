"""Index the spec versions of data/inputs the shared corpus does not hold.

The judge does this by itself when it needs one (services/judge_service._collection);
this script does it ahead of a run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from openapi_analysis.config.paths import MANIFEST_PATH, ROOT
from openapi_analysis.services.judge_service import _collection


def main() -> int:
    for entry in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["specs"]:
        print(f"ok     {entry['path']}  ->  {_collection(ROOT / entry['path'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
