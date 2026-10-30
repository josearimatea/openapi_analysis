"""The final analysis of one generated document — the result first, then the detail.

    RESULT     valid OpenAPI or not, then the two views, each on its own base:
                 1. how much of the official the generated reproduces
                 2. how much of the generated is right
               a FIELD is one line of the YAML holding a value; the document header is
               counted apart, never scored
    LISTS      improvements, errors, undecided, different but right, groupings the
               judge disputed, the header
    RESULT 1   OpenAPI validation (openapi-spec-validator): syntax and structure only
    DETAIL     part by part: each group of corresponding blocks, each leftover

Each field takes the verdict of the most specific difference holding it
(judge/group_parts.views): a field that only moved counts once, in its group — never
as missing plus extra. Saved as data/outputs/reports/<Service>/generator/
YYYY-MM-DD_HH-MM-SS.txt, one per run, never overwritten.
"""

from __future__ import annotations

import textwrap

from openapi_analysis.schemas.judge import Difference, JudgeReport, Verdict

_RULE = "=" * 100
_THIN = "-" * 100
VERDICT_NAME = {"equivalent": "different but right", "improvement": "better",
                "error": "wrong", "uncertain": "undecided"}


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


def _header(v: Verdict) -> bool:
    return v.aspect.startswith("header")


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


def correct(view: dict[str, int], side: str) -> int:
    """The fields that are right: same + different but right + better (+ extra useful
    on the generated side)."""
    keys = ["same", "different but right", "better"] + (["extra useful"]
                                                         if side == "generated" else [])
    return sum(view.get(k, 0) for k in keys)


# ── sections ─────────────────────────────────────────────────────────────────

_LINES = {
    "official": (
        ("same", "same as the official"),
        ("different but right", "different, but right  (same meaning)"),
        ("better", "better than the official"),
        ("wrong", "wrong"),
        ("missing", "missing in the generated"),
        ("undecided", "undecided"),
    ),
    "generated": (
        ("same", "same as the official"),
        ("different but right", "different, but right  (same meaning)"),
        ("better", "better than the official"),
        ("wrong", "wrong"),
        ("extra useful", "extra, useful          (not in the official)"),
        ("extra wrong", "extra, wrong           (not in the official)"),
        ("undecided", "undecided"),
    ),
}


def _view(report: JudgeReport, side: str) -> list[str]:
    view = report.views.get(side, {})
    total = sum(view.values())
    title = ("1. HOW MUCH OF THE OFFICIAL THE GENERATED REPRODUCES" if side == "official"
             else "2. HOW MUCH OF THE GENERATED IS RIGHT")
    lines = [f"  {title:60}({side}: {total} fields)"]
    for key, name in _LINES[side]:
        n = view.get(key, 0)
        lines.append(f"     {name:46}{n:>6}   {_share(n, total) if n else '':>6}")
    ok = correct(view, side)
    what = ("same + different but right + better" if side == "official"
            else "same + different but right + better + extra useful")
    label = "REPRODUCED CORRECTLY" if side == "official" else "RIGHT"
    lines += ["     " + "─" * 62,
              f"     {label}  ({what})   {_share(ok, total)}  ({ok} of {total})"]
    return lines


def result_views(report: JudgeReport) -> list[str]:
    """The result: validity, then the two views of the fields."""
    lines = ["RESULT", ""]
    vg, vo = report.validity_generated, report.validity_official
    if vg is not None:
        lines += ["  Valid OpenAPI 3.0: " + ("YES" if vg.valid else f"NO — {len(vg.issues)} issue(s)")
                  + (f"   (official: {'valid' if vo.valid else 'NOT valid'})"
                     if vo is not None else ""), ""]
    if not report.views:
        return lines
    lines += ["  A field is one line of the YAML that holds a value (e.g.",
              "  responses.204.description: No Content). The document header (info, servers,",
              "  tags...) is listed apart and not scored.", "",
              *_view(report, "official"), "", *_view(report, "generated")]
    header = report.views.get("header", {})
    if header:
        lines += ["", (f"  document header (NOT scored): {header.get('official', 0)} fields in the "
                      f"official, {header.get('generated', 0)} in the generated — listed below")]
    return lines


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


def _change(d: Difference) -> str:
    if d.kind == "differing":
        return f"{_short(d.official, 45)!r} → {_short(d.generated, 45)!r}"
    if d.kind == "moved":
        return f"moved: official at {d.official} → generated at {d.generated}"
    return "missing in the generated" if d.kind == "absent" else "added by the generated"


def _listing(title: str, items: list[tuple[Verdict, int, Difference, str, str]]) -> list[str]:
    lines = [f"{title} ({len(items)})"]
    if not items:
        return lines + ["  none"]
    for v, _, d, _, why in items:
        lines.append(f"  • {v.owner} · {d.official_location if d.kind == 'absent' else d.location}")
        lines += _wrap(f"{_change(d)}. {why}", "      ")
    return lines


def _disputed(report: JudgeReport) -> list[str]:
    items = [v for v in report.verdicts if v.answer.grouping_wrong]
    lines = [(f"GROUPINGS THE JUDGE DISPUTED — blocks put together that do not correspond "
             f"({len(items)})")]
    if not items:
        return lines + ["  none"]
    for v in items:
        lines.append(f"  • {v.owner} — {v.aspect}")
        lines += _wrap(v.answer.why_different, "      ")
    return lines


def _part(i: int, v: Verdict) -> list[str]:
    lines = ["", _THIN, (f"{i}. {v.owner} — {v.aspect}   "
                        f"[{VERDICT_NAME.get(v.answer.verdict, v.answer.verdict).upper()}]"),
             _THIN]
    lines += _wrap(v.summary, "  ")
    lines += _wrap(v.answer.why_different, "  ")
    per = v.difference_verdicts or [v.answer.verdict] * len(v.differences)
    why = {d.difference_id.strip().upper(): d.reason for d in v.answer.differences}
    for n, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
        mark = {"absent": "-", "extra": "+", "differing": "~", "moved": ">"}[d.kind]
        where = d.official_location if d.kind == "absent" else d.location
        lines.append(f"  D{n} {VERDICT_NAME.get(verdict, verdict).upper():20}{mark} {where}")
        if d.kind in ("differing", "moved"):
            lines.append(f"{'':27}official : {_short(d.official, 68)}")
            lines.append(f"{'':27}generated: {_short(d.generated, 68)}")
        if why.get(f"D{n}"):
            lines += _wrap(why[f"D{n}"], " " * 27)
    lines += _wrap(f"clearer: {v.answer.clearer} — {v.answer.clearer_why}", "  ")
    return lines


def render_final(report: JudgeReport) -> str:
    diffs = differences(report)
    api = [x for x in diffs if not _header(x[0])]
    usage = report.usage
    g = report.grouping
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
        *(textwrap.wrap(f"grouping  : blocks of both documents put together {g.get('address', 0)} "
                        f"by the same address, {g.get('key', 0)} by the same OpenAPI identity "
                        f"elsewhere, {g.get('llm', 0)} by the LLM grouper; "
                        f"{g.get('leftover', 0)} left in one document only", width=100,
                        subsequent_indent=" " * 12) if g else []),
        (f"cost      : {usage.get('llm_calls', 0)} LLM call(s), US$ {usage.get('cost_usd', 0)}"
         " this run (cached answers cost nothing)"),
        "",
        _RULE, *result_views(report), "",
        _RULE, *_listing("IMPROVEMENTS — the generated is better than the official",
                         [x for x in api if x[3] == "improvement"]), "",
        _RULE, *_step2(report), "",
        _RULE,
        *_listing("ERRORS — wrong, or missing in the generated",
                  [x for x in api if x[3] == "error"]), "",
        *_listing("UNDECIDED — the evidence did not decide",
                  [x for x in api if x[3] == "uncertain"]), "",
        *_listing("DIFFERENT, BUT RIGHT — written another way, same meaning",
                  [x for x in api if x[3] == "equivalent"]), "",
        *_disputed(report), "",
        *_listing("DOCUMENT HEADER — not scored", [x for x in diffs if _header(x[0])]), "",
        _RULE,
        ("DETAIL, PART BY PART  (a part: a group of corresponding blocks, or a block in one "
         "document only;"),
        ("                       D1, D2 …: its differences, each with its verdict.  - missing "
         "in the"),
        "                       generated, + added by the generated, ~ changed, > moved)",
    ]
    for i, v in enumerate(report.verdicts, 1):
        lines += _part(i, v)
    lines += ["", ("Verdicts are the judge's reading, uncalibrated until reviewed by a person. "
                   "The full report (.txt) holds each part's YAML and the evidence read.")]
    return "\n".join(lines) + "\n"
