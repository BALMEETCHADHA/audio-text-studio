"""
A single-image export of the results: transcript (or the whole text), summary, key points,
AI insights and highlights, in the same order as the results page, on one tall card.

Meant for quick sharing (chat apps, social posts). A picture is a poor format for very long text,
so the transcript part is capped at ~1,200 words and says so; the PDF / Word downloads always hold
the complete text.

Uses DejaVu Sans when the system has it, otherwise Pillow's built-in font.
"""
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import settings

CARD_WIDTH = 1080
MARGIN = 64
BG_COLOR = (241, 236, 226)  # matches the frontend's --paper token
INK = (33, 29, 26)
ACCENT = (110, 42, 59)
RULE = (217, 208, 193)
MAX_HEIGHT = 16000          # keeps the file a sane size even for huge inputs
TRANSCRIPT_WORD_CAP = 1200


def _load_font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:  # very old Pillow without a sized default font
            return ImageFont.load_default()


def _wrap(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)
    return lines


def build_summary_image(
    title: str,
    summary: str | None,
    key_points: list[str],
    transcript: str | None = None,
    transcript_label: str = "FULL TRANSCRIPT",
    ai_insights: str | None = None,
    dates: list[str] | None = None,
    links: list[str] | None = None,
    notable_terms: list[str] | None = None,
) -> Path:
    font_title = _load_font(40, bold=True)
    font_meta = _load_font(20)
    font_h2 = _load_font(24, bold=True)
    font_body = _load_font(22)

    scratch = Image.new("RGB", (CARD_WIDTH, 10), BG_COLOR)
    measure = ImageDraw.Draw(scratch)
    content_width = CARD_WIDTH - 2 * MARGIN

    # Pass 1: lay everything out as a list of (kind, text) rows so the height is known up front.
    rows: list[tuple[str, str]] = [("title", title), ("meta", "Language: English"), ("rule", "")]

    def section(heading: str, body: str | None = None, bullets: list[str] | None = None):
        if not body and not bullets:
            return
        rows.append(("h2", heading))
        if body:
            for line in _wrap(body, font_body, content_width, measure):
                rows.append(("body", line))
        for item in bullets or []:
            for line in _wrap(f"-  {item}", font_body, content_width, measure):
                rows.append(("body", line))
        rows.append(("gap", ""))

    if transcript:
        words = transcript.split()
        shown = transcript
        if len(words) > TRANSCRIPT_WORD_CAP:
            shown = " ".join(words[:TRANSCRIPT_WORD_CAP]) + " ...\n(Shortened for the picture - the PDF and Word downloads have the complete text.)"
        section(transcript_label, body=shown)
    section("SUMMARY", body=summary)
    section("KEY POINTS", bullets=key_points[:8])
    section("AI INSIGHTS", body=ai_insights)
    if dates or links or notable_terms:
        rows.append(("h2", "HIGHLIGHTS"))
        for label, items in (("Dates", dates), ("Links", links), ("Notable terms", notable_terms)):
            if items:
                for line in _wrap(f"{label}: " + ", ".join(items), font_body, content_width, measure):
                    rows.append(("body", line))
        rows.append(("gap", ""))

    heights = {"title": 56, "meta": 40, "rule": 28, "h2": 36, "body": 30, "gap": 20}
    total = MARGIN * 2 + sum(heights[k] for k, _ in rows)
    total = min(total, MAX_HEIGHT)

    # Pass 2: draw.
    final = Image.new("RGB", (CARD_WIDTH, total), BG_COLOR)
    draw = ImageDraw.Draw(final)
    y = MARGIN
    for kind, text in rows:
        if y + heights[kind] > total - MARGIN // 2:
            break
        if kind == "title":
            draw.text((MARGIN, y), text, font=font_title, fill=INK)
        elif kind == "meta":
            draw.text((MARGIN, y), text, font=font_meta, fill=ACCENT)
        elif kind == "rule":
            draw.line([(MARGIN, y), (CARD_WIDTH - MARGIN, y)], fill=RULE, width=2)
        elif kind == "h2":
            draw.text((MARGIN, y), text, font=font_h2, fill=ACCENT)
        elif kind == "body":
            draw.text((MARGIN, y), text, font=font_body, fill=INK)
        y += heights[kind]

    report_id = uuid.uuid4().hex
    out_path = settings.storage_path / "reports" / f"{report_id}.jpg"
    final.save(str(out_path), "JPEG", quality=90)
    return out_path
