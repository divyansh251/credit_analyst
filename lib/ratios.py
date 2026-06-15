"""Financial ratio calculation (pipeline stage 2).

Consumes the canonical structure from ``lib.parsing`` and computes liquidity,
leverage, profitability, and efficiency ratios for every fiscal year present.

Output schema::

    {
        "most_recent_year": 2025,
        "years": [2025, 2024, 2023],
        "ratios": [
            {
                "name": "current_ratio",
                "label": "Current Ratio",
                "category": "Liquidity",
                "unit": "x",                 # "x" (multiple) or "%"
                "values": {2025: 1.90, 2024: 1.86, 2023: 1.78},
                "latest": 1.90,
            },
            ...
        ],
    }

Ratio names match the ``ratio`` column in the industry-benchmark CSV so the
benchmark comparator can join the two directly.
"""

from __future__ import annotations

from typing import Callable, Optional


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _get(statement: dict, key: str, year_index: int) -> Optional[float]:
    values = statement.get(key)
    if not values or year_index >= len(values):
        return None
    return values[year_index]


# Each definition: (name, label, category, unit, function(parsed, year_index) -> Optional[float])
# `unit` "x" => a multiple/ratio; "%" => stored as a fraction (0.32) and rendered as a percentage.
RATIO_DEFS: list[tuple[str, str, str, str, Callable]] = [
    # --- Liquidity ---
    ("current_ratio", "Current Ratio", "Liquidity", "x",
     lambda p, i: _safe_div(_get(p["balance_sheet"], "total_current_assets", i),
                            _get(p["balance_sheet"], "total_current_liabilities", i))),
    ("quick_ratio", "Quick Ratio", "Liquidity", "x",
     lambda p, i: _safe_div(
         (_get(p["balance_sheet"], "total_current_assets", i) or 0)
         - (_get(p["balance_sheet"], "inventory", i) or 0),
         _get(p["balance_sheet"], "total_current_liabilities", i))),
    # --- Leverage ---
    ("debt_to_equity", "Debt-to-Equity", "Leverage", "x",
     lambda p, i: _safe_div(
         (_get(p["balance_sheet"], "short_term_debt", i) or 0)
         + (_get(p["balance_sheet"], "long_term_debt", i) or 0),
         _get(p["balance_sheet"], "total_equity", i))),
    ("debt_to_assets", "Debt-to-Assets", "Leverage", "x",
     lambda p, i: _safe_div(_get(p["balance_sheet"], "total_liabilities", i),
                            _get(p["balance_sheet"], "total_assets", i))),
    ("interest_coverage", "Interest Coverage", "Leverage", "x",
     lambda p, i: _safe_div(_get(p["income_statement"], "ebit", i),
                            _get(p["income_statement"], "interest_expense", i))),
    # --- Profitability ---
    ("gross_margin", "Gross Margin", "Profitability", "%",
     lambda p, i: _safe_div(_get(p["income_statement"], "gross_profit", i),
                            _get(p["income_statement"], "revenue", i))),
    ("net_margin", "Net Margin", "Profitability", "%",
     lambda p, i: _safe_div(_get(p["income_statement"], "net_income", i),
                            _get(p["income_statement"], "revenue", i))),
    ("return_on_assets", "Return on Assets", "Profitability", "%",
     lambda p, i: _safe_div(_get(p["income_statement"], "net_income", i),
                            _get(p["balance_sheet"], "total_assets", i))),
    ("return_on_equity", "Return on Equity", "Profitability", "%",
     lambda p, i: _safe_div(_get(p["income_statement"], "net_income", i),
                            _get(p["balance_sheet"], "total_equity", i))),
    # --- Efficiency ---
    ("asset_turnover", "Asset Turnover", "Efficiency", "x",
     lambda p, i: _safe_div(_get(p["income_statement"], "revenue", i),
                            _get(p["balance_sheet"], "total_assets", i))),
    ("inventory_turnover", "Inventory Turnover", "Efficiency", "x",
     lambda p, i: _safe_div(_get(p["income_statement"], "cogs", i),
                            _get(p["balance_sheet"], "inventory", i))),
]

CATEGORY_ORDER = ["Liquidity", "Leverage", "Profitability", "Efficiency"]


def _round(value: Optional[float], unit: str) -> Optional[float]:
    if value is None:
        return None
    return round(value, 4) if unit == "%" else round(value, 2)


def compute_ratios(parsed: dict) -> dict:
    """Compute all defined ratios for each fiscal year in ``parsed``."""
    years = parsed.get("years", [])
    ratios = []
    for name, label, category, unit, fn in RATIO_DEFS:
        values = {}
        for i, year in enumerate(years):
            try:
                values[year] = _round(fn(parsed, i), unit)
            except Exception:
                values[year] = None
        latest = values.get(years[0]) if years else None
        ratios.append({
            "name": name,
            "label": label,
            "category": category,
            "unit": unit,
            "values": values,
            "latest": latest,
        })
    return {
        "most_recent_year": years[0] if years else None,
        "years": years,
        "ratios": ratios,
    }


def format_ratio(value: Optional[float], unit: str) -> str:
    """Human-readable rendering of a ratio value for tables/memos."""
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value * 100:.1f}%"
    return f"{value:.2f}x"


if __name__ == "__main__":
    import sys
    from parsing import parse_financials  # noqa: E402  (script-mode import)

    target = sys.argv[1] if len(sys.argv) > 1 else "samples/financials_1001.pdf"
    result = compute_ratios(parse_financials(target))
    print(f"Ratios for {target}  (most recent: {result['most_recent_year']})\n")
    current_cat = None
    for r in result["ratios"]:
        if r["category"] != current_cat:
            current_cat = r["category"]
            print(f"  [{current_cat}]")
        series = "  ".join(
            f"{y}:{format_ratio(r['values'][y], r['unit'])}" for y in result["years"]
        )
        print(f"    {r['label']:<22} {series}")
