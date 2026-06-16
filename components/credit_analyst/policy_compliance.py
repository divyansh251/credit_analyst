"""Langflow component (pipeline stage 4): Policy Compliance (RAG).

Embeds the credit-policy clauses into a local Chroma vector store, retrieves the
clauses relevant to the applicant's profile, and evaluates the deterministic
hard/soft policy thresholds — recording findings and cited clause text.
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
from langflow.io import BoolInput, DataInput, MessageTextInput, Output
from langflow.schema import Data

_DEFAULT_MD = os.path.join(_ROOT, "data", "policy", "credit_policy.md")
_DEFAULT_CHROMA = os.path.join(_ROOT, ".chroma")


class PolicyComplianceComponent(Component):
    display_name = "Policy Compliance (RAG)"
    description = "Retrieves relevant credit-policy clauses and evaluates compliance."
    icon = "shield-check"
    name = "PolicyCompliance"

    inputs = [
        DataInput(name="bundle", display_name="Analysis Bundle"),
        MessageTextInput(name="policy_md", display_name="Policy Markdown Path",
                         value=_DEFAULT_MD, advanced=True),
        MessageTextInput(name="persist_dir", display_name="Chroma Persist Dir",
                         value=_DEFAULT_CHROMA, advanced=True),
        BoolInput(name="use_vector", display_name="Use Vector Store (Chroma)",
                  value=True, advanced=True,
                  info="If off (or Chroma unavailable), falls back to keyword retrieval."),
    ]
    outputs = [Output(name="bundle_out", display_name="Analysis Bundle", method="evaluate")]

    def evaluate(self) -> Data:
        from lib.policy import PolicyStore, evaluate_policy

        bundle = dict(self.bundle.data)
        store = PolicyStore.build(
            md_path=(self.policy_md or "").strip() or _DEFAULT_MD,
            persist_dir=(self.persist_dir or "").strip() or _DEFAULT_CHROMA,
            prefer_vector=bool(self.use_vector),
        )
        bundle["policy"] = evaluate_policy(
            bundle["application"], bundle["parsed"],
            bundle["ratios"], bundle["benchmark"], store=store,
        )
        s = bundle["policy"]["summary"]
        self.status = (f"Policy ({bundle['policy']['retrieval_mode']}): "
                       f"{s['hard_fails']} hard, {s['soft_fails']} soft, {s['conditions']} cond")
        return Data(data=bundle)
