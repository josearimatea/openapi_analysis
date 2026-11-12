"""The final analysis of one generated document — the result first, then the detail.

    RESULT     valid OpenAPI or not, then the two views, each on its own base:
                 1. how much of the official the generated reproduces
                 2. how much of the generated is right
               a FIELD is one line of the YAML holding a value; the document header and
               the text only the official has are counted apart, never scored
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

import re
import textwrap
from collections import Counter

from openapi_analysis.judge.parts import is_prose
from openapi_analysis.schemas.judge import Difference, JudgeReport, Verdict

_RULE = "=" * 100
_THIN = "-" * 100
VERDICT_NAME = {"equivalent": "different but right", "improvement": "better",
                "useful": "extra, useful", "error": "wrong", "uncertain": "undecided"}


def _share(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "—"


def _when(iso: str) -> str:
    from openapi_analysis.reporting.text import _when as when

    return when(iso)


def _flat(value: object) -> str:
    return " ".join(str(value).split())


def _wrap(text: str, indent: str, width: int = 100) -> list[str]:
    return textwrap.wrap(" ".join(str(text).split()), width=width, initial_indent=indent,
                         subsequent_indent=indent) or [indent]


def _header(v: Verdict) -> bool:
    return v.aspect.startswith("header")


def _text_only_in_official(d: Difference, verdict: str) -> bool:
    return d.kind == "absent" and verdict == "equivalent" and is_prose(d.location)


# when a rule of the instrument decides a difference, its text replaces the judge's: what the
# judge wrote may argue for the verdict it gave (kept in the .json)
_RULE_TEXT = {
    "same_content": "The content is identical; only its place differs (rule of the instrument).",
    "callback_to_path": ("The official declares this request as a callback, sent to an address "
                         "given at runtime; the generated declares it as a path, on its own "
                         "server (rule of the instrument)."),
    "empty_schema": ("The generated schema is {}, which places no restriction on the value (rule "
                     "of the instrument)."),
    "beside_ref": ("A key beside a $ref: OpenAPI (Reference Object) says it SHALL be ignored, so "
                   "it does not change the contract, and it is not allowed by that rule (rule of "
                   "the instrument)."),
    "operationId": ("OpenAPI makes operationId optional, so nothing calls for it: useful, not an "
                    "improvement (rule of the instrument)."),
    "prose only": "Prose is not part of the contract and never counts (rule of the instrument).",
    "second declaration": "A second declaration of the same object (rule of the instrument).",
    "not valid": "Inside a location that is not valid OpenAPI 3.0 (rule of the instrument).",
}


def _reasons(v: Verdict) -> dict[str, str]:
    """D1, D2 ... -> the reason to show: the judge's, or the rule's when a rule decided."""
    out = {d.difference_id.strip().upper(): d.reason for d in v.answer.differences}
    for note in v.overrides:
        tag, _, rest = note.partition(" ")
        text = next((t for key, t in _RULE_TEXT.items() if key in rest), None)
        if text and "->" in rest:
            out[tag] = text
    for n, d in enumerate(v.differences, 1):      # decided by a rule even when the judge agreed
        if d.known:
            out[f"D{n}"] = _RULE_TEXT[d.known]
    return out


# ── counting ─────────────────────────────────────────────────────────────────

def differences(report: JudgeReport) -> list[tuple[Verdict, int, Difference, str, str]]:
    """Every judged difference: (verdict of its part, n, difference, its verdict, why)."""
    out = []
    for v in report.verdicts:
        per = v.difference_verdicts or [v.answer.verdict] * len(v.differences)
        why = _reasons(v)
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
        ("extra discardable", "extra, discardable     (the user's choice)"),
        ("undecided", "undecided"),
    ),
}
# rows shown only where they can occur: a rules bank's default AND 4XX + 5XX (A.7)
_RULES_ONLY = {"extra discardable"}


def _view(report: JudgeReport, side: str, unit: str = "fields",
          evaluated: str = "generated") -> list[str]:
    view = report.views.get(side, {})
    total = sum(view.values())
    title = (f"1. HOW MUCH OF THE OFFICIAL THE {evaluated.upper()} REPRODUCES"
             if side == "official" else f"2. HOW MUCH OF THE {evaluated.upper()} IS RIGHT")
    base = "official" if side == "official" else evaluated
    lines = [f"  {title:60}({base}: {total} {unit})"]
    for key, name in _LINES[side]:
        if key in _RULES_ONLY and unit != "rules":
            continue
        name = name.replace("generated", evaluated)
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
              *_view(report, "official")]
    text = report.views.get("text", {}).get("official", 0)
    if text:
        lines.append(f"     text only in the official  (NOT scored, listed below){text:>9}")
    lines += ["", *_view(report, "generated")]
    duplicates = report.views.get("duplicates", {}).get("generated", 0)
    if duplicates:
        lines.append(f"     of the extra, wrong: {duplicates} fields are in duplicate declarations")
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
        for i in v.issues:
            lines += _wrap(f"{i.location}: {i.message}", "      - ")
    return lines


def _change(d: Difference) -> str:
    if d.kind == "differing":
        return f"{_flat(d.official)!r} → {_flat(d.generated)!r}"
    if d.kind == "moved":
        return f"moved: official at {d.official} → generated at {d.generated}"
    if d.kind == "duplicate":
        return f"declared again — the original declaration is at {d.official}"
    return "missing in the generated" if d.kind == "absent" else "added by the generated"


def _source(v: Verdict, tag: str) -> str:
    """What an id of a reason stands for: the clause, the OpenAPI object, the document."""
    if tag == "C1":
        return "official"
    if tag == "C2":
        return "generated"
    e = next((x for x in v.evidence if x.id == tag), None)
    if e is None:
        return ""
    if e.source == "spec" and e.clause:
        return f"clause {e.clause}"
    steps = [x for x in e.path.split(" › ")
             if x and x not in ("OpenAPI Specification", "Specification", "Schema")]
    return " › ".join(steps[-2:]) or e.title or "reference"


def _named(v: Verdict, text: str) -> str:
    """A reason with each id it cites followed by what it stands for: S2 [clause 12.1]."""
    def name(m: re.Match) -> str:
        where = _source(v, m[0])
        return f"{m[0]} [{where}]" if where else m[0]
    return re.sub(r"\b[SOC]\d+\b", name, text)


def _sources(v: Verdict) -> list[str]:
    """The passages the verdict rests on, as the judge quoted them."""
    lines = []
    for c in v.answer.citations:
        lines += _wrap(f"{c.evidence_id} [{_source(v, c.evidence_id)}]: {c.quote}", "    ")
    return ["  sources:", *lines] if lines else []


def _listing(title: str, items: list[tuple[Verdict, int, Difference, str, str]]) -> list[str]:
    lines = [f"{title} ({len(items)} difference{'' if len(items) == 1 else 's'})"]
    if not items:
        return lines + ["  none"]
    for v, _, d, _, why in items:
        lines.append(f"  • {v.owner} · {d.official_location if d.kind == 'absent' else d.location}")
        lines += _wrap(f"{_change(d)}. {_named(v, why)}", "      ")
    return lines


def _disputed(report: JudgeReport) -> list[str]:
    """Blocks the judge took out of a group (judged again on their own), and groups it
    still disputes (a primary pair is never taken out) — for review."""
    items = [v for v in report.verdicts if v.answer.grouping_wrong]
    lines = [("GROUPINGS THE JUDGE DISPUTED — blocks put together that do not correspond "
              f"({len(report.regrouped) + len(items)})")]
    if not report.regrouped and not items:
        return lines + ["  none"]
    for taken in report.regrouped:
        lines += _wrap(f"• {taken}  → judged again on its own", "  ")
    for v in items:
        lines.append(f"  • {v.owner} — {v.aspect}  (still disputed)")
        lines += _wrap(v.answer.wrongly_grouped_why or v.answer.why_different, "      ")
    return lines


def _name_of(d: Difference, verdict: str) -> str:
    return ("text only in official" if _text_only_in_official(d, verdict)
            else VERDICT_NAME.get(verdict, verdict))


def _part(i: int, v: Verdict) -> list[str]:
    per = v.difference_verdicts or [v.answer.verdict] * len(v.differences)
    counts = Counter(_name_of(d, x) for d, x in zip(v.differences, per, strict=True))
    tally = ", ".join(f"{n} {name}" for name, n in counts.most_common()) or (
        VERDICT_NAME.get(v.answer.verdict, v.answer.verdict))
    lines = ["", _THIN, f"{i}. {v.owner} — {v.aspect}   [{tally}]", _THIN]
    lines += _wrap(v.summary, "  ")
    lines += _wrap(_named(v, v.answer.why_different), "  ")
    why = _reasons(v)
    for n, (d, verdict) in enumerate(zip(v.differences, per, strict=True), 1):
        mark = {"absent": "-", "extra": "+", "differing": "~", "moved": ">",
                "duplicate": "x"}[d.kind]
        where = d.official_location if d.kind == "absent" else d.location
        lines.append(f"  D{n} {_name_of(d, verdict).upper():22}{mark} {where}")
        if d.kind == "duplicate":
            lines.append(f"{'':29}original : {_flat(d.official)}  (in the generated)")
        elif d.kind in ("differing", "moved"):
            lines.append(f"{'':29}official : {_flat(d.official)}")
            lines.append(f"{'':29}generated: {_flat(d.generated)}")
        if why.get(f"D{n}"):
            lines += _wrap(_named(v, why[f"D{n}"]), " " * 29)
    lines += _wrap(_named(v, f"clearer: {v.answer.clearer} — {v.answer.clearer_why}"), "  ")
    return lines + _sources(v)


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
        *([f"spec      : {report.spec}  (the version this analysis is based on)"]
          if report.spec else []),
        *[f"WARNING   : {note}" for note in report.version_notes],
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
        "The lists below count differences; the tables above count fields (a difference may",
        "hold several fields, or none of its own when each has a verdict of its own).", "",
        _RULE, *_listing("IMPROVEMENTS — the generated is better than the official",
                         [x for x in api if x[3] == "improvement"]), "",
        _RULE, *_step2(report), "",
        _RULE,
        *_listing("ERRORS — wrong, or missing in the generated",
                  [x for x in api if x[3] == "error"]), "",
        *_listing("UNDECIDED — the evidence did not decide",
                  [x for x in api if x[3] == "uncertain"]), "",
        *_listing("EXTRA, USEFUL — only in the generated, not called for, contradicted by nothing",
                  [x for x in api if x[3] == "useful"]), "",
        *_listing("DIFFERENT, BUT RIGHT — written another way, same meaning",
                  [x for x in api if x[3] == "equivalent"
                   and not _text_only_in_official(x[2], x[3])]), "",
        *_listing("TEXT ONLY IN THE OFFICIAL — not scored",
                  [x for x in api if _text_only_in_official(x[2], x[3])]), "",
        *_disputed(report), "",
        *_listing("DOCUMENT HEADER — not scored", [x for x in diffs if _header(x[0])]), "",
        _RULE,
        ("DETAIL, PART BY PART  (a part: a group of corresponding blocks, or a block in one "
         "document only;"),
        ("                       D1, D2 …: its differences, each with its verdict.  - missing "
         "in the"),
        ("                       generated, + added by the generated, ~ changed, > moved, "
         "x duplicate)"),
    ]
    for i, v in enumerate(report.verdicts, 1):
        lines += _part(i, v)
    lines += ["", ("Verdicts are the judge's reading, uncalibrated until reviewed by a person. "
                   "The .json of this report holds each part's YAML and the evidence read.")]
    return "\n".join(lines) + "\n"


# ── the rules bank: the same reading, a rule in the place of a field ─────────

# what each row means, and the verdict it comes from (an example of the bank follows it)
_RULE_ROWS = (
    ("same", "SAME AS THE OFFICIAL",
     "address and value written as in the official. Decided without the judge: nothing differs."),
    ("different but right", "DIFFERENT, BUT RIGHT",
     "the value is written another way with the same meaning (judge: equivalent)."),
    ("better", "BETTER THAN THE OFFICIAL",
     ("the bank's value, or a rule the official lacks, is better supported by the spec "
      "(judge: improvement).")),
    ("wrong", "WRONG", "the bank's value on an official address is wrong (judge: error)."),
    ("missing", "MISSING IN THE BANK",
     "an official rule with no bank rule on its address, judged a real loss (judge: error)."),
    ("extra useful", "EXTRA, USEFUL",
     ("a bank rule on no official address: not called for, contradicted by nothing "
      "(judge: useful).")),
    ("extra wrong", "EXTRA, WRONG",
     ("a bank rule on no official address, or a further rule on one address, judged wrong "
      "(judge: error).")),
    ("extra discardable", "EXTRA, DISCARDABLE (THE USER'S CHOICE)",
     ("the bank declares default AND 4XX + 5XX on one operation: two configurations of the "
      "same errors. Neither right nor wrong — which to keep is the user's choice; the report "
      "gives the configuration the spec indicates. Counted in the bank's base, out of RIGHT.")),
    ("undecided", "UNDECIDED", "the evidence read did not decide (judge: uncertain)."),
)

_RECOMMENDATION = {"default": "default", "4XX + 5XX": "4XX + 5XX",
                   "both": "either — the spec gives both forms"}


def _choice_listing(report: JudgeReport) -> list[str]:
    """The operations where the bank declares default AND 4XX + 5XX (A.7): each rule's
    outcome and the configuration the spec indicates (the judge's recommendation)."""
    parts = [v for v in report.verdicts if v.aspect == "error responses"
             and v.summary.startswith("CASE: 4XX + 5XX + default —")]
    plural = "" if len(parts) == 1 else "s"
    lines = [f"DEFAULT OR 4XX + 5XX — the user's choice ({len(parts)} operation{plural})"]
    if not parts:
        return lines + ["  none"]
    for v in parts:
        lines.append(f"  • {v.owner.removesuffix(' · error responses')}")
        rules = (v.generated_focus or {}).get("rule") or []
        for r in rules if isinstance(rules, list) else [rules]:
            m = r.get("openapi_mapping") or {}
            got = v.rule_verdicts.get(str(r.get("rule_index")), v.answer.verdict)
            lines.append(f"      {m.get('openapi_field', ''):8} {_flat(m.get('openapi_value', ''))}"
                         f"   [{_choice_row(got)}]")
        rec = v.answer.recommendation
        lines += _wrap(f"recommended: {_RECOMMENDATION.get(rec, 'not given')}"
                       + (f" — {v.answer.recommendation_why}" if v.answer.recommendation_why
                          else ""), "      ")
    return lines


def _choice_row(verdict: str) -> str:
    return {"discardable": "extra, discardable", "same": "same", "error": "wrong",
            "improvement": "better", "equivalent": "different but right",
            "uncertain": "undecided"}.get(verdict, verdict)


def _rule_row(v: Verdict) -> str:
    from openapi_analysis.judge.parts import rule_outcome

    side = "generated" if v.aspect in ("extra", "duplicate") else "official"
    return rule_outcome(side, v.aspect, v.answer.verdict)


def _rule_value(side: dict) -> str:
    rule = side.get("rule")
    rules = rule if isinstance(rule, list) else [rule] if rule else []
    values = []
    for r in rules:
        m = (r or {}).get("openapi_mapping") or {}
        value = _flat(m.get("openapi_value", "")) or "(no value)"
        values.append(f"{m.get('openapi_field', '')}: {value}" if len(rules) > 1 else value)
    return " | ".join(values) if values else "—"


def _rule_values(v: Verdict) -> list[str]:
    return [f"      official: {_rule_value(v.official_focus) if v.official_focus else '— (no rule)'}",
            f"      bank    : {_rule_value(v.generated_focus) if v.generated_focus else '— (no rule)'}"]


def _how_to_read(report: JudgeReport) -> list[str]:
    first: dict[str, Verdict] = {}
    for v in report.verdicts:
        first.setdefault(_rule_row(v), v)
    lines = ["HOW TO READ",
             "  A rule is one address (rule_type · openapi_object · openapi_field) with its value.",
             "  Layer 1 only sorts: a rule equal to the official is SAME; every other one — a",
             "  different value, a value the official does not write, a missing rule, an extra",
             "  rule, a duplicate — gets a verdict, and the verdict gives the row. A verdict",
             "  comes from the judge (LLM), or from a rule when it follows from a fact of the",
             "  structure (a $ref that resolves to nothing): those are marked \"decided by a",
             "  rule\".", ""]
    for key, name, meaning in _RULE_ROWS:
        lines += _wrap(f"{name} — {meaning}", "  ")
        v = first.get(key)
        if v is not None:
            lines += _wrap(f"e.g. {v.owner}", "      ")
            lines += _rule_values(v)
    return lines


def _rule_listing(title: str, items: list[Verdict]) -> list[str]:
    lines = [f"{title} ({len(items)} rule part{'' if len(items) == 1 else 's'})"]
    if not items:
        return lines + ["  none"]
    for v in items:
        lines.append(f"  • {v.owner}   [{v.aspect}]")
        lines += _rule_values(v)
        lines += _wrap(_named(v, v.answer.why_different), "      ")
    return lines


def _rule_part(i: int, v: Verdict) -> list[str]:
    a = v.answer
    by_rule = v.decided_by == "rule"
    lines = ["", _THIN, f"{i}. {v.owner} — {v.aspect}   [{VERDICT_NAME.get(a.verdict, a.verdict)}]"
             + ("   (decided by a rule, no LLM)" if by_rule else ""), _THIN]
    lines += _wrap(v.summary, "  ")
    lines += _rule_values(v)
    if by_rule:
        lines += _wrap(f"rule: {a.why_different}", "  ")
        return lines + [f"  override: {o}" for o in v.overrides]
    for label, text in (("why", a.why_different), ("3GPP", a.spec_3gpp),
                        ("OpenAPI", a.openapi),
                        ("clearer", f"{a.clearer} — {a.clearer_why}")):
        lines += _wrap(_named(v, f"{label}: {text}"), "  ")
    if a.recommendation:
        lines += _wrap(_named(v, f"recommended configuration: "
                                 f"{_RECOMMENDATION.get(a.recommendation, a.recommendation)} — "
                                 f"{a.recommendation_why}"), "  ")
    if v.rule_verdicts:
        lines += _wrap("each rule: " + ", ".join(f"#{k} {_choice_row(x)}"
                                                 for k, x in v.rule_verdicts.items()), "  ")
    lines += [f"  override: {o}" for o in v.overrides]
    return lines + _sources(v)


def render_final_rulesbank(report: JudgeReport) -> str:
    """The complete analysis of one rules bank: layers 1 + 3 (layer 2, OpenAPI validity,
    does not apply to a bank) — the result first, then the lists, then each part."""
    usage = report.usage
    by_row: dict[str, list[Verdict]] = {}
    for v in report.verdicts:
        by_row.setdefault(_rule_row(v), []).append(v)
    by_rule = sum(v.decided_by == "rule" for v in report.verdicts)
    partial = (f"WARNING   : {len(report.verdicts)} of {report.parts_total} parts judged — "
               "the views count the others as undecided"
               if report.parts_total > len(report.verdicts) else "")
    lines = [
        _RULE,
        f"FINAL ANALYSIS — {report.service}: the rules bank against the official YAML",
        _RULE,
        f"bank      : {report.input}",
        *([f"official  : {report.official.label}  (v{report.official.version})"]
          if report.official else []),
        *([f"spec      : {report.spec}  (the version this analysis is based on)"]
          if report.spec else []),
        *[f"WARNING   : {note}" for note in report.version_notes],
        *([partial] if partial else []),
        f"evaluated : {_when(report.evaluated_at)}",
        (f"judge     : {report.model}, prompt {report.prompt_version}; 3GPP spec "
         f"{report.spec_collection} (clauses {', '.join(report.scope) or 'all'}) + OpenAPI "
         "3.0 reference"),
        (f"verdicts  : {len(report.verdicts) - by_rule} by the judge, {by_rule} by a rule "
         "(judge/rules.py: a fact of the structure, no LLM)"),
        (f"cost      : {usage.get('llm_calls', 0)} LLM call(s), US$ {usage.get('cost_usd', 0)}"
         " this run (cached answers cost nothing)"),
        "",
        _RULE, "RESULT", "",
        *_view(report, "official", unit="rules", evaluated="bank"), "",
        *_view(report, "generated", unit="rules", evaluated="bank"), "",
        "  Every line but SAME is a verdict: the judge's reading (not a measurement, and",
        "  uncalibrated until reviewed by a person) or a rule's, from a fact of the structure.",
        "",
        _RULE, *_how_to_read(report), "",
        _RULE, *_rule_listing("IMPROVEMENTS — the bank is better than the official",
                              by_row.get("better", [])), "",
        *_rule_listing("ERRORS — wrong, or missing in the bank",
                       by_row.get("wrong", []) + by_row.get("missing", [])), "",
        *_rule_listing("EXTRA, WRONG — on no official address, or a further rule on one",
                       by_row.get("extra wrong", [])), "",
        *_rule_listing("UNDECIDED — the evidence did not decide", by_row.get("undecided", [])),
        "",
        *_choice_listing(report), "",
        *_rule_listing("EXTRA, USEFUL — only in the bank, not called for, contradicted by "
                       "nothing", by_row.get("extra useful", [])), "",
        *_rule_listing("DIFFERENT, BUT RIGHT — written another way, same meaning",
                       by_row.get("different but right", [])), "",
        _RULE, "DETAIL, PART BY PART  (each rule that is not equal to the official, as judged)",
    ]
    for i, v in enumerate(report.verdicts, 1):
        lines += _rule_part(i, v)
    lines += ["", ("Verdicts are the judge's reading, uncalibrated until reviewed by a person. "
                   "The .json of this report holds each rule and the evidence read.")]
    return "\n".join(lines) + "\n"
