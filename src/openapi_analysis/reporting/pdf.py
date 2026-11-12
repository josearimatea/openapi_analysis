"""A report's text as a PDF, for reading: the same text, line for line — only the layout is
added. Nothing is summarised, reordered or left out.

Layout read from the text the renderers write (reporting/text.py, reporting/final.py):
  "====" lines around a title   a main section: the title set apart, the lines drawn;
                                the DETAIL section starts a page
  "----" lines around a title   a part of the detail: a thin line and the title in bold
  any other line                as written, in a monospaced font; a line wider than the
                                page is broken at spaces, the rest indented under it
"""

from __future__ import annotations

import textwrap
from html import escape
from pathlib import Path

WIDTH = 112          # characters that fit the A4 text width at the body size below
_FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu",
              "/Library/Fonts", "C:/Windows/Fonts")


def _fonts() -> tuple[str, str]:
    """(regular, bold): DejaVu Sans Mono when the system has it (it draws ─ · — •);
    else the PDF's own Courier, with the characters it lacks replaced."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for folder in _FONT_DIRS:
        regular, bold = Path(folder, "DejaVuSansMono.ttf"), Path(folder, "DejaVuSansMono-Bold.ttf")
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("ReportMono", str(regular)))
            pdfmetrics.registerFont(TTFont("ReportMono-Bold", str(bold)))
            return "ReportMono", "ReportMono-Bold"
    return "Courier", "Courier-Bold"


def _plain(text: str, font: str) -> str:
    if font != "Courier":
        return text
    text = text.replace("─", "-").replace("→", "->")
    return text.encode("cp1252", "replace").decode("cp1252")


def wrapped(line: str, width: int = WIDTH) -> list[str]:
    """A line longer than the page, broken at spaces; the continuation is indented under
    the line's own text. Nothing is cut."""
    if len(line) <= width:
        return [line]
    lead = len(line) - len(line.lstrip(" "))
    return textwrap.wrap(line, width, subsequent_indent=" " * (lead + 4),
                         drop_whitespace=False, break_on_hyphens=False) or [line]


def _rule_of(line: str, char: str) -> bool:
    return len(line) > 20 and set(line) == {char}


def write_pdf(text: str, path: Path, title: str = "") -> Path:
    """Write `text` (a report as rendered) to `path` as a PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        XPreformatted,
    )

    regular, bold = _fonts()
    ink, accent, rule = (colors.HexColor(c) for c in ("#1f2933", "#1d4e89", "#9aa5b1"))
    body = ParagraphStyle("body", fontName=regular, fontSize=7.4, leading=9.4, textColor=ink)
    section = ParagraphStyle("section", fontName=bold, fontSize=10.5, leading=13,
                             textColor=accent, spaceBefore=4, spaceAfter=4)
    part = ParagraphStyle("part", fontName=bold, fontSize=7.8, leading=10, textColor=ink,
                          spaceBefore=6)

    lines = [_plain(line, regular) for line in text.splitlines()]
    story: list = []
    block: list[str] = []

    def flush() -> None:
        if block:
            story.append(XPreformatted(escape("\n".join(block)), body))
            block.clear()

    def line_at(i: int) -> str:
        return lines[i] if i < len(lines) else ""

    i = 0
    while i < len(lines):
        line = lines[i]
        if _rule_of(line, "="):                        # "====\nTITLE\n===="
            flush()
            heading = line_at(i + 1)
            if story:
                story.append(PageBreak() if heading.startswith("DETAIL") else Spacer(1, 8))
            story.append(HRFlowable(width="100%", thickness=1.2, color=accent, spaceAfter=2))
            if heading.strip() and not _rule_of(heading, "="):
                story.append(Paragraph(escape(heading), section))
                i += 1
                if _rule_of(line_at(i + 1), "="):
                    story.append(HRFlowable(width="100%", thickness=1.2, color=accent,
                                            spaceAfter=4))
                    i += 1
        elif _rule_of(line, "-"):                      # "----\nN. part\n----"
            flush()
            heading = line_at(i + 1)
            if heading.strip():
                story.append(Spacer(1, 4))
                story.append(HRFlowable(width="100%", thickness=0.4, color=rule, spaceAfter=1))
                story.append(Paragraph(escape(heading), part))
                i += 1
                if _rule_of(line_at(i + 1), "-"):
                    i += 1
        else:
            block.extend(wrapped(line))
        i += 1
    flush()

    name = path.with_suffix(".txt").name

    def page(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(regular, 6.8)
        canvas.setFillColor(rule)
        canvas.drawString(1.5 * cm, 1 * cm, name)
        canvas.drawRightString(A4[0] - 1.5 * cm, 1 * cm, str(doc.page))
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                      topMargin=1.5 * cm, bottomMargin=1.6 * cm, title=title or path.stem,
                      author="openapi_analysis").build(story, onFirstPage=page,
                                                       onLaterPages=page)
    return path
