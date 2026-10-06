"""The final analysis of one evaluated input, short enough to read (Markdown).

Written beside the full judge report on every judge run: the result of the whole
document (lines of YAML: equal, or different and then as the judge ruled), then
every difference in one table row — where, what changed, the verdict and why. No
YAML: the full report (<input>.txt) holds the context and the evidence.
"""

from __future__ import annotations

from openapi_analysis.reporting.text import CENSUS_COLUMNS, HEADER, _when, judge_census
from openapi_analysis.schemas.judge import Difference, JudgeReport, Verdict

_MARK = {"error": "❌ error", "improvement": "⬆️ improvement", "equivalent": "✅ equivalent",
         "uncertain": "❔ uncertain"}


def _share(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def _cell(text: object, limit: int = 220) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit] + " …"


def _change(d: Difference) -> str:
    if d.kind == "absent":
        return f"missing in the generated ({d.leaves} line{'s' * (d.leaves > 1)})"
    if d.kind == "extra":
        return f"added by the generated ({d.leaves} line{'s' * (d.leaves > 1)})"
    return f"`{_cell(d.official, 80)}` → `{_cell(d.generated, 80)}`"


def _where(d: Difference, focus: list[str]) -> str:
    """The location relative to the part's focus, when it is inside it."""
    for f in sorted(focus, key=len, reverse=True):
        if d.location.startswith(f + "."):
            return "`…" + _cell(d.location[len(f):], 120) + "`"
    return f"`{_cell(d.location, 120)}`"


def _result(report: JudgeReport) -> list[str]:
    rows, total = judge_census(report)
    header = rows.pop(HEADER, None)
    t = total["total"]
    correct = total["equal"] + total["equivalent"] + total["improvement"]
    different = t - total["equal"]
    head = "| region | lines | " + " | ".join(CENSUS_COLUMNS) + " | **correct** |"
    lines = [
        "## Result",
        "",
        ("Unit: one **line of YAML** (a leaf value), counted over both documents. A line is "
         "either **equal** to the official, or **different** — and then it takes the "
         "judge's verdict on its own difference. **Correct = equal + equivalent + "
         "improvement.** Scored: the **API** (paths and components). The document header "
         "(`info`, `servers`, `tags`, `x-…`) is reported apart and **not scored**."),
        "",
        head,
        "|" + "---|" * (len(CENSUS_COLUMNS) + 3),
    ]
    for name, row in [*rows.items(), ("**total (API)**", total)]:
        ok = row["equal"] + row["equivalent"] + row["improvement"]
        lines.append(f"| {name} | {row['total']} | "
                     + " | ".join(str(row[c]) for c in CENSUS_COLUMNS)
                     + f" | **{_share(ok, row['total'])}** |")
    lines += [
        "",
        f"- **{t}** lines of API in all.",
        f"- **{total['equal']}** ({_share(total['equal'], t)}) equal to the official.",
        f"- **{different}** ({_share(different, t)}) different; of these:",
        f"  - {total['equivalent']} correct though different (equivalent)",
        f"  - {total['improvement']} better than the official (improvement)",
        f"  - {total['error']} wrong (error)",
        f"  - {total['uncertain']} undecided — the evidence did not settle them (uncertain)",
    ]
    if total["not judged"]:
        lines.append(f"  - {total['not judged']} not judged in this run (partial run)")
    lines += ["",
              (f"**Correct: {correct} of {t} lines = {_share(correct, t)}** — wrong "
               f"{_share(total['error'], t)}, undecided "
               f"{_share(total['uncertain'] + total['not judged'], t)}.")]
    if header:
        lines += ["", "### Document header — not scored", "",
                  ("`info`, `servers`, `externalDocs`, `openapi`, `tags`, `security`, `x-…`: "
                   "they describe the document, not the API."), "",
                  f"{header['total']} lines: " + ", ".join(
                      f"{c} {header[c]}" for c in CENSUS_COLUMNS if header[c]) + "."]
    if report.owners_equal:
        lines += ["", f"Entirely equal to the official ({len(report.owners_equal)} of "
                      f"{report.owners_total}): " + ", ".join(f"`{o}`" for o in
                                                            report.owners_equal) + "."]
    return lines


def _part(i: int, v: Verdict) -> list[str]:
    a = v.answer
    lines = ["", f"### {i}. `{v.owner}` — {v.aspect}  ·  {_MARK[a.verdict]}", "",
             f"{_cell(a.why_different, 600)}", ""]
    if v.focus:
        lines += ["Focus: " + ", ".join(f"`{f}`" for f in v.focus), ""]
    if v.differences:
        per = v.difference_verdicts or [a.verdict] * len(v.differences)
        reasons = {d.difference_id.strip().upper(): d.reason for d in a.differences}
        lines += ["| # | where | change | verdict | why |", "|---|---|---|---|---|"]
        for n, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
            lines.append(f"| D{n} | {_where(d, v.focus)} | {_change(d)} | "
                         f"{_MARK[verdict]} | {_cell(reasons.get(f'D{n}', ''))} |")
    lines += ["", f"Clearer: **{a.clearer}** — {_cell(a.clearer_why, 300)}"]
    if v.overrides:
        lines += ["", "Deterministic corrections: " + "; ".join(v.overrides)]
    return lines


def render_judge_final(report: JudgeReport) -> str:
    usage = report.usage
    subject = ("the generated document" if report.evaluation == "generator"
               else "the rules bank")
    lines = [
        f"# Final analysis — {report.service}: {subject} vs the official",
        "",
        f"- **Input:** `{report.input}`",
        f"- **Evaluated:** {_when(report.evaluated_at)}",
        (f"- **Judge:** {report.model}, prompt {report.prompt_version}; 3GPP spec from "
         f"`{report.spec_collection}` (scope {', '.join(report.scope) or 'all'}) and the "
         "OpenAPI 3.0 reference"),
        (f"- **Cost of this run:** {usage.get('llm_calls', 0)} LLM call(s), US$ "
         f"{usage.get('cost_usd', 0)} (cached verdicts cost nothing)"),
        ("- Verdicts are the judge's reading, not measurements, and are uncalibrated until "
         "reviewed by a person. Full context and evidence: the `.txt` report beside this "
         "file."),
        "",
        *_result(report),
        "",
        "## Differences, part by part",
        "",
        ("Each part is one aspect of an operation, schema or block; the judge read it "
         "whole (both documents) and ruled on each difference."),
    ]
    for i, v in enumerate(report.verdicts, 1):
        lines += _part(i, v)
    return "\n".join(lines) + "\n"
