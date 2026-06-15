"""Industry benchmark comparison (pipeline stage 3).

Loads the industry-benchmark CSV, selects the row set for the applicant's
sector (falling back to the ``GEN`` general profile if the sector is unknown),
and compares each computed ratio's most-recent value against the sector mean
using a z-score (number of standard deviations from the mean).

Crucially, deviation is interpreted *directionally*: a current ratio far above
the mean is a strength, while a debt-to-equity far above the mean is a concern.
The ``higher_is_better`` flag in the CSV encodes this per ratio.

Assessment bands (by absolute z-score):
    |z| < 1.0                      -> "in_line"
    favorable & |z| >= 1.0         -> "strength"
    unfavorable & 1.0 <= |z| < 2.0 -> "watch"
    unfavorable & |z| >= 2.0       -> "concern"
"""

from __future__ import annotations

import csv
import os
from typing import Optional

DEFAULT_BENCHMARK_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "benchmarks", "industry_benchmarks.csv",
)

WATCH_THRESHOLD = 1.0   # z-score at which an unfavorable deviation becomes a watch
CONCERN_THRESHOLD = 2.0  # z-score at which an unfavorable deviation becomes a concern


def load_benchmarks(csv_path: str = DEFAULT_BENCHMARK_CSV) -> dict:
    """Load benchmarks into ``{sector_code: {ratio_name: {...}}}``."""
    table: dict[str, dict[str, dict]] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sector = row["sector_code"].strip().upper()
            table.setdefault(sector, {})[row["ratio"].strip()] = {
                "sector_name": row["sector_name"].strip(),
                "mean": float(row["mean"]),
                "std_dev": float(row["std_dev"]),
                "higher_is_better": bool(int(row["higher_is_better"])),
                "unit": row.get("unit", "").strip(),
            }
    return table


def _assess(z: float, higher_is_better: bool) -> tuple[str, str, bool]:
    """Return (direction, assessment, favorable)."""
    if z > 0:
        direction = "above"
    elif z < 0:
        direction = "below"
    else:
        direction = "in_line"

    favorable = (z >= 0 and higher_is_better) or (z <= 0 and not higher_is_better)
    magnitude = abs(z)

    if magnitude < WATCH_THRESHOLD:
        assessment = "in_line"
    elif favorable:
        assessment = "strength"
    elif magnitude < CONCERN_THRESHOLD:
        assessment = "watch"
    else:
        assessment = "concern"
    return direction, assessment, favorable


def compare_to_benchmarks(
    ratio_result: dict,
    sector_code: Optional[str],
    csv_path: str = DEFAULT_BENCHMARK_CSV,
) -> dict:
    """Compare most-recent ratio values to the sector benchmarks.

    Returns::

        {
            "sector_code": "MFG",
            "sector_name": "Manufacturing",
            "comparisons": [ {ratio, label, value, mean, std_dev, z_score,
                              direction, assessment, favorable, higher_is_better}, ...],
            "flags": [ <comparisons where assessment in {"watch","concern"}> ],
        }
    """
    table = load_benchmarks(csv_path)
    sector = (sector_code or "GEN").strip().upper()
    if sector not in table:
        sector = "GEN"
    sector_benchmarks = table[sector]
    sector_name = next(iter(sector_benchmarks.values()))["sector_name"] if sector_benchmarks else sector

    comparisons = []
    for r in ratio_result.get("ratios", []):
        bench = sector_benchmarks.get(r["name"])
        value = r.get("latest")
        if bench is None or value is None:
            continue
        std = bench["std_dev"] or 1e-9
        z = (value - bench["mean"]) / std
        direction, assessment, favorable = _assess(z, bench["higher_is_better"])
        comparisons.append({
            "ratio": r["name"],
            "label": r["label"],
            "category": r["category"],
            "unit": r["unit"],
            "value": value,
            "mean": bench["mean"],
            "std_dev": bench["std_dev"],
            "z_score": round(z, 2),
            "direction": direction,
            "assessment": assessment,
            "favorable": favorable,
            "higher_is_better": bench["higher_is_better"],
        })

    flags = [c for c in comparisons if c["assessment"] in ("watch", "concern")]
    return {
        "sector_code": sector,
        "sector_name": sector_name,
        "comparisons": comparisons,
        "flags": flags,
    }


if __name__ == "__main__":
    import sys
    from parsing import parse_financials  # noqa: E402
    from ratios import compute_ratios, format_ratio  # noqa: E402

    target = sys.argv[1] if len(sys.argv) > 1 else "samples/financials_1001.pdf"
    sector = sys.argv[2] if len(sys.argv) > 2 else None

    parsed = parse_financials(target)
    sector = sector or parsed.get("sector_code")
    ratios = compute_ratios(parsed)
    result = compare_to_benchmarks(ratios, sector)

    print(f"Benchmark comparison for {target}  "
          f"(sector {result['sector_code']} / {result['sector_name']})\n")
    icon = {"in_line": "  ", "strength": "++", "watch": " !", "concern": "!!"}
    for c in result["comparisons"]:
        print(f"  {icon[c['assessment']]}  {c['label']:<20} "
              f"value={format_ratio(c['value'], c['unit']):>8}  "
              f"mean={format_ratio(c['mean'], c['unit']):>8}  "
              f"z={c['z_score']:+.2f}  -> {c['assessment']}")
    print(f"\n{len(result['flags'])} flag(s): "
          f"{', '.join(f['label'] for f in result['flags']) or 'none'}")
