"""Langflow component (pipeline stage 5): Risk Scoring & Recommendation.

Synthesises ratios, benchmark deviations, and policy findings into a risk
rating and recommendation. Uses Claude when an API key is supplied; otherwise
falls back to the deterministic policy-driven mock engine.
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
from langflow.io import DataInput, MessageTextInput, Output, SecretStrInput
from langflow.schema import Data


class RiskScoringComponent(Component):
    display_name = "Risk Scoring"
    description = ("Synthesises analysis into a risk rating + recommendation via Claude "
                   "(falls back to a deterministic engine when no API key is set).")
    icon = "gauge"
    name = "RiskScoring"

    inputs = [
        DataInput(name="bundle", display_name="Analysis Bundle"),
        SecretStrInput(name="anthropic_api_key", display_name="Anthropic API Key",
                       info="Optional. If empty, uses the deterministic mock engine.",
                       required=False),
        MessageTextInput(name="model", display_name="Claude Model",
                         value="claude-opus-4-8", advanced=True),
    ]
    outputs = [Output(name="bundle_out", display_name="Analysis Bundle", method="score")]

    def score(self) -> Data:
        from lib.scoring import score_risk

        key = (self.anthropic_api_key or "").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        if (self.model or "").strip():
            os.environ["CLAUDE_MODEL"] = self.model.strip()

        bundle = dict(self.bundle.data)
        prefer_llm = bool(key) or bool(os.environ.get("ANTHROPIC_API_KEY"))
        verdict = score_risk(
            bundle["application"], bundle["ratios"],
            bundle["benchmark"], bundle["policy"], prefer_llm=prefer_llm,
        )
        bundle["verdict"] = verdict
        self.status = (f"{verdict['risk_rating']} risk / {verdict['recommendation']} "
                       f"(engine: {verdict['engine']})")
        return Data(data=bundle)
