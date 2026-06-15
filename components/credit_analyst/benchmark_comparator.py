"""Langflow component (pipeline stage 3): Benchmark Comparator.

Compares the most-recent-year ratios against the applicant's sector benchmarks
(directional z-scores) and records the flagged deviations on the bundle.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.environ.get("CREDIT_ANALYST_ROOT")
if not _ROOT:
    try:
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:  # pragma: no cover
        _ROOT = os.getcwd()
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from langflow.custom import Component
from langflow.io import DataInput, MessageTextInput, Output
from langflow.schema import Data

_DEFAULT_CSV = os.path.join(_ROOT, "data", "benchmarks", "industry_benchmarks.csv")


class BenchmarkComparatorComponent(Component):
    display_name = "Benchmark Comparator"
    description = "Flags ratios deviating from industry/sector benchmarks (z-score)."
    icon = "trending-up"
    name = "BenchmarkComparator"

    inputs = [
        DataInput(name="bundle", display_name="Analysis Bundle"),
        MessageTextInput(
            name="benchmark_csv", display_name="Benchmark CSV Path",
            value=_DEFAULT_CSV, advanced=True),
    ]
    outputs = [Output(name="bundle_out", display_name="Analysis Bundle", method="compare")]

    def compare(self) -> Data:
        from lib.benchmarks import compare_to_benchmarks

        bundle = dict(self.bundle.data)
        sector = bundle["parsed"].get("sector_code")
        csv_path = (self.benchmark_csv or "").strip() or _DEFAULT_CSV
        bundle["benchmark"] = compare_to_benchmarks(bundle["ratios"], sector, csv_path)
        flags = len(bundle["benchmark"]["flags"])
        self.status = (f"Sector {bundle['benchmark']['sector_code']}: "
                       f"{flags} ratio(s) flagged vs benchmark")
        return Data(data=bundle)
