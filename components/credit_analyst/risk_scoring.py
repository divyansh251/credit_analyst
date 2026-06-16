"""Langflow component (pipeline stage 5): Risk Scoring & Recommendation.

Synthesises ratios, benchmark deviations, and policy findings into a risk
rating and recommendation. Uses Claude or Gemini when an API key is supplied;
otherwise falls back to the deterministic policy-driven mock engine.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.environ.get("CREDIT_ANALYST_ROOT") or os.getcwd()
if not os.path.isdir(os.path.join(_ROOT, "lib")):  # CLI/test fallback (skipped under Langflow exec)
    try:
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except (NameError, TypeError):  # __file__ missing or None (Langflow exec)  # pragma: no cover
        pass
# Langflow's component loader only runs module-level imports/assignments (not `if`/expr
# statements), so sys.path must be updated via assignment, not sys.path.insert(...).
sys.path = [_ROOT, *sys.path] if _ROOT not in sys.path else sys.path

from langflow.custom import Component
from langflow.io import DataInput, DropdownInput, MessageTextInput, Output, SecretStrInput
from langflow.schema import Data


class RiskScoringComponent(Component):
    display_name = "Risk Scoring"
    description = ("Synthesises analysis into a risk rating + recommendation via Claude "
                   "or Gemini (falls back to a deterministic engine when no API key is set).")
    icon = "gauge"
    name = "RiskScoring"

    inputs = [
        DataInput(name="bundle", display_name="Analysis Bundle"),
        DropdownInput(name="provider", display_name="LLM Provider",
                      options=["auto", "anthropic", "gemini"], value="auto",
                      info="Which LLM to use. 'auto' prefers Claude when both keys are set."),
        SecretStrInput(name="anthropic_api_key", display_name="Anthropic API Key",
                       info="Optional. Used when provider is 'anthropic' or 'auto'.",
                       required=False),
        SecretStrInput(name="gemini_api_key", display_name="Gemini API Key",
                       info="Optional. Used when provider is 'gemini' or 'auto'.",
                       required=False),
        MessageTextInput(name="model", display_name="Claude Model",
                         value="claude-opus-4-8", advanced=True),
        MessageTextInput(name="gemini_model", display_name="Gemini Model",
                         value="gemini-2.5-pro", advanced=True),
    ]
    outputs = [Output(name="bundle_out", display_name="Analysis Bundle", method="score")]

    def score(self) -> Data:
        from lib.scoring import score_risk

        anthropic_key = (self.anthropic_api_key or "").strip()
        gemini_key = (self.gemini_api_key or "").strip()
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
        if gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
        if (self.provider or "").strip():
            os.environ["LLM_PROVIDER"] = self.provider.strip()
        if (self.model or "").strip():
            os.environ["CLAUDE_MODEL"] = self.model.strip()
        if (self.gemini_model or "").strip():
            os.environ["GEMINI_MODEL"] = self.gemini_model.strip()

        bundle = dict(self.bundle.data)
        prefer_llm = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("GEMINI_API_KEY"))
        verdict = score_risk(
            bundle["application"], bundle["ratios"],
            bundle["benchmark"], bundle["policy"], prefer_llm=prefer_llm,
        )
        bundle["verdict"] = verdict
        self.status = (f"{verdict['risk_rating']} risk / {verdict['recommendation']} "
                       f"(engine: {verdict['engine']})")
        return Data(data=bundle)
