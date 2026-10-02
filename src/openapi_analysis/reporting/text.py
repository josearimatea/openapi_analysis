"""Render the reports as plain text for the CLI and the saved .txt files.

Rendering never computes: every number shown is read from the report.
"""

from __future__ import annotations

from openapi_analysis.schemas.openapi import OpenAPIEvaluation
from openapi_analysis.schemas.rulesbank import RulesBankEvaluation

_RULE = "=" * 78


def _pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _mapping_line(rule: dict) -> str:
    m = rule.get("openapi_mapping") or {}
    return f"{rule.get('rule_type', '?'):15} {m.get('openapi_object', '')}  ·  {m.get('openapi_field', '')}"


def render_rulesbank(ev: RulesBankEvaluation, max_items: int = 20) -> str:
    t = ev.totals
    lines = [
        _RULE, "RULES BANK × OFFICIAL YAML — rule by rule", _RULE,
        f"official : {ev.official.label}  (v{ev.official.version})",
        (f"bank     : {ev.bank.label}  (spec {ev.bank.version}, {ev.bank.model}, "
        f"{ev.bank.generated_at})"),
        "",
        (f"ADDRESS   {t.covered}/{t.expected} official rules have a bank rule  "
        f"→ coverage {_pct(t.coverage)}   ({t.missing} missing)"),
        (f"VALUE     {t.value_equal} equal · {t.value_different} different · "
        f"{t.value_not_comparable} not comparable  → fidelity {_pct(t.fidelity)}"),
        (f"BANK      {t.bank_rules} rules · {t.bank_extra} on no official address · "
        f"{ev.bank_invalid_rules} with validation_passed=False · "
        f"{len(ev.shared_addresses)} official addresses held by >1 rule"),
        "",
        (f"{'rule_type':16} {'expected':>8} {'covered':>8} {'coverage':>9} "
        f"{'equal':>6} {'diff':>5} {'n/c':>4} {'bank':>5} {'extra':>6}"),
    ]
    for name, c in ev.by_rule_type.items():
        lines.append(f"{name:16} {c.expected:8} {c.covered:8} {_pct(c.coverage):>9} "
                     f"{c.value_equal:6} {c.value_different:5} {c.value_not_comparable:4} "
                     f"{c.bank_rules:5} {c.bank_extra:6}")

    if ev.missing:
        lines += ["", f"MISSING — official rules with no bank rule ({len(ev.missing)}):"]
        lines += [f"  - {_mapping_line(r)}" for r in ev.missing[:max_items]]
    different = [m for m in ev.matches if m.value_status == "different"]
    if different:
        lines += ["", f"WRONG VALUE — on the right address ({len(different)}):"]
        for m in different[:max_items]:
            lines.append(f"  ! {_mapping_line(m.expected)}")
            lines.append(f"      official: {m.expected['openapi_mapping']['openapi_value'][:90]}")
            lines.append(f"      bank    : {m.bank[0].openapi_value[:90]}")
            lines.append(f"      why     : {m.note[:110]}")
    if ev.shared_addresses:
        lines += ["", (f"SHARED ADDRESS — one official rule, several bank rules "
                      f"({len(ev.shared_addresses)}):")]
        for m in ev.shared_addresses[:max_items]:
            lines.append(f"  = {_mapping_line(m.expected)}  ← bank rules "
                         f"{[b.index for b in m.bank]}")
    if ev.extra:
        lines += ["", f"EXTRA — bank rules on no official address ({len(ev.extra)}):"]
        for x in ev.extra[:max_items]:
            r = x.rule
            lines.append(f"  + [{r.index}] {r.rule_type:15} {r.openapi_object}  ·  "
                         f"{r.openapi_field}   ({x.reason})")
    return "\n".join(lines)


def render_openapi(ev: OpenAPIEvaluation, max_items: int = 20) -> str:
    labels = {
        "contract": "CONTRACT  paths, methods, schemas, types, $ref",
        "metadata": "METADATA  info, servers, externalDocs, x-* extensions",
        "prose":    "PROSE     descriptions, summaries (wording may differ)",
    }
    lines = [
        _RULE, "GENERATED OPENAPI × OFFICIAL YAML — document against document", _RULE,
        f"official  : {ev.official.label}  (v{ev.official.version})",
        f"generated : {ev.generated.label}  ({ev.generated.model}, {ev.generated.generated_at})",
        "",
    ]
    for name in ("contract", "metadata", "prose"):
        s = getattr(ev, name)
        lines.append(f"{labels[name]}\n    {s.exact}/{s.total} exact ({_pct(s.ratio)})"
                     f"  |  {len(s.absent)} absent  |  {len(s.differing)} differing"
                     f"  |  {len(s.extra)} extra")
    lines += [
        "",
        f"operations missing={ev.operations_missing or 'none'}  extra={ev.operations_extra or 'none'}",
        f"schemas    missing={ev.schemas_missing or 'none'}  extra={ev.schemas_extra or 'none'}",
        f"$ref       {ev.refs_total - len(ev.refs_with_siblings)}/{ev.refs_total} hold $ref alone",
    ]
    c = ev.contract
    if c.absent:
        lines += ["", f"contract leaves NOT generated ({len(c.absent)}):"]
        lines += [f"  - {p}" for p in c.absent[:max_items]]
    if c.differing:
        lines += ["", f"contract leaves with a WRONG value ({len(c.differing)}):"]
        for d in c.differing[:max_items]:
            lines.append(f"  ! {d.path}\n      generated: {str(d.generated)[:88]}"
                         f"\n      official : {str(d.official)[:88]}")
    if c.extra:
        lines += ["", f"contract leaves the official document does not have ({len(c.extra)}):"]
        lines += [f"  + {p}" for p in c.extra[:max_items]]
    return "\n".join(lines)
