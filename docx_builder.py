"""
Builds a formatted, professional .docx from an AI Assessment's plain text.

The assessment always comes back from Claude in the fixed section structure
defined in prompts.build_assessment_prompt (CURRENT STATE, KEY CHALLENGES,
RECOMMENDED AI OPPORTUNITIES, ESTIMATED IMPACT, SUGGESTED NEXT STEPS). This
module parses that structure into real Word headings and bullet lists
rather than dumping it as one plain paragraph, since the whole point is
that a consultant can open this and send it as-is.
"""

import io
import re
from datetime import date

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

_SECTION_HEADERS = [
    "CURRENT STATE",
    "KEY CHALLENGES",
    "RECOMMENDED AI OPPORTUNITIES",
    "BROADER AI LANDSCAPE FOR THIS INDUSTRY",
    "ESTIMATED IMPACT",
    "SUGGESTED NEXT STEPS",
]

_BRAND_BLUE = RGBColor(0x2A, 0x3B, 0x8F)
_BRAND_GRAY = RGBColor(0x5A, 0x5F, 0x6E)


def _strip_markdown_artifacts(text: str) -> str:
    """Claude occasionally decorates output with markdown even when told
    not to (## headers, **bold**) — strip it before parsing rather than
    relying solely on the prompt instruction, since that's not 100%
    deterministic. This keeps section-header matching working either way."""
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # leading #/##/### on a line
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)                # **bold** -> bold
    return text


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Splits the assessment text into (header, body) pairs using the known
    fixed headers. Anything before the first recognized header (there
    shouldn't be any, but defensively) is dropped rather than mis-labeled."""
    text = _strip_markdown_artifacts(text)
    pattern = "|".join(re.escape(h) for h in _SECTION_HEADERS)
    parts = re.split(f"^({pattern})\\s*$", text, flags=re.MULTILINE)
    sections = []
    # re.split with a capturing group interleaves: [pre, header, body, header, body, ...]
    for i in range(1, len(parts) - 1, 2):
        header = parts[i].strip()
        body = parts[i + 1].strip()
        sections.append((header, body))
    return sections


def _add_body_paragraphs(doc: Document, body: str) -> None:
    """Renders a section body as real bullet points where the source used
    '-'/'•' prefixes, plain paragraphs otherwise.

    Numbered items are rendered as plain indented paragraphs with the
    number kept as literal text, NOT Word's built-in numbered-list style —
    that style continues counting across the whole document regardless of
    section breaks, so a second numbered section would start at "4." instead
    of "1." with no easy per-section reset. Literal numbers sidestep that."""
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("- ", "• ", "* ")):
            p = doc.add_paragraph(line[2:].strip(), style="List Bullet")
        elif re.match(r"^\d+[.)]\s", line):
            p = doc.add_paragraph(line)  # keep the "1. " as literal text
            p.paragraph_format.left_indent = Inches(0.25)
        else:
            p = doc.add_paragraph(line)
        for run in p.runs:
            run.font.size = Pt(11)


def _heading_text(header: str) -> str:
    """Title-cases a section header while keeping known acronyms intact —
    plain .title() turns "AI" into "Ai", which looks like a typo on a
    document a client actually reads."""
    words = header.title().split()
    return " ".join("AI" if w.upper() == "AI" else w for w in words)


def build_assessment_docx(assessment_text: str, client_name: str = "") -> io.BytesIO:
    doc = Document()

    # US Letter, not the python-docx default — matches what a US client expects printed.
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = title.add_run("AI Opportunity Assessment")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = _BRAND_BLUE

    subtitle = doc.add_paragraph()
    sub_run = subtitle.add_run(
        f"Prepared for {client_name.strip()}" if client_name.strip() else "Prepared for the client"
    )
    sub_run.font.size = Pt(12)
    sub_run.font.color.rgb = _BRAND_GRAY

    meta = doc.add_paragraph()
    meta_run = meta.add_run(f"AI Curator LLC  ·  {date.today().strftime('%B %d, %Y')}")
    meta_run.font.size = Pt(9.5)
    meta_run.font.color.rgb = _BRAND_GRAY
    meta_run.italic = True

    # Simple rule under the header block, per the skill's guidance to use a
    # paragraph border rather than a table for a horizontal rule.
    p = doc.add_paragraph()
    p_border = p.paragraph_format
    p_border.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "2A3B8F")
    pBdr.append(bottom)
    pPr.append(pBdr)

    doc.add_paragraph()  # spacing

    for header, body in _parse_sections(assessment_text):
        heading = doc.add_heading(_heading_text(header), level=2)
        for run in heading.runs:
            run.font.color.rgb = _BRAND_BLUE
            run.font.size = Pt(14)
        _add_body_paragraphs(doc, body)
        doc.add_paragraph()  # spacing between sections

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
