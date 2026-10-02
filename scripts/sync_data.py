"""Copy the data this repo analyses from the sibling repos into data/.

    uv run python scripts/sync_data.py            # copy + (re)write data/manifest.json
    uv run python scripts/sync_data.py --check    # only report what would change

What is copied, and why it is copied rather than read in place: a pinned count must
not move because a file changed in another repo. Every copied file is recorded in
data/manifest.json with its source path and sha256, so any number reported here can
be traced to the exact bytes it was measured on.

  reference/  every distinct official YAML found in the siblings, deduplicated by
              CONTENT (the same YAML sits in both repos under different names) and
              renamed by service + info.version, which is unambiguous where the
              sibling filenames are not (rel18_… vs TS28532_… vs rel_18_…).
  rulesbank/  the curated banks in RULES_BANKS below — the latest per spec version,
              plus every bank a copied generated document was built from.
  generated/  the curated documents in GENERATED below; each one's source bank is
              read from its own x-ai-generation header, never guessed from names.

To track a new run: add it to RULES_BANKS / GENERATED and re-run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from openapi_analysis.config.paths import (
    GENERATED_DIR,
    MANIFEST_PATH,
    ROOT,
    RULESBANK_DIR,
    SIBLING_GENERATOR,
    SIBLING_RULESBANK,
    WORKSPACE,
    reference_yaml,
)
from openapi_analysis.config.settings import SERVICES, SPEC_VERSIONS

REFERENCE_SOURCES = [
    SIBLING_RULESBANK / "data/inputs/yamls",
    SIBLING_GENERATOR / "data/inputs/legacy",
]

_BANKS = SIBLING_RULESBANK / "data/outputs/rules_bank"
RULES_BANKS = {
    "ProvMnS": [
        _BANKS / "ProvMnS/Final_rules/rules_bank_28532-i20_full_20260915_214107.json",
        _BANKS / "ProvMnS/Final_rules/rules_bank_28532-i00_full_20260828_210819.json",
    ],
    "PerfMnS": [
        _BANKS / "PerfMnS/Final_rules/rules_bank_28532-i20_full_20260915_232343.json",
        _BANKS / "PerfMnS/Final_rules/rules_bank_28532-i00_full_20260926_182802.json",
        _BANKS / "PerfMnS/Final_rules/rules_bank_28532-i00_full_20260818_214526.json",
    ],
}

_GEN = SIBLING_GENERATOR / "data/outputs/test_pipeline"
GENERATED = {
    "ProvMnS": [
        _GEN / "provmns_20260920_194130.yaml",
        _GEN / "ProvMnS/provmns_20260828_232853.yaml",
    ],
    "PerfMnS": [
        _GEN / "PerfMnS/perfmns_20260823_031421.yaml",
    ],
}

_BANK_SPEC = re.compile(r"rules_bank_28532-(i\d\d)_")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    """Path relative to the workspace (sources) or to this repo (copies)."""
    for base in (ROOT, WORKSPACE):
        try:
            return str(path.resolve().relative_to(base))
        except ValueError:
            continue
    return str(path)


def service_of(filename: str) -> str:
    for svc in SERVICES:
        if svc in filename:
            return svc
    raise ValueError(f"cannot tell the service of {filename}")


def collect_references() -> list[dict]:
    """Every distinct official YAML, deduplicated by content hash."""
    by_hash: dict[str, dict] = {}
    for src_dir in REFERENCE_SOURCES:
        for src in sorted(src_dir.rglob("*.yaml")):
            digest = sha256(src)
            if digest in by_hash:
                by_hash[digest]["also_at"].append(rel(src))
                continue
            doc = yaml.safe_load(src.read_text(encoding="utf-8"))
            svc = service_of(src.name)
            version = str(doc["info"]["version"])
            by_hash[digest] = {
                "service": svc, "version": version, "sha256": digest,
                "path": rel(reference_yaml(svc, version)),
                "source": rel(src), "also_at": [], "_src": src,
            }
    # same service+version with DIFFERENT bytes (e.g. a trailing newline): keep the
    # first, record the other, and make the collision visible rather than silent
    by_target: dict[str, dict] = {}
    for entry in by_hash.values():
        kept = by_target.get(entry["path"])
        if kept is None:
            by_target[entry["path"]] = entry
            continue
        same = (yaml.safe_load(kept["_src"].read_text(encoding="utf-8"))
                == yaml.safe_load(entry["_src"].read_text(encoding="utf-8")))
        kept.setdefault("variants", []).append(
            {"source": entry["source"], "sha256": entry["sha256"],
             "same_parsed_content": same})
        if not same:
            print(f"WARNING: {entry['source']} differs in CONTENT from {kept['source']} "
                  f"(both {entry['service']} v{entry['version']})", file=sys.stderr)
    return sorted(by_target.values(), key=lambda e: (e["service"], e["version"]))


def collect_banks() -> list[dict]:
    out = []
    for svc, srcs in RULES_BANKS.items():
        for src in srcs:
            meta = json.loads(src.read_text(encoding="utf-8")).get("metadata", {})
            code = _BANK_SPEC.search(src.name).group(1)
            out.append({
                "service": svc, "path": rel(RULESBANK_DIR / svc / src.name),
                "source": rel(src), "sha256": sha256(src),
                "spec": code, "spec_version": SPEC_VERSIONS.get(code),
                "generated_at": meta.get("generated_at"), "model": meta.get("model"),
                "total_rules": meta.get("total_rules"), "_src": src,
            })
    return out


def collect_generated(banks: list[dict]) -> list[dict]:
    bank_by_time = {b["generated_at"]: b for b in banks}
    out = []
    for svc, srcs in GENERATED.items():
        for src in srcs:
            doc = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
            gen = doc.get("x-ai-generation") or (doc.get("info") or {}).get(
                "x-openapi-generator") or {}
            rb = gen.get("rules-bank") or {}
            bank = bank_by_time.get(rb.get("generated-at"))
            if bank is None:
                raise SystemExit(
                    f"{src.name}: its source bank (generated-at {rb.get('generated-at')}) "
                    "is not in RULES_BANKS — add it there so the pair travels together")
            out.append({
                "service": svc, "path": rel(GENERATED_DIR / svc / src.name),
                "source": rel(src), "sha256": sha256(src),
                "generated_at": gen.get("generated-at"), "model": gen.get("model"),
                "rules_bank": bank["path"], "_src": src,
            })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="report only, copy nothing")
    args = ap.parse_args(argv)

    refs = collect_references()
    banks = collect_banks()
    gens = collect_generated(banks)

    changed = 0
    for entry in refs + banks + gens:
        dst = ROOT / entry["path"]
        if dst.exists() and sha256(dst) == entry["sha256"]:
            continue
        changed += 1
        print(f"{'would copy' if args.check else 'copy'}  {entry['source']}  ->  {entry['path']}")
        if not args.check:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["_src"], dst)

    manifest = {
        "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference": refs, "rulesbank": banks, "generated": gens,
    }
    for section in ("reference", "rulesbank", "generated"):
        for entry in manifest[section]:
            entry.pop("_src", None)
    if not args.check:
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    print(f"{changed} file(s) {'to copy' if args.check else 'copied'}; "
          f"{len(refs)} reference, {len(banks)} banks, {len(gens)} generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
