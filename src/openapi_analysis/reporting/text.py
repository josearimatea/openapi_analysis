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
            covered = equal + diff + n/c
  coverage  covered / expected                       (is the ADDRESS there?)
  equal     the bank rule's value is the official value
  diff      the value is DIFFERENT from the official — not necessarily wrong: 4XX/5XX
            instead of default differs and can be better. Only the semantic review
            (layer 3) rules a difference an error or an improvement.
  n/c       not comparable: the official YAML holds no value at that address to compare
  fidelity  equal / (equal + diff)                   (is the VALUE the official one?)
  dup       bank rules on an address another bank rule already holds (duplicates)
  extra     bank rules on no official address (an invention, a wrong address, or
            something the spec asks for that the official YAML leaves out)
  bank      rules in the bank = covered + dup + extra
  ESTIMATE  fidelity applied to every covered rule — the n/c ones too: how many bank
            rules agree with the official, of the covered and of the expected (a
            missing rule counts as not there). An agreement estimate, not a
            correctness one."""


def _estimate(covered: int, equal: int, different: int, expected: int) -> list[str]:
    """Fidelity (equal over the comparable) applied to every covered rule — the not
    comparable ones too: how many covered rules agree with the official, and what that
    is of the expected rules (a missing rule counts as not there)."""
    comparable = equal + different
    if not comparable:
        return []
    fidelity = equal / comparable
    agree = round(covered * fidelity)
    return [(f"ESTIMATE  ~{agree} of the {covered} covered rules agree with the official "
             f"({_pct(fidelity).strip()}, the fidelity of the {comparable} comparable ones)"),
            (f"          = ~{_pct(agree / expected).strip() if expected else '—'} of the "
             f"{expected} official rules; the {different} diff are differences, not proven "
             "errors")]


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
        (f"BANK      {t.covered} covering + {t.bank_duplicates} duplicates + {t.bank_extra} "
         f"extra = {t.bank_rules} rules   ({ev.bank_invalid_rules} with "
         f"validation_passed=False)"),
        *_estimate(t.covered, t.value_equal, t.value_different, t.expected),
        "",
        (f"{'':16} {'':>8} {'covered = equal + diff + n/c':>28}"),
        (f"{'rule_type':16} {'expected':>8} {'covered':>8} {'coverage':>9} "
         f"{'equal':>6} {'diff':>5} {'n/c':>4}   {'dup':>4} {'extra':>6} {'bank':>5}"),
    ]
    for name, c in ev.by_rule_type.items():
        lines.append(f"{name:16} {c.expected:8} {c.covered:8} {_pct(c.coverage):>9} "
                     f"{c.value_equal:6} {c.value_different:5} {c.value_not_comparable:4}   "
                     f"{c.bank_duplicates:4} {c.bank_extra:6} {c.bank_rules:5}")
    lines += [(f"{'TOTAL':16} {t.expected:8} {t.covered:8} {_pct(t.coverage):>9} "
               f"{t.value_equal:6} {t.value_different:5} {t.value_not_comparable:4}   "
               f"{t.bank_duplicates:4} {t.bank_extra:6} {t.bank_rules:5}"),
              f"{'':16} {'':8} bank = covered + dup + extra",
              "", _RULESBANK_LEGEND]

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


# ── layer 3, the judge ───────────────────────────────────────────────────────

_JUDGE_LEGEND = """\
LEGEND
  Each part is a place where the evaluated side differs from the official document.
  The judge (an LLM) read only the evidence retrieved for that part — 3GPP spec passages
  (S1, S2, ...) and OpenAPI 3.0 reference passages (O1, O2, ...) — and answered:
    why        why the evaluated side differs
    verdict    error | improvement | equivalent | uncertain   (of the evaluated side)
    clearer    which version is easier to understand: official | generated | same
  These verdicts are the judge's reading, NOT measurements: they are reported apart
  from the agreement numbers, and are uncalibrated until reviewed by a person."""


def _yaml_block(node, indent: str) -> list[str]:
    import yaml

    if node is None:
        return [indent + "(absent)"]
    text = yaml.safe_dump(node, sort_keys=False, allow_unicode=True, width=100).rstrip()
    return [indent + line for line in text.removesuffix("\n...").splitlines()]


def _analysed(v) -> list[str]:
    """What the judge analysed: each focus location on both sides, then the exact
    differences — the official side is the document the verdict is compared with."""
    from openapi_analysis.judge.prompts import difference_line

    if not v.focus:
        return []
    lines = ["  ANALYSED (the focus; the judge also read the whole owner as context)"]
    for loc in v.focus:
        lines += [f"    at {loc}", "      OFFICIAL:",
                  *_yaml_block(v.official_focus.get(loc), "        "),
                  "      GENERATED:",
                  *_yaml_block(v.generated_focus.get(loc), "        ")]
    per = v.difference_verdicts or [""] * len(v.differences)
    reasons = {d.difference_id.strip().upper(): d.reason for d in v.answer.differences}
    lines.append("  DIFFERENCES (each with the judge's verdict)")
    for i, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
        lines.append(f"    D{i} {verdict.upper():12}" + difference_line(d).replace(
            "\n", "\n" + " " * 20))
        if reasons.get(f"D{i}"):
            lines.append(" " * 20 + "why: " + " ".join(reasons[f"D{i}"].split())[:300])
    return lines


def _judge_summary(report) -> list[str]:
    """The result first (reporting/final.py): validity, every value of the API by
    verdict, the score, then the same by region."""
    from openapi_analysis.reporting.final import (
        _official_coverage,
        _result,
        _result2,
        census,
        differences,
    )

    rows, total = census(report)
    return [*_result(report, total, differences(report)), "", *_official_coverage(report),
            "", *_result2(rows, total)]


def render_judge(report, max_text: int = 400) -> str:
    def cut(text: str) -> str:
        text = " ".join(str(text).split())
        return text if len(text) <= max_text else text[:max_text] + " …"

    usage = report.usage
    lines = [
        _RULE, f"JUDGE (layer 3) — {report.evaluation}", _RULE,
        f"evaluated : {_when(report.evaluated_at)}",
        f"input     : {report.input}",
        f"service   : {report.service}   spec: {report.spec_collection}",
        f"judge     : {report.model}   prompt {report.prompt_version}",
        (f"usage     : {usage.get('llm_calls', 0)} LLM call(s), "
         f"{usage.get('total_tokens', 0)} tokens, US$ {usage.get('cost_usd', 0)} "
         "(cached verdicts cost nothing)"),
        "",
        *_judge_summary(report),
        "",
        _JUDGE_LEGEND,
    ]
    for v in report.verdicts:
        a = v.answer
        lines += ["", _THIN, f"{v.owner} — {v.aspect}", _THIN,
                  f"  differs : {cut(v.summary)}"]
        lines += _analysed(v)
        lines += [f"  VERDICT : {a.verdict.upper()}   (clearer: {a.clearer})"
                  + ("" if v.decided_by == "llm" else f"   [{v.decided_by}]"),
                  f"  why     : {cut(a.why_different)}",
                  f"  3GPP    : {cut(a.spec_3gpp)}",
                  f"  OpenAPI : {cut(a.openapi)}",
                  f"  clearer : {cut(a.clearer_why)}"]
        by_id = {e.id: e for e in v.evidence}
        for c in a.citations:
            e = by_id.get(c.evidence_id)
            where = (f"clause {e.clause} {e.title}" if e and e.source == "spec"
                     else f"OpenAPI ref. {e.title}" if e else "?")
            lines.append(f"  cites {c.evidence_id:3} {cut(where)[:70]}\n"
                         f"            \"{cut(c.quote)[:200]}\"")
        for o in v.overrides:
            lines.append(f"  override: {o}")
        lines.append("  read    : " + ", ".join(
            f"{e.id} {e.clause or e.title[:25]}" for e in v.evidence))
    return "\n".join(lines)
