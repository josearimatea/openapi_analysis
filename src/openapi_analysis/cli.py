"""Command line — calls services/, never the evaluation logic directly.

    openapi-analysis rulesbank <rules_bank.json> <official.yaml> [--json]
    openapi-analysis openapi   <generated.yaml>  <official.yaml> [--json]
    openapi-analysis extract   <official.yaml> [-o official_rules.json]
    openapi-analysis all       # every input in data/inputs → data/outputs/{rulesbank,generator}/<Service>/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openapi_analysis.reporting.text import render_openapi, render_rulesbank
from openapi_analysis.services import (
    evaluate_all_generated,
    evaluate_all_rules_banks,
    evaluate_openapi,
    evaluate_rules_bank,
    extract_official_rules,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openapi-analysis",
                                 description="Evaluate rules banks and generated OpenAPI "
                                             "documents against the official YAML.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("rulesbank", help="rules bank × official YAML, rule by rule")
    p.add_argument("rules_bank", type=Path)
    p.add_argument("official", type=Path)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("openapi", help="generated YAML × official YAML")
    p.add_argument("generated", type=Path)
    p.add_argument("official", type=Path)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("extract", help="official YAML → its rules in the rules-bank format")
    p.add_argument("official", type=Path)
    p.add_argument("-o", "--output", type=Path)

    sub.add_parser("all", help="evaluate every input in data/inputs, save to data/outputs")

    args = ap.parse_args(argv)
    for name in ("rules_bank", "generated", "official"):
        path = getattr(args, name, None)
        if path is not None and not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2

    if args.command == "rulesbank":
        report = evaluate_rules_bank(args.rules_bank, args.official)
        print(report.model_dump_json(indent=2) if args.json else render_rulesbank(report))
    elif args.command == "openapi":
        report = evaluate_openapi(args.generated, args.official)
        print(report.model_dump_json(indent=2) if args.json else render_openapi(report))
    elif args.command == "extract":
        text = json.dumps(extract_official_rules(args.official), indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
    else:
        for r in evaluate_all_rules_banks():
            t = r.totals
            print(f"rulesbank  {r.bank.label:72} coverage {t.covered:3}/{t.expected:<3} "
                  f"fidelity {t.value_equal:3}/{t.value_equal + t.value_different:<3} "
                  f"extra {t.bank_extra}")
        for r in evaluate_all_generated():
            c, v = r.contract, r.validity_generated
            valid = "valid" if v.valid else f"INVALID ({len(v.issues)})"
            print(f"openapi    {r.generated.label:72} contract {c.exact:4}/{c.total:<4} "
                  f"absent {len(c.absent)} differing {len(c.differing)}  {valid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
