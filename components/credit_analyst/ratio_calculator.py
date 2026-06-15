"""Langflow component (pipeline stage 2): Ratio Calculator.

Computes liquidity, leverage, profitability, and efficiency ratios for every
fiscal year in the parsed statements and adds them to the analysis bundle.
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
from langflow.io import DataInput, Output
from langflow.schema import Data


class RatioCalculatorComponent(Component):
    display_name = "Ratio Calculator"
    description = "Computes liquidity, leverage, profitability and efficiency ratios."
    icon = "calculator"
    name = "RatioCalculator"

    inputs = [DataInput(name="bundle", display_name="Analysis Bundle")]
    outputs = [Output(name="bundle_out", display_name="Analysis Bundle", method="calculate")]

    def calculate(self) -> Data:
        from lib.ratios import compute_ratios

        bundle = dict(self.bundle.data)
        bundle["ratios"] = compute_ratios(bundle["parsed"])
        n = len(bundle["ratios"]["ratios"])
        self.status = f"Computed {n} ratios for {bundle['ratios']['most_recent_year']}"
        return Data(data=bundle)
