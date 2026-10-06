"""Render the reports as plain text for the CLI and the saved .txt files.

Rendering never computes: every count and every grouping shown is read from the
report; this module only lays it out.
"""

from __future__ import annotations

from collections import defaultdict

from openapi_analysis.schemas.openapi import LeafCounts, OpenAPIEvaluation
from openapi_analysis.schemas.rulesbank import RulesBankEvaluation

_RULE = "=" * 78
_THIN = "-" * 78


def _pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _when(iso: str) -> str:
    """'2026-09-15T22:54:58.508129-03:00' → '2026-09-15 22:54:58 -03:00' ('—' if unknown)."""
    if not iso:
        return "—"
    date, _, rest = iso.partition("T")
    clock = rest[:8]
    offset = rest[-6:] if len(rest) > 8 and rest[-6] in "+-" else ""
    return f"{date} {clock} {offset}".strip()


def _mapping_line(rule: dict) -> str:
    m = rule.get("openapi_mapping") or {}
    return (f"{rule.get('rule_type', '?'):15} {m.get('openapi_object', '')}  ·  "
            f"{m.get('openapi_field', '')}")


# ── rules bank ───────────────────────────────────────────────────────────────

_RULESBANK_LEGEND = """\
LEGEND
  expected  rules extracted from the official YAML (one per address)
  covered   … that have at least one bank rule on the same address
  coverage  covered / expected                       (is the ADDRESS there?)
  equal / diff / n/c   the value of the bank rule on a covered address is equal,
            different, or not comparable (the official YAML has no value there)
  fidelity  equal / (equal + diff)                   (is the VALUE right?)
  bank      rules in the bank = covered + dup + extra
  dup       bank rules on an address another bank rule already holds (duplicates)
  extra     bank rules on no official address"""


def render_rulesbank(ev: RulesBankEvaluation, max_items: int = 20) -> str:
    t = ev.totals
    lines = [
        _RULE, "RULES BANK × OFFICIAL YAML — rule by rule", _RULE,
        f"evaluated : {_when(ev.evaluated_at)}",
        f"official  : {ev.official.label}  (v{ev.official.version})",
        f"bank      : {ev.bank.label}",
        (f"            spec {ev.bank.version} · model {ev.bank.model or '—'} · "
         f"bank generated {_when(ev.bank.generated_at)}"),
        "",
        (f"ADDRESS   {t.covered}/{t.expected} official rules have a bank rule  "
         f"→ coverage {_pct(t.coverage)}   ({t.missing} missing)"),
        (f"VALUE     {t.value_equal} equal · {t.value_different} different · "
         f"{t.value_not_comparable} not comparable  → fidelity {_pct(t.fidelity)}"),
        (f"BANK      {t.bank_rules} rules = {t.covered} covering · {t.bank_duplicates} "
         f"duplicates · {t.bank_extra} extra   ({ev.bank_invalid_rules} with "
         f"validation_passed=False)"),
        "",
        (f"{'rule_type':16} {'expected':>8} {'covered':>8} {'coverage':>9} "
         f"{'equal':>6} {'diff':>5} {'n/c':>4}   {'bank':>5} {'dup':>4} {'extra':>6}"),
    ]
    for name, c in ev.by_rule_type.items():
        lines.append(f"{name:16} {c.expected:8} {c.covered:8} {_pct(c.coverage):>9} "
                     f"{c.value_equal:6} {c.value_different:5} {c.value_not_comparable:4}   "
                     f"{c.bank_rules:5} {c.bank_duplicates:4} {c.bank_extra:6}")
    lines += ["", _RULESBANK_LEGEND]

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
        lines += ["", (f"DUPLICATES — one official address, several bank rules "
                       f"({len(ev.shared_addresses)} addresses):")]
        for m in ev.shared_addresses[:max_items]:
            lines.append(f"  = {_mapping_line(m.expected)}")
            for b in m.bank:
                lines.append(f"      [{b.index}] {b.openapi_value[:90]}")
    if ev.extra:
        lines += ["", f"EXTRA — bank rules on no official address ({len(ev.extra)}):"]
        for x in ev.extra[:max_items]:
            r = x.rule
            lines.append(f"  + [{r.index}] {r.rule_type:15} {r.openapi_object}  ·  "
                         f"{r.openapi_field}   ({x.reason})")
    return "\n".join(lines)


# ── generated OpenAPI ────────────────────────────────────────────────────────

_OPENAPI_LEGEND = """\
LEGEND
  Every leaf (a scalar at a path) of the official YAML is looked up in the generated one:
    exact      same path, same value
    absent     the official has it, the generated does not
    differing  both have it, the values disagree
    extra      the generated has it, the official does not (listed, not scored)
  contract = what the API promises (paths, parameters, schemas, types, $ref, enum, ...)
  metadata = info, servers, externalDocs, x-* ;  prose = description, summary, title
  Operations / schemas below break the CONTRACT down by owner; "PATH /x" is what the
  path item declares itself (parameters shared by every method).
  valid OpenAPI 3.0 = the document follows the format the OpenAPI 3.0 specification
  fixes (syntax only — a valid choice can still be the wrong one). External $refs to
  other 3GPP files are not opened."""


def _leaves(c: LeafCounts) -> str:
    return f"{c.exact:3}/{c.total:<3} exact  {c.absent:3} abs {c.differing:2} diff {c.extra:3} extra"


def render_openapi(ev: OpenAPIEvaluation, max_items: int = 20) -> str:
    lines = [
        _RULE, "GENERATED OPENAPI × OFFICIAL YAML — document against document", _RULE,
        f"evaluated : {_when(ev.evaluated_at)}",
        f"official  : {ev.official.label}  (v{ev.official.version})",
        f"generated : {ev.generated.label}",
        (f"            model {ev.generated.model or '—'} · document generated "
         f"{_when(ev.generated.generated_at)}"),
        "",
        "SUMMARY",
    ]
    for label, v in (("generated", ev.validity_generated), ("official ", ev.validity_official)):
        verdict = "VALID" if v.valid else f"INVALID — {len(v.issues)} issue(s)"
        lines.append(f"  valid OpenAPI 3.0 ({label})   {verdict}")
    for name, label in (("contract", "contract"), ("metadata", "metadata"), ("prose", "prose   ")):
        s = getattr(ev, name)
        lines.append(f"  {label}  {s.exact:4}/{s.total:<4} exact ({_pct(s.ratio)})   "
                     f"{len(s.absent)} absent · {len(s.differing)} differing · "
                     f"{len(s.extra)} extra")
    clean = ev.refs_total - len(ev.refs_with_siblings)
    lines += [(f"  $ref      {clean}/{ev.refs_total} hold $ref alone (siblings of a $ref are "
               "ignored by OAS 3.0)"), "", _OPENAPI_LEGEND]

    for label, v in (("generated", ev.validity_generated), ("official", ev.validity_official)):
        if v.valid:
            continue
        lines += ["", _THIN, f"VALIDITY — the {label} document is not valid OpenAPI 3.0", _THIN,
                  f"  checks: {', '.join(v.checks_run)}  ({v.validator})"]
        for i in v.issues[:max_items]:
            lines.append(f"  x [{i.check}] {i.location}\n        {i.message}")

    # operations
    lines += ["", _THIN, "OPERATIONS", _THIN]
    for o in ev.operations:
        flag = "" if o.status == "present" else f"   [{o.status.upper()}]"
        lines.append(f"{o.operation:40} {_leaves(o.leaves)}{flag}")
        facts = [
            ("parameters missing", o.params_missing), ("parameters extra", o.params_extra),
            ("declared on the PATH, not on this operation (§3.22)", o.params_at_path_level),
            ("request body media missing", o.media_missing),
            ("request body media extra", o.media_extra),
            ("responses missing", o.responses_missing), ("responses extra", o.responses_extra),
        ]
        for label, values in facts:
            if values:
                lines.append(f"    {label}: {', '.join(values)}")

    # schemas
    lines += ["", _THIN, "SCHEMAS (components.schemas)", _THIN]
    for s in ev.schemas:
        lines.append(f"{s.name:32} {s.status.upper():10} {_leaves(s.leaves)}")
        if s.status in ("present", "misplaced") and s.shape_official != s.shape_generated:
            lines.append(f"    shape: official {s.shape_official or '—'}  |  "
                         f"generated {s.shape_generated or '—'}")
        if s.note:
            lines.append(f"    {s.note}")
    o = ev.other_leaves
    if o.total or o.extra:
        lines.append(f"{'(outside paths / schemas)':43} {_leaves(o)}")

    # details, grouped by owner (computed by the comparison, only laid out here)
    grouped: dict[str, list[str]] = defaultdict(list)
    sign = {"absent": "-", "differing": "!", "extra": "+"}
    for d in ev.details:
        line = f"{sign[d.kind]} {d.element}" + (f"   ({d.leaves} leaves)" if d.leaves > 1 else "")
        if d.kind == "differing":
            line += (f"\n        generated: {str(d.generated)[:80]}"
                     f"\n        official : {str(d.official)[:80]}")
        grouped[d.owner].append(line)
    if grouped:
        lines += ["", _THIN, "CONTRACT DETAILS by owner   (- absent  ! differing  + extra)",
                  _THIN]
        for own, items in grouped.items():
            lines.append(own)
            lines += [f"    {item}" for item in items[:max_items]]
            if len(items) > max_items:
                lines.append(f"    … {len(items) - max_items} more")
    return "\n".join(lines)
