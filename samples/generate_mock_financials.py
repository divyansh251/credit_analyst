"""Render the canonical figures in ``financial_data.py`` into mock financial
statement PDFs (one per applicant), laid out as labelled, parser-friendly tables.

Run:
    python samples/generate_mock_financials.py

Produces:
    samples/financials_1001.pdf
    samples/financials_1002.pdf

Each PDF contains three statements (Balance Sheet, Income Statement, Cash Flow),
each a table with a label column followed by one column per fiscal year, newest
first. The label text exactly matches the keys in ``financial_data.FINANCIALS``
so ``lib/parsing.py`` can map rows back to structured line items deterministically.
"""

from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Paragraph,
)

try:
    from financial_data import FINANCIALS
except ImportError:  # when imported as a package
    from samples.financial_data import FINANCIALS

HERE = os.path.dirname(os.path.abspath(__file__))


def _fmt(value: int) -> str:
    """Format a whole-dollar figure with thousands separators; parens for negatives."""
    if value < 0:
        return f"({abs(value):,})"
    return f"{value:,}"


def _statement_table(title: str, items: dict, years: list[int], styles) -> list:
    header = [title] + [str(y) for y in years]
    rows = [header]
    for label, values in items.items():
        rows.append([label] + [_fmt(v) for v in values])

    col_widths = [3.1 * inch] + [1.3 * inch] * len(years)
    table = Table(rows, colWidths=col_widths, hAlign="LEFT")

    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#1f3b57")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f6")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    # Bold the subtotal / total rows for readability (and to mimic a real statement).
    for i, label in enumerate(items.keys(), start=1):
        low = label.lower()
        if low.startswith("total") or low.startswith("net") or low.startswith("gross") \
                or "ebit" in low or low.startswith("pre-tax"):
            style.append(("FONT", (0, i), (-1, i), "Helvetica-Bold", 9))
            style.append(("LINEABOVE", (0, i), (-1, i), 0.4, colors.grey))
    table.setStyle(TableStyle(style))
    return [Paragraph(f"<b>{title}</b>", styles["Heading3"]), Spacer(1, 4), table, Spacer(1, 18)]


def build_pdf(app_id: str, record: dict) -> str:
    out_path = os.path.join(HERE, f"financials_{app_id}.pdf")
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        out_path, pagesize=LETTER,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        title=f"Financial Statements — {record['company_name']}",
    )

    story = []
    story.append(Paragraph(record["company_name"], styles["Title"]))
    story.append(Paragraph(
        f"Audited Financial Statements &nbsp;|&nbsp; Sector: {record['sector_code']} "
        f"&nbsp;|&nbsp; Application {app_id} &nbsp;|&nbsp; Figures in USD",
        styles["Normal"],
    ))
    story.append(Spacer(1, 18))

    years = record["years"]
    story += _statement_table("Balance Sheet", record["balance_sheet"], years, styles)
    story += _statement_table("Income Statement", record["income_statement"], years, styles)
    story += _statement_table("Cash Flow Statement", record["cash_flow"], years, styles)

    doc.build(story)
    return out_path


def main() -> None:
    for app_id, record in FINANCIALS.items():
        path = build_pdf(app_id, record)
        print(f"  wrote {os.path.relpath(path)}")


if __name__ == "__main__":
    print("Generating mock financial statement PDFs...")
    main()
    print("Done.")
