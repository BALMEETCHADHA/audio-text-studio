"""
Renders the PDF downloads (full report, or transcript only).

English only, so the built-in PDF font is enough. That font covers Latin-1, and
"smart" typography that is everywhere in normal writing (em/en dashes, curly
quotes, ellipsis characters, non-breaking spaces) would crash it — AI-written
text uses these constantly, and it broke real jobs. They are swapped for plain
ASCII look-alikes first, and anything still outside Latin-1 (an emoji, say)
becomes '?' instead of crashing the export.
"""
import uuid
from pathlib import Path

from fpdf import FPDF

from config import settings

_ASCII_FALLBACKS = {
    "\u2014": "-", "\u2013": "-",       # em dash, en dash
    "\u2018": "'", "\u2019": "'",       # curly single quotes
    "\u201c": '"', "\u201d": '"',       # curly double quotes
    "\u2026": "...",                     # ellipsis
    "\u00a0": " ",                       # non-breaking space
    "\u2022": "-",                       # bullet
}


def _safe_text(text: str) -> str:
    """Guarantees `text` can be drawn by the built-in (Latin-1) PDF font."""
    for smart, plain in _ASCII_FALLBACKS.items():
        text = text.replace(smart, plain)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class _ReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=18)
        self.add_page()

    def body_font(self, size=11, bold=False):
        self.set_font("Helvetica", "B" if bold else "", size)

    def block(self, h: float, text: str):
        """
        Write one full-width block of text, always starting at the left margin.

        This exists because of a real crash: fpdf2's multi_cell() leaves the
        cursor at the RIGHT edge of the cell it just wrote. A following
        multi_cell(w=0, ...) then measures "remaining width" from there, gets
        roughly zero, and raises "Not enough horizontal space to render a
        single character". Calls followed by self.ln() happened to be safe
        (ln() resets X to the left margin), but consecutive calls — like a loop
        writing bullets — were not. Resetting X here makes every call start
        from a full-width line, whatever was written before it.
        """
        if not text:
            return
        self.set_x(self.l_margin)
        self.multi_cell(0, h, _safe_text(text))

    def h1(self, text: str):
        self.body_font(16, bold=True)
        self.block(10, text)
        self.ln(2)

    def h2(self, text: str):
        self.body_font(13, bold=True)
        self.block(8, text)
        self.ln(1)

    def paragraph(self, text: str):
        self.body_font(11)
        self.block(6, text)
        self.ln(2)

    def bullet_list(self, items: list[str]):
        self.body_font(11)
        for item in items:
            self.block(6, f"-  {item}")
        self.ln(2)


def _save(pdf: _ReportPDF) -> Path:
    out_path = settings.storage_path / "reports" / f"{uuid.uuid4().hex}.pdf"
    pdf.output(str(out_path))
    return out_path


def build_full_report_pdf(
    transcript: str,
    summary: str | None,
    key_points: list[str],
    links_mentioned: list[str],
    ai_insights: str | None,
    dates_mentioned: list[str] | None = None,
    notable_terms: list[str] | None = None,
    title: str = "Audio Transcription Report",
    transcript_label: str = "Full Transcript (word for word)",
) -> Path:
    """Same order as the results page: transcript, summary, key points, AI insights, highlights."""
    pdf = _ReportPDF()
    pdf.h1(title)

    pdf.h2(transcript_label)
    pdf.paragraph(transcript)

    if summary:
        pdf.h2("Summary")
        pdf.paragraph(summary)
    if key_points:
        pdf.h2("Key Points")
        pdf.bullet_list(key_points)
    if ai_insights:
        pdf.h2("AI Insights")
        pdf.paragraph(ai_insights)
    if dates_mentioned or links_mentioned or notable_terms:
        pdf.h2("Highlights")
        if dates_mentioned:
            pdf.paragraph("Dates mentioned:")
            pdf.bullet_list(dates_mentioned)
        if links_mentioned:
            pdf.paragraph("Links mentioned:")
            pdf.bullet_list(links_mentioned)
        if notable_terms:
            pdf.paragraph("Notable terms:")
            pdf.bullet_list(notable_terms)
    return _save(pdf)


def build_transcribe_only_pdf(transcript: str) -> Path:
    pdf = _ReportPDF()
    pdf.h1("Audio Transcript")
    pdf.paragraph(transcript)
    return _save(pdf)
