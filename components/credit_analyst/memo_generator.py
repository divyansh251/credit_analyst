"""Langflow component (pipeline stage 6): Memo Generator.

Assembles the structured credit memo and renders both the PDF
(credit_memo_<id>.pdf) and the JSON summary (analysis_<id>.json) to the output
directory. Terminal node of the Credit Analyst flow.
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

_DEFAULT_OUT = os.path.join(_ROOT, "outputs")


class MemoGeneratorComponent(Component):
    display_name = "Memo Generator"
    description = "Renders the credit memo to PDF and writes the JSON analysis summary."
    icon = "file-output"
    name = "MemoGenerator"

    inputs = [
        DataInput(name="bundle", display_name="Analysis Bundle"),
        MessageTextInput(name="output_dir", display_name="Output Directory",
                         value=_DEFAULT_OUT, advanced=True),
    ]
    outputs = [Output(name="result", display_name="Result", method="generate")]

    def generate(self) -> Data:
        from lib.memo import build_memo, generate_outputs

        bundle = dict(self.bundle.data)
        out_dir = (self.output_dir or "").strip() or _DEFAULT_OUT
        memo = build_memo(
            bundle["application"], bundle["parsed"], bundle["ratios"],
            bundle["benchmark"], bundle["policy"], bundle["verdict"],
        )
        paths = generate_outputs(memo, out_dir)
        result = {
            "application_id": memo["application_id"],
            "company_name": memo["company_name"],
            "risk_rating": memo["risk_rating"],
            "recommendation": memo["recommendation"],
            "pdf_path": paths["pdf"],
            "json_path": paths["json"],
        }
        self.status = (f"{memo['company_name']}: {memo['risk_rating']} / "
                       f"{memo['recommendation']} -> {os.path.basename(paths['pdf'])}")
        return Data(data=result)
