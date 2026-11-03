import os
from pathlib import Path
from typing import Any

from fpdf import FPDF

from worksheet_generator import LANGUAGES, QUESTION_TYPES, ValidationError, validate_worksheet_document


class PDFError(RuntimeError):
    pass


class WorksheetPDF(FPDF):
    footer_font = "Helvetica"

    def footer(self):
        self.set_y(-14)
        self.set_font(self.footer_font, size=8)
        self.set_text_color(100, 112, 103)
        self.cell(0, 8, f"AI Worksheet Generator  |  {self.page_no()}", align="C")


def _unicode_font_path() -> Path | None:
    configured = os.getenv("WORKSHEET_UNICODE_FONT", "").strip()
    candidates = [Path(configured)] if configured else []
    windows_directory = os.getenv("WINDIR", r"C:\Windows")
    candidates.extend(
        [
            Path(windows_directory) / "Fonts" / "Nirmala.ttf",
            Path(windows_directory) / "Fonts" / "NirmalaUI.ttf",
            Path(windows_directory) / "Fonts" / "mangal.ttf",
        ]
    )
    return next((path for path in candidates if path.is_file()), None)


def _language_labels(language: str) -> dict[str, str]:
    labels = {
        "en": {
            "student": "Student name",
            "grade": "Class / grade",
            "subject": "Subject",
            "topic": "Topic",
            "date": "Date",
            "instructions": "Instructions",
            "answer_key": "Answer key",
            "points": "points",
        },
        "hi": {
            "student": "विद्यार्थी का नाम",
            "grade": "कक्षा",
            "subject": "विषय",
            "topic": "विषय-वस्तु",
            "date": "तारीख",
            "instructions": "निर्देश",
            "answer_key": "उत्तर कुंजी",
            "points": "अंक",
        },
        "mr": {
            "student": "विद्यार्थ्याचे नाव",
            "grade": "इयत्ता",
            "subject": "विषय",
            "topic": "घटक",
            "date": "दिनांक",
            "instructions": "सूचना",
            "answer_key": "उत्तर सूची",
            "points": "गुण",
        },
    }
    return labels.get(language, labels["en"])


def _font_family(pdf: WorksheetPDF, language: str) -> str:
    if language == "en":
        return "Helvetica"
    font_path = _unicode_font_path()
    if font_path is None:
        raise PDFError(
            "A Devanagari font is required for Hindi or Marathi PDFs. Set WORKSHEET_UNICODE_FONT "
            "to a .ttf font file, such as C:\\Windows\\Fonts\\Nirmala.ttf."
        )
    try:
        pdf.add_font("WorksheetUnicode", fname=str(font_path))
        pdf.set_text_shaping(
            use_shaping_engine=True,
            direction="ltr",
            script="Deva",
            language=LANGUAGES[language].lower(),
        )
    except Exception as error:
        raise PDFError(
            "The configured font could not shape Hindi or Marathi text. Choose a Devanagari .ttf font."
        ) from error
    return "WorksheetUnicode"


def _write_text(pdf: WorksheetPDF, family: str, text: str, size: int = 11, bold: bool = False, height: int = 7):
    style = "B" if bold and family == "Helvetica" else ""
    pdf.set_font(family, style=style, size=size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, height, text)


def generate_pdf(data: Any, include_answer_key: bool = False) -> bytes:
    try:
        worksheet = validate_worksheet_document(data)
    except ValidationError as error:
        raise PDFError(str(error)) from None

    pdf = WorksheetPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=20)
    family = _font_family(pdf, worksheet["language"])
    pdf.footer_font = family
    labels = _language_labels(worksheet["language"])
    pdf.set_title(worksheet["title"])
    pdf.set_author("AI Worksheet Generator")
    pdf.add_page()

    pdf.set_text_color(31, 83, 59)
    _write_text(pdf, family, worksheet["title"], size=22, bold=True, height=12)
    pdf.set_text_color(38, 48, 41)
    _write_text(
        pdf,
        family,
        f"{labels['subject']}: {worksheet['subject']}    {labels['grade']}: {worksheet['grade']}",
        size=10,
    )
    _write_text(pdf, family, f"{labels['topic']}: {worksheet['topic']}", size=10)
    _write_text(pdf, family, f"{labels['student']}: ____________________    {labels['date']}: ______________", size=10)
    pdf.ln(3)

    if worksheet["instructions"]:
        _write_text(pdf, family, labels["instructions"], size=12, bold=True)
        _write_text(pdf, family, worksheet["instructions"])
        pdf.ln(3)

    for index, question in enumerate(worksheet["questions"], start=1):
        pdf.set_text_color(31, 83, 59)
        _write_text(
            pdf,
            family,
            f"{index}.  {question['question']}  ({question['points']} {labels['points']})",
            size=11,
            bold=True,
        )
        pdf.set_text_color(38, 48, 41)
        for option_index, option in enumerate(question["options"], start=1):
            _write_text(pdf, family, f"    {chr(64 + option_index)}. {option}", size=10)
        for pair_index, pair in enumerate(question["pairs"], start=1):
            _write_text(pdf, family, f"    {pair_index}. {pair['left']}    ______    {pair_index}.", size=10)
        pdf.ln(3)

    if include_answer_key and worksheet["include_answer_key"]:
        pdf.add_page()
        pdf.set_text_color(31, 83, 59)
        _write_text(pdf, family, labels["answer_key"], size=18, bold=True, height=10)
        pdf.set_text_color(38, 48, 41)
        for index, question in enumerate(worksheet["questions"], start=1):
            _write_text(pdf, family, f"{index}. {question['answer']}", size=11)
            if question["explanation"]:
                _write_text(pdf, family, f"   {question['explanation']}", size=10)
            pdf.ln(2)

    return bytes(pdf.output())