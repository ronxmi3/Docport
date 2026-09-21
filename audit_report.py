"""PDF audit-report rendering from stored SDOC pipeline decisions.

This module is deliberately presentation-only.  It never classifies an email,
opens an attachment, extracts a field, normalizes a value, or compares two
documents.  Everything it renders comes from immutable ``EmailRecord`` and
``EmailDecision`` objects created by the existing pipeline.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from xml.sax.saxutils import escape

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from explanation import format_email_explanation
from models import EMAIL_CATEGORIES, REQUIRED_FIELDS, Attachment, DocumentAssessment, EmailDecision, EmailRecord


_PAGE_SIZE = landscape(letter)
_MARGIN = 0.5 * inch
_PAGE_WIDTH = _PAGE_SIZE[0] - (2 * _MARGIN)


@dataclass(frozen=True)
class AuditReportResult:
    """The written report and the deterministic set of included email IDs."""

    path: Path
    included_email_ids: tuple[str, ...]
    page_count: int

    @property
    def included_count(self) -> int:
        return len(self.included_email_ids)


def write_decision_audit_report(
    output_path: str | Path,
    emails: Iterable[EmailRecord],
    decisions: Mapping[str, EmailDecision],
    *,
    runtime_seconds: float,
    throughput: float,
    problems_only: bool = False,
) -> AuditReportResult:
    """Write a readable PDF report from existing pipeline evidence.

    ``emails`` identifies the run scope.  This is important for ``--email``:
    the loaded bundle can contain every email, while a one-email demo report
    must include exactly the email that was processed.
    """

    records = tuple(sorted(emails, key=lambda email: email.email_id))
    missing_decisions = [email.email_id for email in records if email.email_id not in decisions]
    if missing_decisions:
        raise ValueError(f"Cannot render report; decisions missing for: {', '.join(missing_decisions)}")

    included = tuple(
        email
        for email in records
        if not problems_only or decisions[email.email_id].status in {"MISMATCH", "NEEDS_REVIEW"}
    )
    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    styles = _build_styles()
    document = SimpleDocTemplate(
        str(target),
        pagesize=_PAGE_SIZE,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=0.68 * inch,
        bottomMargin=0.52 * inch,
        title="SDOC Shipping Document Verification - Decision Audit Report",
        author="SDOC Pipeline",
    )
    story = _summary_story(records, decisions, runtime_seconds, throughput, problems_only, included, styles)
    for index, email in enumerate(included):
        story.append(PageBreak())
        story.extend(_email_story(email, decisions[email.email_id], styles))
        if index == len(included) - 1:
            continue
    if not included:
        story.append(Spacer(1, 0.15 * inch))
        story.append(_paragraph("No MISMATCH or NEEDS_REVIEW decisions were included.", styles["Body"]))

    document.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    page_count = len(PdfReader(str(target)).pages)
    return AuditReportResult(
        path=target.resolve(),
        included_email_ids=tuple(email.email_id for email in included),
        page_count=page_count,
    )


def _summary_story(
    records: tuple[EmailRecord, ...],
    decisions: Mapping[str, EmailDecision],
    runtime_seconds: float,
    throughput: float,
    problems_only: bool,
    included: tuple[EmailRecord, ...],
    styles: Mapping[str, ParagraphStyle],
) -> list[object]:
    """Create the required first page from aggregate stored decision data."""

    scoped_decisions = [decisions[email.email_id] for email in records]
    category_counts = Counter(decision.category for decision in scoped_decisions)
    status_counts = Counter(decision.status for decision in scoped_decisions)
    review_counts = Counter(
        decision.review_reason for decision in scoped_decisions if decision.review_reason is not None
    )
    mode = "Problem decisions only" if problems_only else "All processed email decisions"
    summary_rows = [
        [_paragraph("<b>Total emails processed</b>", styles["TableCell"]), _paragraph(str(len(records)), styles["TableCell"])],
        [_paragraph("<b>Emails included in this report</b>", styles["TableCell"]), _paragraph(str(len(included)), styles["TableCell"])],
        [_paragraph("<b>Report scope</b>", styles["TableCell"]), _paragraph(mode, styles["TableCell"])],
        [_paragraph("<b>Runtime</b>", styles["TableCell"]), _paragraph(f"{runtime_seconds:.2f} seconds", styles["TableCell"])],
        [_paragraph("<b>Throughput</b>", styles["TableCell"]), _paragraph(f"{throughput:.2f} emails/sec", styles["TableCell"])],
        [_paragraph("<b>BL comparison count</b>", styles["TableCell"]), _paragraph(str(sum(decision.category == "BL_COMPARISON" for decision in scoped_decisions)), styles["TableCell"])],
        [_paragraph("<b>OK count</b>", styles["TableCell"]), _paragraph(str(status_counts["OK"]), styles["TableCell"])],
        [_paragraph("<b>MISMATCH count</b>", styles["TableCell"]), _paragraph(str(status_counts["MISMATCH"]), styles["TableCell"])],
        [_paragraph("<b>NEEDS_REVIEW count</b>", styles["TableCell"]), _paragraph(str(status_counts["NEEDS_REVIEW"]), styles["TableCell"])],
    ]
    category_rows = [[_paragraph("<b>Category</b>", styles["TableHeader"]), _paragraph("<b>Count</b>", styles["TableHeader"])] ]
    category_rows.extend(
        [_paragraph(category, styles["TableCell"]), _paragraph(str(category_counts[category]), styles["TableCell"])]
        for category in EMAIL_CATEGORIES
    )
    review_rows = [[_paragraph("<b>Review reason</b>", styles["TableHeader"]), _paragraph("<b>Count</b>", styles["TableHeader"])] ]
    if review_counts:
        review_rows.extend(
            [_paragraph(reason, styles["TableCell"]), _paragraph(str(count), styles["TableCell"])]
            for reason, count in sorted(review_counts.items())
        )
    else:
        review_rows.append([_paragraph("None", styles["TableCell"]), _paragraph("0", styles["TableCell"])])

    story: list[object] = [
        _paragraph("SDOC Shipping Document Verification", styles["Title"]),
        _paragraph("Decision Audit Report", styles["Subtitle"]),
        Spacer(1, 0.22 * inch),
        _paragraph("Summary", styles["Heading"]),
        _styled_table(summary_rows, [2.85 * inch, 3.8 * inch]),
        Spacer(1, 0.16 * inch),
        _paragraph("Category counts", styles["HeadingSmall"]),
        _styled_table(category_rows, [2.2 * inch, 1.0 * inch], header=True),
        Spacer(1, 0.16 * inch),
        _paragraph("Review reason breakdown", styles["HeadingSmall"]),
        _styled_table(review_rows, [2.2 * inch, 1.0 * inch], header=True),
    ]
    return story


def _email_story(email: EmailRecord, decision: EmailDecision, styles: Mapping[str, ParagraphStyle]) -> list[object]:
    """Render one audit section solely from stored email and decision objects."""

    # Keep headings with their immediate context, but leave large tables as
    # normal flowables so ReportLab can split them cleanly between pages.
    identity_table = _styled_table(
            [
                [_paragraph("<b>Email ID</b>", styles["TableCell"]), _paragraph(email.email_id, styles["TableCell"])],
                [_paragraph("<b>Subject</b>", styles["TableCell"]), _paragraph(_value(email.subject), styles["TableCell"])],
                [_paragraph("<b>Category</b>", styles["TableCell"]), _paragraph(decision.category, styles["TableCell"])],
                [_paragraph("<b>Classification evidence</b>", styles["TableCell"]), _paragraph(_joined(decision.classification_reasons), styles["TableCell"])],
            ],
            [1.6 * inch, _PAGE_WIDTH - (1.6 * inch)],
        )
    story: list[object] = [
        KeepTogether(
            [
                _paragraph(f"Email audit: {email.email_id}", styles["Heading"]),
                identity_table,
                Spacer(1, 0.12 * inch),
                _paragraph("Attachments and document identification", styles["HeadingSmall"]),
            ]
        ),
        _attachment_table(email, decision, styles),
    ]
    if decision.category == "BL_COMPARISON":
        story.extend(
            [
                Spacer(1, 0.12 * inch),
                _paragraph("SI versus BL field comparison", styles["HeadingSmall"]),
                _field_table(decision, styles),
            ]
        )
    explanation_blocks = _explanation_blocks(format_email_explanation(email, decision), styles["Explanation"])
    final_section: list[object] = [
            Spacer(1, 0.12 * inch),
            _paragraph("Final decision", styles["HeadingSmall"]),
            _styled_table(
                [
                    [_paragraph("<b>Final status</b>", styles["TableCell"]), _paragraph(_value(decision.status), styles["TableCell"])],
                    [_paragraph("<b>Defect fields</b>", styles["TableCell"]), _paragraph(_joined(decision.defect_fields), styles["TableCell"])],
                    [_paragraph("<b>Review reason</b>", styles["TableCell"]), _paragraph(_value(decision.review_reason), styles["TableCell"])],
                ],
                [1.6 * inch, _PAGE_WIDTH - (1.6 * inch)],
            ),
            Spacer(1, 0.12 * inch),
            _paragraph("Human-readable explanation", styles["HeadingSmall"]),
    ]
    # The first stored explanation block (email ID/subject) belongs with the
    # decision summary.  The middle of a long explanation remains one normal
    # Paragraph to avoid adding artificial vertical gaps at every heading.
    if explanation_blocks:
        final_section.append(explanation_blocks[0])
    story.append(KeepTogether(final_section))
    for block in explanation_blocks[1:]:
        story.extend((Spacer(1, 0.04 * inch), block))
    return story


def _attachment_table(
    email: EmailRecord, decision: EmailDecision, styles: Mapping[str, ParagraphStyle]
) -> Table:
    """Render type evidence captured by document handling, never re-detect it."""

    assessments = decision.selection.assessments if decision.selection else ()
    assessment_by_attachment = {id(item.attachment): item for item in assessments}
    rows: list[list[Paragraph]] = [
        [
            _paragraph("<b>Attachment</b>", styles["TableHeader"]),
            _paragraph("<b>Detected type</b>", styles["TableHeader"]),
            _paragraph("<b>Document-type evidence</b>", styles["TableHeader"]),
            _paragraph("<b>Source format</b>", styles["TableHeader"]),
            _paragraph("<b>Extraction method</b>", styles["TableHeader"]),
        ]
    ]
    if not email.attachments:
        rows.append([_paragraph("No attachments", styles["TableCell"])] + [_paragraph("-", styles["TableCell"]) for _ in range(4)])
    else:
        for attachment in email.attachments:
            assessment = assessment_by_attachment.get(id(attachment))
            rows.append(
                [
                    _paragraph(attachment.filename, styles["TableCell"]),
                    _paragraph(assessment.document_type if assessment else "Not evaluated", styles["TableCell"]),
                    _paragraph(_joined(assessment.reasons) if assessment else "Not evaluated (not a BL comparison)", styles["TableCell"]),
                    _paragraph(_source_format(attachment), styles["TableCell"]),
                    _paragraph(_extraction_method(attachment), styles["TableCell"]),
                ]
            )
    return _styled_table(rows, [1.4 * inch, 0.85 * inch, 2.9 * inch, 0.8 * inch, 1.0 * inch], header=True)


def _field_table(decision: EmailDecision, styles: Mapping[str, ParagraphStyle]) -> Table:
    """Use stored raw/normalized mappings and stored comparison field results."""

    rows: list[list[Paragraph]] = [
        [
            _paragraph("<b>Field</b>", styles["TableHeader"]),
            _paragraph("<b>SI Raw</b>", styles["TableHeader"]),
            _paragraph("<b>BL Raw</b>", styles["TableHeader"]),
            _paragraph("<b>SI Normalized</b>", styles["TableHeader"]),
            _paragraph("<b>BL Normalized</b>", styles["TableHeader"]),
            _paragraph("<b>Result</b>", styles["TableHeader"]),
        ]
    ]
    for field in REQUIRED_FIELDS:
        comparison = decision.comparison.fields[field] if decision.comparison else None
        result = "NOT COMPARED" if comparison is None else ("MATCH" if comparison.matches else "MISMATCH")
        rows.append(
            [
                _paragraph(field, styles["TableCell"]),
                _paragraph(_mapping_value(decision.si_extracted, field), styles["TableCell"]),
                _paragraph(_mapping_value(decision.bl_extracted, field), styles["TableCell"]),
                _paragraph(_mapping_value(decision.si_normalized, field), styles["TableCell"]),
                _paragraph(_mapping_value(decision.bl_normalized, field), styles["TableCell"]),
                _paragraph(result, styles["TableCell"]),
            ]
        )
    return _styled_table(rows, [1.08 * inch, 1.35 * inch, 1.35 * inch, 1.35 * inch, 1.35 * inch, 0.72 * inch], header=True)


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle("AuditTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=21, leading=25, alignment=TA_CENTER, textColor=colors.HexColor("#16324F"), spaceAfter=2),
        "Subtitle": ParagraphStyle("AuditSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=13, leading=16, alignment=TA_CENTER, textColor=colors.HexColor("#3B556D")),
        "Heading": ParagraphStyle("AuditHeading", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=colors.HexColor("#16324F"), spaceAfter=6, keepWithNext=1),
        "HeadingSmall": ParagraphStyle("AuditHeadingSmall", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#16324F"), spaceAfter=4, keepWithNext=1),
        "Body": ParagraphStyle("AuditBody", parent=base["BodyText"], fontName="Helvetica", fontSize=8.4, leading=10.4, alignment=TA_LEFT),
        "TableCell": ParagraphStyle("AuditTableCell", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2, leading=8.8, alignment=TA_LEFT, wordWrap="CJK"),
        "TableHeader": ParagraphStyle("AuditTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=8.8, textColor=colors.white, alignment=TA_LEFT, wordWrap="CJK"),
        "Explanation": ParagraphStyle("AuditExplanation", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9.2, backColor=colors.HexColor("#F3F6F8"), borderColor=colors.HexColor("#D5DEE5"), borderWidth=0.5, borderPadding=6, wordWrap="CJK"),
    }


def _styled_table(rows: list[list[Paragraph]], widths: list[float], *, header: bool = False) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT", splitByRow=1)
    commands: list[tuple[object, ...]] = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C5D0D8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F5A7A")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FA")]),
            ]
        )
    else:
        commands.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#F5F8FA")]))
    table.setStyle(TableStyle(commands))
    return table


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    raw_text = _value(value)
    # Labels are marked internally, while every user-derived value still goes
    # through XML escaping below.  This keeps table labels bold without
    # allowing email content to become ReportLab markup.
    if raw_text.startswith("<b>") and raw_text.endswith("</b>"):
        raw_text = raw_text[3:-4]
        style = ParagraphStyle(f"{style.name}Bold", parent=style, fontName="Helvetica-Bold")
    text = raw_text.replace("\n", "<br/>")
    return Paragraph(escape(text, {'"': '&quot;'}), style)


def _explanation_paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    """Preserve the established explainer's line structure inside the PDF."""

    text = value.strip() or "-"
    escaped = escape(text, {'"': '&quot;'}).replace("\n", "<br/>")
    return Paragraph(escaped, style)


def _explanation_blocks(value: str, style: ParagraphStyle) -> list[object]:
    """Split existing explanation text only at its blank-line section breaks.

    This is presentation-only: it does not recompute any reasoning.  A final
    ``Reason:`` block remains one Paragraph with its first reason line, which
    prevents the common two-line orphan at a page boundary.
    """

    blocks = [block.strip() for block in value.split("\n\n") if block.strip()]
    if not blocks:
        return [_explanation_paragraph("-", style)]
    if len(blocks) == 1:
        return [_explanation_paragraph(blocks[0], style)]

    first = _explanation_paragraph(blocks[0], style)
    # Keep a final Reason block with its first reason line.  All intervening
    # stored explanation sections stay in a single split-capable Paragraph,
    # which is both more compact and less prone to one-line spill pages.
    final_reason = blocks[-1] if blocks[-1].startswith("Reason:") else None
    middle_blocks = blocks[1:-1] if final_reason else blocks[1:]
    result: list[object] = [first]
    if middle_blocks:
        result.append(_explanation_paragraph("\n\n".join(middle_blocks), style))
    if final_reason:
        result.append(KeepTogether([Spacer(1, 0.04 * inch), _explanation_paragraph(final_reason, style)]))
    return result


def _value(value: object | None) -> str:
    """Render unset stored values clearly without manufacturing replacements."""

    if value is None:
        return "-"
    text = " ".join(str(value).split())
    return text if text else "-"


def _mapping_value(values: Mapping[str, str | None] | None, field: str) -> str:
    return _value(values.get(field) if values is not None else None)


def _joined(values: Iterable[object]) -> str:
    rendered = [_value(value) for value in values if value is not None]
    return "; ".join(rendered) if rendered else "-"


def _source_format(attachment: Attachment) -> str:
    stored = attachment.metadata.get("source_format")
    if stored:
        return _value(stored)
    suffix = Path(attachment.filename).suffix.removeprefix(".").upper()
    return suffix or "UNKNOWN"


def _extraction_method(attachment: Attachment) -> str:
    stored = attachment.metadata.get("extraction")
    if stored:
        return _value(stored)
    return "plain text" if Path(attachment.filename).suffix.casefold() == ".txt" else "unavailable"


def _draw_footer(canvas, document) -> None:  # type: ignore[no-untyped-def]
    """Apply a consistent header/footer and page number to every report page."""

    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#C5D0D8"))
    canvas.setLineWidth(0.5)
    canvas.line(_MARGIN, 0.39 * inch, _PAGE_SIZE[0] - _MARGIN, 0.39 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#526B7A"))
    canvas.drawString(_MARGIN, 0.23 * inch, "SDOC Shipping Document Verification - Decision Audit Report")
    canvas.drawRightString(_PAGE_SIZE[0] - _MARGIN, 0.23 * inch, f"Page {document.page}")
    canvas.restoreState()
