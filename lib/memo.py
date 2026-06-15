"""Memo generation (pipeline stage 6) — structured memo + PDF + JSON summary.

``build_memo`` assembles every upstream artifact into a single structured memo
dict (the JSON summary used for auditing / downstream systems). ``render_pdf``
lays that memo out as a professional credit memorandum PDF using reportlab.

Memo sections (per the brief):
    1. Executive Summary
    2. Applicant Overview
    3. Financial Analysis (multi-year ratio tables)
    4. Industry Comparison
    5. Policy Compliance Notes
    6. Risk Assessment
    7. Recommendation

Every memo is watermarked as an AI-generated *draft* requiring analyst sign-off.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

try:
    from ratios import format_ratio
except ImportError:  # package import
    from lib.ratios import format_ratio

RATING_COLORS = {
    "Low": colors.HexColor("#1b7f3b"),
    "Medium": colors.HexColor("#b8860b"),
    "High": colors.HexColor("#b3261e"),
}
SEVERITY_LABEL = {
    "pass": "Pass", "soft_fail": "Soft fail",
    "hard_fail": "HARD FAIL", "condition": "Condition",
}
SEVERITY_COLOR = {
    "pass": colors.HexColor("#1b7f3b"),
    "soft_fail": colors.HexColor("#b8860b"),
    "condition": colors.HexColor("#b8860b"),
    "hard_fail": colors.HexColor("#b3261e"),
}
HEADER_BG = colors.HexColor("#1f3b57")


# --------------------------------------------------------------------------- #
# Build the structured memo / JSON summary
# --------------------------------------------------------------------------- #
def build_memo(application: dict, parsed: dict, ratio_result: dict,
               benchmark_result: dict, policy_result: dict, verdict: dict) -> dict:
    applicant = application.get("applicant", {})
    loan = application.get("loan_request", {})
    app_id = application.get("application_id")

    return {
        "application_id": app_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": verdict.get("engine"),
        "retrieval_mode": policy_result.get("retrieval_mode"),
        "company_name": applicant.get("company_name"),
        "industry": applicant.get("industry"),
        "sector_code": benchmark_result.get("sector_code"),
        "loan_request": loan,
        "applicant": applicant,
        "risk_rating": verdict.get("risk_rating"),
        "recommendation": verdict.get("recommendation"),
        "reasoning": verdict.get("reasoning"),
        "key_factors": verdict.get("key_factors", []),
        "conditions": verdict.get("conditions", []),
        "years": ratio_result.get("years", []),
        "ratios": ratio_result.get("ratios", []),
        "benchmark": {
            "sector_name": benchmark_result.get("sector_name"),
            "comparisons": benchmark_result.get("comparisons", []),
            "flags": [c["label"] for c in benchmark_result.get("flags", [])],
        },
        "policy": {
            "summary": policy_result.get("summary", {}),
            "findings": policy_result.get("findings", []),
            "retrieved_context": policy_result.get("retrieved_context", []),
        },
        "financial_highlights": _financial_highlights(parsed),
        "data_quality_warnings": parsed.get("warnings", []),
    }


def _financial_highlights(parsed: dict) -> dict:
    income = parsed.get("income_statement", {})
    return {
        "years": parsed.get("years", []),
        "revenue": income.get("revenue", []),
        "gross_profit": income.get("gross_profit", []),
        "operating_income_ebit": income.get("ebit", []),
        "net_income": income.get("net_income", []),
    }


def write_json_summary(memo: dict, out_dir: str = "outputs") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"analysis_{memo['application_id']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(memo, fh, indent=2, default=str)
    return path


# --------------------------------------------------------------------------- #
# PDF rendering
# --------------------------------------------------------------------------- #
def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("MemoTitle", parent=ss["Title"], fontSize=20, spaceAfter=2,
                          textColor=HEADER_BG))
    ss.add(ParagraphStyle("Section", parent=ss["Heading2"], fontSize=13,
                          textColor=HEADER_BG, spaceBefore=14, spaceAfter=6))
    ss.add(ParagraphStyle("Body", parent=ss["BodyText"], fontSize=9.5, leading=13,
                          alignment=TA_LEFT))
    ss.add(ParagraphStyle("Small", parent=ss["BodyText"], fontSize=8, leading=11,
                          textColor=colors.HexColor("#555555")))
    ss.add(ParagraphStyle("MemoBullet", parent=ss["BodyText"], fontSize=9.5, leading=13,
                          leftIndent=12, bulletIndent=2))
    return ss


def _kv_table(rows, col0=2.0, col1=4.5):
    t = Table(rows, colWidths=[col0 * inch, col1 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
    ]))
    return t


def _money(v):
    if v is None:
        return "n/a"
    return f"({abs(v):,})" if v < 0 else f"{v:,}"


def _header_style(extra=None):
    base = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f6")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    return TableStyle(base + (extra or []))


def _summary_box(memo, ss):
    rating = memo["risk_rating"] or "n/a"
    color = RATING_COLORS.get(rating, colors.grey)
    loan = memo["loan_request"]
    data = [[
        Paragraph(f"<b>RISK RATING</b><br/><font size=14 color='{color.hexval()}'>"
                  f"<b>{rating.upper()}</b></font>", ss["Body"]),
        Paragraph(f"<b>RECOMMENDATION</b><br/><font size=11><b>{memo['recommendation']}</b></font>",
                  ss["Body"]),
        Paragraph(f"<b>FACILITY</b><br/>{_money(loan.get('amount_requested'))} "
                  f"{loan.get('currency','USD')}<br/>"
                  f"{loan.get('requested_term_months','?')} months", ss["Body"]),
    ]]
    t = Table(data, colWidths=[2.2 * inch, 2.7 * inch, 2.1 * inch])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, color),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7fa")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _ratio_section(memo, ss):
    years = memo["years"]
    header = ["Ratio", "Category"] + [str(y) for y in years]
    rows = [header]
    for r in memo["ratios"]:
        rows.append([r["label"], r["category"]] +
                    [format_ratio(r["values"].get(y), r["unit"]) for y in years])
    widths = [1.7 * inch, 1.2 * inch] + [0.95 * inch] * len(years)
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(_header_style([("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
    return t


def _highlights_table(memo, ss):
    h = memo["financial_highlights"]
    years = h["years"]
    labels = [("Revenue", "revenue"), ("Gross profit", "gross_profit"),
              ("Operating income (EBIT)", "operating_income_ebit"), ("Net income", "net_income")]
    rows = [["($ figures)"] + [str(y) for y in years]]
    for label, key in labels:
        series = h.get(key, [])
        rows.append([label] + [_money(series[i]) if i < len(series) else "n/a"
                               for i in range(len(years))])
    widths = [2.4 * inch] + [1.1 * inch] * len(years)
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(_header_style([("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
    return t


def _benchmark_table(memo, ss):
    header = ["Ratio", "Company", "Sector mean", "z-score", "Assessment"]
    rows = [header]
    style_extra = []
    for i, c in enumerate(memo["benchmark"]["comparisons"], start=1):
        rows.append([
            c["label"], format_ratio(c["value"], c["unit"]),
            format_ratio(c["mean"], c["unit"]), f"{c['z_score']:+.2f}",
            c["assessment"].replace("_", " "),
        ])
        col = {"strength": "#1b7f3b", "in_line": "#333333",
               "watch": "#b8860b", "concern": "#b3261e"}[c["assessment"]]
        style_extra.append(("TEXTCOLOR", (4, i), (4, i), colors.HexColor(col)))
    widths = [1.6 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch, 1.3 * inch]
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(_header_style([("ALIGN", (1, 0), (3, -1), "RIGHT")] + style_extra))
    return t


def _policy_table(memo, ss):
    header = ["Clause", "Area", "Status", "Detail"]
    rows = [header]
    style_extra = []
    for i, f in enumerate(memo["policy"]["findings"], start=1):
        rows.append([
            f["clause_id"], f["title"],
            SEVERITY_LABEL.get(f["severity"], f["severity"]),
            Paragraph(f["detail"], ss["Small"]),
        ])
        style_extra.append(("TEXTCOLOR", (2, i), (2, i), SEVERITY_COLOR.get(f["severity"], colors.black)))
        if f["severity"] == "hard_fail":
            style_extra.append(("FONT", (2, i), (2, i), "Helvetica-Bold", 8.5))
    widths = [0.7 * inch, 1.3 * inch, 0.9 * inch, 3.6 * inch]
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(_header_style([("VALIGN", (0, 0), (-1, -1), "TOP")] + style_extra))
    return t


def _bullets(items, ss):
    return [Paragraph(f"•&nbsp;&nbsp;{it}", ss["MemoBullet"]) for it in items]


def render_pdf(memo: dict, out_dir: str = "outputs") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"credit_memo_{memo['application_id']}.pdf")
    ss = _styles()
    doc = SimpleDocTemplate(
        path, pagesize=LETTER, title=f"Credit Memo — {memo['company_name']}",
        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    story = []

    # --- header ---
    story.append(Paragraph("Commercial Credit Memorandum", ss["MemoTitle"]))
    story.append(Paragraph(
        f"<b>{memo['company_name']}</b> &nbsp;|&nbsp; Application {memo['application_id']} "
        f"&nbsp;|&nbsp; {memo['industry']} ({memo['sector_code']})", ss["Body"]))
    gen = memo["generated_at"][:19].replace("T", " ")
    story.append(Paragraph(
        f"<font color='#b3261e'><b>AI-GENERATED DRAFT</b></font> — requires analyst review &amp; "
        f"sign-off &nbsp;|&nbsp; Generated {gen} UTC &nbsp;|&nbsp; Engine: {memo['engine']}",
        ss["Small"]))
    story.append(Spacer(1, 8))
    story.append(_summary_box(memo, ss))
    story.append(Spacer(1, 6))

    # --- 1. Executive Summary ---
    story.append(Paragraph("1. Executive Summary", ss["Section"]))
    story.append(Paragraph(memo["reasoning"], ss["Body"]))

    # --- 2. Applicant Overview ---
    story.append(Paragraph("2. Applicant Overview", ss["Section"]))
    a, loan = memo["applicant"], memo["loan_request"]
    story.append(_kv_table([
        ["Company", a.get("company_name", "")],
        ["Legal structure", f"{a.get('legal_structure','')} · founded {a.get('year_founded','')}"],
        ["Industry / sector", f"{a.get('industry','')} ({a.get('sector_code','')})"],
        ["Employees / HQ", f"{a.get('employees','')} · {a.get('headquarters','')}"],
        ["Facility requested", f"{_money(loan.get('amount_requested'))} {loan.get('currency','USD')} "
                               f"over {loan.get('requested_term_months','')} months"],
        ["Purpose", loan.get("purpose", "")],
        ["Loan type / collateral", f"{loan.get('loan_type','')} — {loan.get('collateral_offered','')}"],
    ]))

    # --- 3. Financial Analysis ---
    story.append(Paragraph("3. Financial Analysis", ss["Section"]))
    story.append(Paragraph("Selected financial highlights:", ss["Body"]))
    story.append(Spacer(1, 3))
    story.append(_highlights_table(memo, ss))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Computed ratios (multi-year):", ss["Body"]))
    story.append(Spacer(1, 3))
    story.append(_ratio_section(memo, ss))
    if memo["data_quality_warnings"]:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Data-quality notes: " +
                               "; ".join(memo["data_quality_warnings"]), ss["Small"]))

    # --- 4. Industry Comparison ---
    story.append(Paragraph("4. Industry Comparison", ss["Section"]))
    story.append(Paragraph(
        f"Most-recent-year ratios vs. {memo['benchmark']['sector_name']} sector benchmarks "
        f"(z-score = standard deviations from the sector mean):", ss["Body"]))
    story.append(Spacer(1, 3))
    story.append(_benchmark_table(memo, ss))

    # --- 5. Policy Compliance Notes ---
    story.append(Paragraph("5. Policy Compliance Notes", ss["Section"]))
    s = memo["policy"]["summary"]
    story.append(Paragraph(
        f"Evaluated against the internal credit policy: "
        f"<b>{s.get('hard_fails',0)}</b> hard fail(s), <b>{s.get('soft_fails',0)}</b> soft fail(s), "
        f"<b>{s.get('conditions',0)}</b> condition(s), <b>{s.get('passes',0)}</b> pass(es). "
        f"Retrieval mode: {memo['retrieval_mode']}.", ss["Body"]))
    story.append(Spacer(1, 3))
    if memo["policy"]["findings"]:
        story.append(_policy_table(memo, ss))

    # --- 6. Risk Assessment ---
    story.append(Paragraph("6. Risk Assessment", ss["Section"]))
    rating = memo["risk_rating"]
    rcolor = RATING_COLORS.get(rating, colors.grey).hexval()
    story.append(Paragraph(
        f"Overall risk rating: <font color='{rcolor}'><b>{rating}</b></font>. Key factors:", ss["Body"]))
    story.extend(_bullets(memo["key_factors"], ss))

    # --- 7. Recommendation ---
    story.append(Paragraph("7. Recommendation", ss["Section"]))
    story.append(Paragraph(f"<b>{memo['recommendation']}</b>", ss["Body"]))
    if memo["conditions"]:
        story.append(Spacer(1, 3))
        story.append(Paragraph("Conditions / required exceptions:", ss["Body"]))
        story.extend(_bullets(memo["conditions"], ss))

    # --- footer ---
    story.append(Spacer(1, 14))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Paragraph(
        "This memorandum is an AI-generated first draft produced by the Credit Analyst agent. "
        "All figures, policy interpretations, and recommendations must be independently verified "
        "and approved by a qualified credit analyst before any lending decision.", ss["Small"]))

    doc.build(story)
    return path


def generate_outputs(memo: dict, out_dir: str = "outputs") -> dict:
    """Write both the PDF memo and the JSON summary; return their paths."""
    return {
        "pdf": render_pdf(memo, out_dir),
        "json": write_json_summary(memo, out_dir),
    }


if __name__ == "__main__":
    import sys
    from parsing import parse_financials  # noqa: E402
    from ratios import compute_ratios  # noqa: E402
    from benchmarks import compare_to_benchmarks  # noqa: E402
    from policy import evaluate_policy  # noqa: E402
    from scoring import score_risk  # noqa: E402

    app_id = sys.argv[1] if len(sys.argv) > 1 else "1001"
    with open(f"samples/application_{app_id}.json", encoding="utf-8") as fh:
        application = json.load(fh)
    parsed = parse_financials(f"samples/financials_{app_id}.pdf")
    if not parsed.get("sector_code"):
        parsed["sector_code"] = application["applicant"].get("sector_code")
    ratios = compute_ratios(parsed)
    bench = compare_to_benchmarks(ratios, parsed["sector_code"])
    policy = evaluate_policy(application, parsed, ratios, bench)
    verdict = score_risk(application, ratios, bench, policy)
    memo = build_memo(application, parsed, ratios, bench, policy, verdict)
    out = generate_outputs(memo)
    print(f"Wrote:\n  {out['pdf']}\n  {out['json']}")
