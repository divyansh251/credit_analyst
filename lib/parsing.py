"""Statement ingestion & parsing (pipeline stage 1).

Extracts structured financial line items from an uploaded financial-statements
file (PDF via ``pdfplumber``, or Excel via ``openpyxl``) into a clean,
canonical dict structure that the downstream ratio engine consumes.

The output schema is::

    {
        "company_name": "Apex Precision Components, Inc.",   # best-effort
        "sector_code":  "MFG",                               # best-effort
        "years":        [2025, 2024, 2023],                  # newest first
        "balance_sheet":     {canonical_key: [v_newest, ...], ...},
        "income_statement":  {canonical_key: [v_newest, ...], ...},
        "cash_flow":         {canonical_key: [v_newest, ...], ...},
        "warnings":     ["balance sheet does not balance for 2024", ...],
    }

Parsing is intentionally label-driven and deterministic: each row's leading
text is normalised and looked up in ``LABEL_MAP``. This keeps the mock-data
demo reproducible while still exercising a real PDF-text extraction path.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# canonical line-item key  ->  (statement, list of accepted display labels)
# The first label is the canonical display name; others are common synonyms so
# the parser tolerates mild wording differences across statement formats.
_FIELD_LABELS: dict[str, tuple[str, list[str]]] = {
    # --- balance sheet ---
    "cash": ("balance_sheet", ["cash and cash equivalents", "cash"]),
    "accounts_receivable": ("balance_sheet", ["accounts receivable", "trade receivables"]),
    "inventory": ("balance_sheet", ["inventory", "inventories"]),
    "other_current_assets": ("balance_sheet", ["other current assets"]),
    "total_current_assets": ("balance_sheet", ["total current assets"]),
    "ppe_net": ("balance_sheet", ["property, plant and equipment, net", "net ppe", "fixed assets, net"]),
    "other_non_current_assets": ("balance_sheet", ["other non-current assets", "other noncurrent assets"]),
    "total_assets": ("balance_sheet", ["total assets"]),
    "accounts_payable": ("balance_sheet", ["accounts payable", "trade payables"]),
    "short_term_debt": ("balance_sheet", ["short-term debt", "short term debt", "current portion of debt"]),
    "other_current_liabilities": ("balance_sheet", ["other current liabilities"]),
    "total_current_liabilities": ("balance_sheet", ["total current liabilities"]),
    "long_term_debt": ("balance_sheet", ["long-term debt", "long term debt"]),
    "total_liabilities": ("balance_sheet", ["total liabilities"]),
    "total_equity": ("balance_sheet", ["total shareholders equity", "total equity", "shareholders' equity"]),
    "total_liabilities_and_equity": ("balance_sheet", ["total liabilities and equity"]),
    # --- income statement ---
    "revenue": ("income_statement", ["revenue", "net sales", "total revenue"]),
    "cogs": ("income_statement", ["cost of goods sold", "cost of sales", "cogs"]),
    "gross_profit": ("income_statement", ["gross profit"]),
    "operating_expenses": ("income_statement", ["operating expenses", "sg&a", "selling, general and administrative"]),
    "ebit": ("income_statement", ["operating income (ebit)", "operating income", "ebit"]),
    "interest_expense": ("income_statement", ["interest expense"]),
    "pre_tax_income": ("income_statement", ["pre-tax income", "income before taxes", "pretax income"]),
    "income_tax": ("income_statement", ["income tax expense", "income taxes", "provision for income taxes"]),
    "net_income": ("income_statement", ["net income", "net profit", "net earnings"]),
    # --- cash flow ---
    "cfo": ("cash_flow", ["cash flow from operations", "operating cash flow", "net cash from operating activities"]),
    "cfi": ("cash_flow", ["cash flow from investing", "net cash from investing activities"]),
    "cff": ("cash_flow", ["cash flow from financing", "net cash from financing activities"]),
    "net_change_in_cash": ("cash_flow", ["net change in cash", "net increase in cash"]),
}

# normalised label  ->  (canonical_key, statement)
LABEL_MAP: dict[str, tuple[str, str]] = {}
for _key, (_stmt, _labels) in _FIELD_LABELS.items():
    for _lbl in _labels:
        LABEL_MAP[_lbl] = (_key, _stmt)

# A numeric token: optional sign / parens, must start with a digit.
# Parentheses denote a negative (accounting convention).
_NUM_RE = re.compile(r"\(?-?\d[\d,]*\)?")
_YEAR_RE = re.compile(r"^\d{4}$")


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(":").lower()


def _parse_number(token: str) -> int:
    negative = token.startswith("(") and token.endswith(")")
    cleaned = token.strip("()").replace(",", "")
    if cleaned in ("", "-"):
        return 0
    value = int(cleaned)
    return -value if negative else value


def _looks_like_year(token: str) -> bool:
    t = token.strip("()")
    return bool(_YEAR_RE.match(t)) and 1990 <= int(t) <= 2100


def _split_label_and_numbers(line: str) -> tuple[str, list[int]]:
    """Return (leading label text, [numeric values]) for a statement row."""
    match = _NUM_RE.search(line)
    if not match:
        return line.strip(), []
    label = line[: match.start()].strip()
    numbers = [_parse_number(tok) for tok in _NUM_RE.findall(line[match.start():])]
    return label, numbers


def _detect_years(lines: list[str]) -> list[int]:
    for line in lines:
        tokens = line.split()
        years = [int(t) for t in tokens if _looks_like_year(t)]
        if len(years) >= 2 and len(years) == len([t for t in tokens if _NUM_RE.fullmatch(t)]):
            return years
    # Fallback: scan the whole document for the longest run of year tokens.
    for line in lines:
        years = [int(t) for t in _NUM_RE.findall(line) if _looks_like_year(t)]
        if len(years) >= 2:
            return years
    return []


def _extract_header_meta(lines: list[str]) -> tuple[Optional[str], Optional[str]]:
    company = lines[0].strip() if lines else None
    sector = None
    for line in lines[:6]:
        m = re.search(r"sector:\s*([A-Za-z]{2,5})", line, re.IGNORECASE)
        if m:
            sector = m.group(1).upper()
            break
    return company, sector


def _statements_from_lines(lines: list[str], years: list[int]) -> dict:
    out: dict[str, dict[str, list[int]]] = {
        "balance_sheet": {},
        "income_statement": {},
        "cash_flow": {},
    }
    n = len(years)
    for line in lines:
        label_text, numbers = _split_label_and_numbers(line)
        key_info = LABEL_MAP.get(_normalize_label(label_text))
        if not key_info or not numbers:
            continue
        canonical_key, statement = key_info
        # Take the first n numbers (newest-first), padding if a value is missing.
        values = numbers[:n] + [0] * max(0, n - len(numbers))
        out[statement][canonical_key] = values
    return out


def _balance_warnings(balance_sheet: dict, years: list[int]) -> list[str]:
    warnings: list[str] = []
    ta = balance_sheet.get("total_assets")
    tle = balance_sheet.get("total_liabilities_and_equity")
    if ta and tle:
        for i, year in enumerate(years):
            if i < len(ta) and i < len(tle) and abs(ta[i] - tle[i]) > 1:
                warnings.append(
                    f"Balance sheet does not balance for {year}: "
                    f"assets {ta[i]:,} vs liabilities+equity {tle[i]:,}"
                )
    return warnings


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def parse_pdf(path: str) -> dict:
    """Parse a financial-statements PDF into the canonical structure."""
    import pdfplumber

    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    return _build_result(lines)


def parse_excel(path: str) -> dict:
    """Parse a financial-statements Excel workbook into the canonical structure.

    Expects a layout with a header row containing fiscal years and subsequent
    rows of ``[label, value, value, ...]`` across one or more sheets.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                lines.append(" ".join(cells))
    return _build_result(lines)


def parse_financials(path: str) -> dict:
    """Dispatch on file extension and parse into the canonical structure."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(path)
    if ext in (".xlsx", ".xlsm", ".xls"):
        return parse_excel(path)
    raise ValueError(f"Unsupported financials file type: {ext!r} ({path})")


def _build_result(lines: list[str]) -> dict:
    years = _detect_years(lines)
    company, sector = _extract_header_meta(lines)
    statements = _statements_from_lines(lines, years)
    result = {
        "company_name": company,
        "sector_code": sector,
        "years": years,
        **statements,
        "warnings": _balance_warnings(statements["balance_sheet"], years),
    }
    return result


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "samples/financials_1001.pdf"
    parsed = parse_financials(target)
    print(json.dumps(parsed, indent=2))
    print(f"\nParsed {len(parsed['years'])} year(s): {parsed['years']}")
    print(f"Balance-sheet items: {len(parsed['balance_sheet'])}, "
          f"income items: {len(parsed['income_statement'])}, "
          f"cash-flow items: {len(parsed['cash_flow'])}")
    if parsed["warnings"]:
        print("WARNINGS:", parsed["warnings"])
    else:
        print("No data-quality warnings.")
