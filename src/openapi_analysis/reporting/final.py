"""The final analysis of one generated document — the result first, then the detail.

    RESULT     everything at once: valid OpenAPI or not, every value of the API —
               equal, or changed / missing / extra with the judge's verdicts — and the
               score (correct = equal + equivalent + improvement), improvements apart
    COVERAGE   the same from the official's side: of the official's values, how many the
               generated reproduces correctly (equal, or another way judged equivalent /
               improvement), how many wrong (changed / missing), how many undecided
    RESULT 1   OpenAPI validation (openapi-spec-validator): syntax and structure only
    RESULT 2   value by value, by region: the deterministic agreement with the official,
               and the semantic review — an LLM judge that read each part whole and
               ruled on each difference, citing the 3GPP spec and the OpenAPI reference
    LISTS      improvements, errors, uncertain, equivalent, the header
    DETAIL     part by part

The unit is the VALUE: one field holding a final value (info.title,
...responses.200.description), counted over both documents. The score covers the API
(endpoints, data types, other components); the document header is apart, not scored.
Saved as data/outputs/reports/<Service>/generator/YYYY-MM-DD_HH-MM-SS.txt, one per
run, never overwritten.
"""

from __future__ import annotations

import textwrap

from openapi_analysis.schemas.judge import Difference, JudgeReport, Verdict

_RULE = "=" * 100
_THIN = "-" * 100
HEADER = "document header"
REGION_HELP = {
    "endpoints": "paths: each operation (method + path) — parameters, request body, "
                 "responses, callbacks",
    "data types": "components.schemas: the data models the endpoints send and receive",
    "other components": "the rest of components, and blocks put outside their place",
    "document header": "info, servers, externalDocs, openapi, tags, security, x-*: about "
                       "the document, not the API — NOT scored",
}
VERDICTS = ("equivalent", "improvement", "error", "uncertain")


def _share(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def _when(iso: str) -> str:
    from openapi_analysis.reporting.text import _when as when

    return when(iso)


def _short(value: object, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _wrap(text: str, indent: str, width: int = 100) -> list[str]:
    return textwrap.wrap(" ".join(str(text).split()), width=width, initial_indent=indent,
                         subsequent_indent=indent) or [indent]


# ── counting ─────────────────────────────────────────────────────────────────

def differences(report: JudgeReport) -> list[tuple[Verdict, int, Difference, str, str]]:
    """Every judged difference: (verdict of its part, n, difference, its verdict, why)."""
    out = []
    for v in report.verdicts:
        per = v.difference_verdicts or [v.answer.verdict] * len(v.differences)
        why = {d.difference_id.strip().upper(): d.reason for d in v.answer.differences}
        for n, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
            out.append((v, n, d, verdict, why.get(f"D{n}", "")))
    return out


def census(report: JudgeReport) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """(rows by region, total of the API) in values: the agreement counts of step 1 and,
    for the values that differ, the verdict of their own difference (step 3)."""
    from openapi_analysis.judge.parts import region

    rows: dict[str, dict[str, int]] = {}
    for r, counts in report.leaves.items():
        rows[r] = dict(counts) | dict.fromkeys(VERDICTS, 0)
    for v, _, d, verdict, _ in differences(report):
        rows.setdefault(region(v.owner), dict.fromkeys(VERDICTS, 0) | {"total": 0})
        rows[region(v.owner)][verdict] += d.leaves
    for row in rows.values():
        row.setdefault("equal", 0)
        row["not judged"] = row["total"] - row["equal"] - sum(row[c] for c in VERDICTS)
        row["correct"] = row["equal"] + row["equivalent"] + row["improvement"]
    keys = {k for row in rows.values() for k in row}
    total = {k: sum(row.get(k, 0) for r, row in rows.items() if r != HEADER) for k in keys}
    return {r: row for r, row in rows.items() if row["total"]}, total


# ── sections ─────────────────────────────────────────────────────────────────

def _step2(report: JudgeReport) -> list[str]:
    vg, vo = report.validity_generated, report.validity_official
    if vg is None:
        return []
    lines = [(f"RESULT 1 — OPENAPI VALIDATION  ({vg.validator or 'openapi-spec-validator'}; "
             "syntax and structure of OpenAPI 3.0 only)"), ""]
    for name, v in (("generated", vg), ("official", vo)):
        if v is None:
            continue
        lines.append(f"  {name:10} {'VALID' if v.valid else 'NOT VALID'}"
                     + (f" — {len(v.issues)} issue(s)" if v.issues else ""))
        for i in v.issues[:12]:
            lines += _wrap(f"{i.location}: {i.message}", "      - ")
        if len(v.issues) > 12:
            lines.append(f"      … and {len(v.issues) - 12} more (full report: .txt)")
    return lines


def _listing(title: str, items: list[tuple[Verdict, int, Difference, str, str]]) -> list[str]:
    lines = [f"{title} ({len(items)})"]
    if not items:
        return lines + ["  none"]
    for v, n, d, _, why in items:
        change = (f"{_short(d.official, 45)!r} → {_short(d.generated, 45)!r}"
                  if d.kind == "differing" else
                  "missing in the generated" if d.kind == "absent" else "added by the generated")
        lines.append(f"  • {v.owner} · {d.location}")
        lines += _wrap(f"{change}. {why}", "      ")
    return lines


def _part(i: int, v: Verdict) -> list[str]:
    lines = ["", _THIN, f"{i}. {v.owner} — {v.aspect}   [{v.answer.verdict.upper()}]", _THIN]
    lines += _wrap(v.answer.why_different, "  ")
    per = v.difference_verdicts or [v.answer.verdict] * len(v.differences)
    why = {d.difference_id.strip().upper(): d.reason for d in v.answer.differences}
    for n, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
        mark = {"absent": "-", "extra": "+", "differing": "~"}[d.kind]
        lines.append(f"  D{n} {verdict.upper():12}{mark} {d.location}")
        if d.kind == "differing":
            lines.append(f"{'':19}official : {_short(d.official, 76)}")
            lines.append(f"{'':19}generated: {_short(d.generated, 76)}")
        if why.get(f"D{n}"):
            lines += _wrap(why[f"D{n}"], " " * 19)
    lines += _wrap(f"clearer: {v.answer.clearer} — {v.answer.clearer_why}", "  ")
    return lines


_NATURE = (("differing", "changed  (in both, another value)"),
           ("absent", "missing  (only in the official)"),
           ("extra", "extra    (only in the generated)"))


def _result(report: JudgeReport, total: dict[str, int],
            diffs: list[tuple[Verdict, int, Difference, str, str]]) -> list[str]:
    """The result of everything, first: validity, then every value of the API — equal,
    or changed / missing / extra, each with the judge's verdicts — and the score."""
    from openapi_analysis.judge.parts import region

    api = [x for x in diffs if region(x[0].owner) != HEADER]
    t = total.get("total", 0)
    w = 12
    lines = ["RESULT", ""]
    vg, vo = report.validity_generated, report.validity_official
    if vg is not None:
        lines.append("  Valid OpenAPI 3.0 (result 1): "
                     + ("YES" if vg.valid else f"NO — {len(vg.issues)} issue(s)")
                     + (f"   (official: {'valid' if vo.valid else 'NOT valid'})"
                        if vo is not None else ""))
        lines.append("")
    lines += [f"  The API (result 2): {t} values  (a value = one field with a final value,",
              "  counted over both documents; the document header is apart, not scored)", "",
              f"  {'':36}{'values':>{w}}" + "".join(f"{v:>{w}}" for v in VERDICTS),
              (f"  {'equal to the official':36}{total.get('equal', 0):>{w}}"
              f"{'—':>{w}}{'—':>{w}}{'—':>{w}}{'—':>{w}}")]
    sums = dict.fromkeys(VERDICTS, 0)
    for kind, label in _NATURE:
        sel = [x for x in api if x[2].kind == kind]
        per = {v: sum(x[2].leaves for x in sel if x[3] == v) for v in VERDICTS}
        for v in VERDICTS:
            sums[v] += per[v]
        lines.append(f"  {label:36}{sum(per.values()):>{w}}"
                     + "".join(f"{per[v]:>{w}}" for v in VERDICTS))
    lines += [f"  {'':36}" + "-" * (w * 5),
              f"  {'TOTAL':36}{t:>{w}}" + "".join(f"{sums[v]:>{w}}" for v in VERDICTS), ""]
    correct = total.get("correct", 0)
    undecided = total.get("uncertain", 0) + total.get("not judged", 0)
    decided = t - undecided
    n_impr = sum(1 for x in api if x[3] == "improvement")
    lines += [(f"  CORRECT      {_share(correct, t):>6}   equal + equivalent + improvement "
              f"({correct} of {t} values; {_share(correct, decided)} of those decided)"),
              (f"  ERROR        {_share(total.get('error', 0), t):>6}   ({total.get('error', 0)} "
              "values)"),
              (f"  UNDECIDED    {_share(undecided, t):>6}   ({undecided} values: the evidence "
              "did not settle them)"),
              (f"  IMPROVEMENTS {n_impr:>6}   differences where the generated is better than the "
              f"official ({sums['improvement']} values) — listed below")]
    if total.get("not judged"):
        lines.append(f"  not judged   {total['not judged']:>6}   values (partial run)")
    return lines


def _official_coverage(report: JudgeReport) -> list[str]:
    """How much of the OFFICIAL document the generated one reproduces correctly: the
    base is the official's values only (the generated side's extras are not in it)."""
    view = {r: c for r, c in report.official_view.items() if c.get("official")}
    if not view:
        return []
    cols = ("official", "equal", "accepted", "wrong_changed", "wrong_missing", "uncertain",
            "not_judged")
    names = ("official", "equal", "accepted", "wrong:chg", "wrong:miss", "uncertain",
             "not judged")
    w = 11
    api = {r: c for r, c in view.items() if r != HEADER}
    total = {k: sum(c.get(k, 0) for c in api.values()) for k in cols}

    def line(name: str, c: dict[str, int]) -> str:
        ok = c.get("equal", 0) + c.get("accepted", 0)
        return (f"  {name:18}" + "".join(f"{c.get(k, 0):>{w}}" for k in cols)
                + f"{_share(ok, c.get('official', 0)):>{w}}")

    t = total["official"]
    ok = total["equal"] + total["accepted"]
    wrong = total["wrong_changed"] + total["wrong_missing"]
    lines = ["COVERAGE OF THE OFFICIAL — how much of the official document the generated one",
             "reproduces correctly (the base is the official's values only; the generated",
             "side's extras are not in it)", "",
             (f"  COVERED CORRECTLY  {_share(ok, t):>6}   {ok} of the official's {t} API values: "
              f"{total['equal']} equal + {total['accepted']} reproduced another way "
              "(equivalent / improvement)"),
             (f"  WRONG              {_share(wrong, t):>6}   {total['wrong_changed']} changed "
              f"to a wrong value + {total['wrong_missing']} missing"),
             (f"  UNDECIDED          {_share(total['uncertain'] + total['not_judged'], t):>6}"
              f"   {total['uncertain']} uncertain"
              + (f" + {total['not_judged']} not judged" if total["not_judged"] else "")),
             "", f"  {'region':18}" + "".join(f"{n:>{w}}" for n in names) + f"{'COVERED':>{w}}"]
    lines += [line(r, c) for r, c in api.items()]
    lines += ["  " + "-" * (18 + w * 8), line("TOTAL (API)", total)]
    if HEADER in view:
        lines.append(line("document header", view[HEADER]) + "   (NOT scored)")
    lines += ["  accepted: the generated changed or left it out, and the judge ruled that",
              "  equivalent or better (e.g. default covered by 4XX/5XX).",
              "  wrong:chg = present with a wrong value; wrong:miss = missing."]
    return lines


def _result2(rows: dict[str, dict[str, int]], total: dict[str, int]) -> list[str]:
    """Result 2 by region: the deterministic agreement and the judge's verdicts."""
    cols = ("total", "equal", "changed", "only_official", "only_generated", *VERDICTS)
    names = ("values", "equal", "changed", "missing", "extra", "equival.", "improv.",
             "error", "uncertain")
    w = 9
    lines = ["RESULT 2 — VALUE BY VALUE, BY REGION",
             "  deterministic: equal / changed / missing / extra, against the official;",
             "  semantic: an LLM judge read each part whole and ruled on each difference,",
             "  citing the 3GPP spec and the OpenAPI 3.0 reference.", "",
             f"  {'region':18}" + "".join(f"{n:>{w}}" for n in names) + f"{'CORRECT':>{w}}"]

    def line(name: str, row: dict[str, int]) -> str:
        return (f"  {name:18}" + "".join(f"{row.get(c, 0):>{w}}" for c in cols)
                + f"{_share(row.get('correct', 0), row.get('total', 0)):>{w}}")

    lines += [line(r, row) for r, row in rows.items() if r != HEADER]
    lines += ["  " + "-" * (18 + w * 10), line("TOTAL (API)", total)]
    if HEADER in rows:
        lines += ["", line("document header", rows[HEADER]) + "   (NOT scored)"]
    lines += ["", "  Regions:"] + [f"    {r:18}{text}" for r, text in REGION_HELP.items()]
    return lines


def render_final(report: JudgeReport) -> str:
    from openapi_analysis.judge.parts import region

    rows, total = census(report)
    diffs = differences(report)
    api = [x for x in diffs if region(x[0].owner) != HEADER]
    usage = report.usage
    lines = [
        _RULE,
        f"FINAL ANALYSIS — {report.service}: the generated document against the official one",
        _RULE,
        f"generated : {report.input}",
        *([f"official  : {report.official.label}  (v{report.official.version})"]
          if report.official else []),
        f"evaluated : {_when(report.evaluated_at)}",
        (f"judge     : {report.model}, prompt {report.prompt_version}; 3GPP spec "
         f"{report.spec_collection} (clauses {', '.join(report.scope) or 'all'}) + OpenAPI "
         "3.0 reference"),
        (f"cost      : {usage.get('llm_calls', 0)} LLM call(s), US$ {usage.get('cost_usd', 0)}"
         " this run (cached verdicts cost nothing)"),
        "",
        _RULE, *_result(report, total, diffs), "",
        *([_RULE, *_official_coverage(report), ""] if report.official_view else []),
        _RULE, *_listing("IMPROVEMENTS — the generated is better than the official",
                         [x for x in api if x[3] == "improvement"]), "",
        _RULE, *_step2(report), "",
        _RULE, *_result2(rows, total), "",
        _RULE,
        *_listing("ERRORS", [x for x in api if x[3] == "error"]), "",
        *_listing("UNCERTAIN — the evidence did not decide",
                  [x for x in api if x[3] == "uncertain"]), "",
        *_listing("EQUIVALENT — different, same meaning",
                  [x for x in api if x[3] == "equivalent"]), "",
        *_listing("DOCUMENT HEADER — not scored", [x for x in diffs
                                                   if region(x[0].owner) == HEADER]), "",
        _RULE,
        ("DETAIL, PART BY PART  (each part: one aspect of an operation, data type or block, "
        "judged whole;"),
        ("                       D1, D2 …: its differences, each with its verdict.  - missing "
        "in the"),
        "                       generated, + added by the generated, ~ changed)",
    ]
    for i, v in enumerate(report.verdicts, 1):
        lines += _part(i, v)
    lines += ["", ("Verdicts are the judge's reading, uncalibrated until reviewed by a person. "
                   "The full report (.txt) holds each part's YAML and the evidence read.")]
    return "\n".join(lines) + "\n"
