"""Risk scoring & recommendation (pipeline stage 5).

Synthesises the ratio analysis, benchmark deviations, and policy findings into:

    * a risk rating       -> "Low" | "Medium" | "High"
    * a recommendation    -> "Approve" | "Approve with conditions"
                             | "Decline" | "Refer to senior analyst"
    * narrative reasoning, key factors, and (where relevant) conditions.

Backends:

* **Claude** (used when ``ANTHROPIC_API_KEY`` is set) — sends the pre-digested
  evidence as JSON and asks ``claude-opus-4-8`` for a structured JSON verdict.
  The arithmetic/threshold work is already done deterministically upstream, so
  the model reasons over facts rather than parsing raw statements.
* **Gemini** (used when ``GEMINI_API_KEY`` is set) — same prompt/contract via
  Google's ``gemini-2.5-pro``.
* **Mock** (offline fallback) — a deterministic engine that applies the policy's
  own Section-8 rating guidelines. Lets the whole pipeline produce a memo with
  no API key, and makes tests reproducible.

All backends return the same schema, so downstream memo rendering is identical.

Provider selection (``score_risk``) honours the ``LLM_PROVIDER`` env var
(``auto`` | ``anthropic`` | ``gemini``). In ``auto`` (the default) Claude wins
when both keys are present; otherwise whichever key is set is used. Any LLM
failure falls back to the deterministic mock engine.
"""

from __future__ import annotations

import json
import os
from typing import Optional

RISK_LOW, RISK_MEDIUM, RISK_HIGH = "Low", "Medium", "High"
REC_APPROVE = "Approve"
REC_CONDITIONS = "Approve with conditions"
REC_DECLINE = "Decline"
REC_REFER = "Refer to senior analyst"

DEFAULT_CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
# Backwards-compatible alias (older callers imported DEFAULT_MODEL).
DEFAULT_MODEL = DEFAULT_CLAUDE_MODEL


# --------------------------------------------------------------------------- #
# Evidence assembly (shared by both backends)
# --------------------------------------------------------------------------- #
def build_evidence(application: dict, ratio_result: dict,
                   benchmark_result: dict, policy_result: dict) -> dict:
    """Compact, LLM-ready summary of all upstream analysis."""
    applicant = application.get("applicant", {})
    loan = application.get("loan_request", {})
    latest_ratios = {
        r["name"]: r["latest"] for r in ratio_result.get("ratios", [])
    }
    return {
        "applicant": {
            "company": applicant.get("company_name"),
            "industry": applicant.get("industry"),
            "sector_code": applicant.get("sector_code"),
            "years_in_business": applicant.get("year_founded"),
        },
        "loan_request": {
            "amount": loan.get("amount_requested"),
            "purpose": loan.get("purpose"),
            "term_months": loan.get("requested_term_months"),
            "type": loan.get("loan_type"),
            "collateral": loan.get("collateral_offered"),
        },
        "latest_ratios": latest_ratios,
        "benchmark_flags": [
            {"ratio": c["label"], "value": c["value"], "mean": c["mean"],
             "z_score": c["z_score"], "assessment": c["assessment"]}
            for c in benchmark_result.get("flags", [])
        ],
        "benchmark_strengths": [
            c["label"] for c in benchmark_result.get("comparisons", [])
            if c["assessment"] == "strength"
        ],
        "policy_summary": policy_result.get("summary", {}),
        "policy_findings": [
            {"clause": f["clause_id"], "title": f["title"],
             "severity": f["severity"], "detail": f["detail"]}
            for f in policy_result.get("findings", [])
            if f["severity"] != "pass"
        ],
    }


# --------------------------------------------------------------------------- #
# Deterministic mock backend
# --------------------------------------------------------------------------- #
def score_mock(evidence: dict) -> dict:
    """Deterministic rating per policy Section-8 guidelines."""
    summary = evidence.get("policy_summary", {})
    hard = summary.get("hard_fails", 0)
    soft = summary.get("soft_fails", 0)
    conditions = summary.get("conditions", 0)
    findings = evidence.get("policy_findings", [])
    flags = evidence.get("benchmark_flags", [])
    strengths = evidence.get("benchmark_strengths", [])

    concerns = [f for f in flags if f["assessment"] == "concern"]

    # --- rating & recommendation (CP-8) ---
    if hard >= 1:
        rating = RISK_HIGH
        # Two-year loss / multiple hard fails -> decline; otherwise cap at refer.
        if hard >= 2 or any("4.2" in f["clause"] for f in findings):
            recommendation = REC_DECLINE
        else:
            recommendation = REC_REFER
    elif soft >= 2 and conditions == 0:
        rating = RISK_HIGH
        recommendation = REC_REFER
    elif soft >= 1 or conditions >= 1 or len(concerns) >= 1:
        rating = RISK_MEDIUM
        recommendation = REC_CONDITIONS
    else:
        rating = RISK_LOW
        recommendation = REC_APPROVE

    # --- key factors ---
    key_factors: list[str] = []
    for f in findings:
        if f["severity"] in ("hard_fail", "soft_fail", "condition"):
            key_factors.append(f["detail"])
    for s in strengths:
        key_factors.append(f"{s} compares favorably to the sector benchmark.")
    if not key_factors:
        key_factors.append("All evaluated ratios meet policy thresholds and sit at or above sector norms.")

    # --- conditions list (for 'approve with conditions') ---
    conditions_list = [
        f["detail"] for f in findings if f["severity"] in ("condition", "soft_fail")
    ]

    # --- narrative reasoning ---
    company = evidence.get("applicant", {}).get("company")
    parts = [f"{company} is assessed as {rating.lower()} risk."]
    if hard:
        parts.append(
            f"The application breaches {hard} hard policy threshold(s), which under CP-8.4 "
            f"caps the recommendation at referral and precludes automatic approval."
        )
    if soft or conditions:
        parts.append(
            f"There are {soft} soft fail(s) and {conditions} item(s) requiring conditions or "
            f"senior review, each of which must be documented as an exception per CP-7.2."
        )
    if strengths:
        parts.append("Offsetting strengths: " + ", ".join(strengths) + ".")
    if rating == RISK_LOW:
        parts.append("No policy exceptions are required and the credit may proceed on standard terms.")
    reasoning = " ".join(parts)

    return {
        "engine": "mock",
        "risk_rating": rating,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "key_factors": key_factors,
        "conditions": conditions_list,
    }


# --------------------------------------------------------------------------- #
# LLM backends (shared prompt + parsing)
# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = (
    "You are a senior commercial credit analyst. You are given pre-computed, "
    "verified financial ratios, industry-benchmark deviations, and deterministic "
    "credit-policy findings (the arithmetic and threshold checks are already done "
    "and are authoritative). Synthesise them into a risk rating and recommendation. "
    "Do not recompute ratios. Respect these hard rules: any policy hard_fail caps "
    "the recommendation at 'Refer to senior analyst' and may never be 'Approve'. "
    "Return ONLY a JSON object with keys: risk_rating (Low|Medium|High), "
    "recommendation (Approve|Approve with conditions|Decline|Refer to senior analyst), "
    "reasoning (string), key_factors (array of strings), conditions (array of strings)."
)


def _user_prompt(evidence: dict) -> str:
    return ("Here is the analysis evidence as JSON. Produce the verdict JSON.\n\n"
            + json.dumps(evidence, indent=2))


def _parse_verdict(text: str, engine: str) -> dict:
    """Parse a model's JSON reply into the verdict schema; tolerate code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]
    verdict = json.loads(text)
    verdict["engine"] = engine
    verdict.setdefault("key_factors", [])
    verdict.setdefault("conditions", [])
    return verdict


def score_with_claude(evidence: dict, model: str = DEFAULT_CLAUDE_MODEL,
                      api_key: Optional[str] = None) -> dict:
    """Call Claude for the risk verdict; raises on any API/parse failure."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=1500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(evidence)}],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    return _parse_verdict(text, f"claude:{model}")


def score_with_gemini(evidence: dict, model: str = DEFAULT_GEMINI_MODEL,
                      api_key: Optional[str] = None) -> dict:
    """Call Gemini for the risk verdict; raises on any API/parse failure."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=model,
        contents=_user_prompt(evidence),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=1500,
            response_mime_type="application/json",
        ),
    )
    return _parse_verdict(response.text or "", f"gemini:{model}")


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def select_provider() -> Optional[str]:
    """Resolve which LLM backend to use from env, or None for the mock engine.

    ``LLM_PROVIDER`` (auto|anthropic|gemini) picks the backend; ``auto`` (default)
    prefers Claude when both keys are set. Returns None when the requested/usable
    provider has no API key configured.
    """
    preference = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))

    if preference == "anthropic":
        return "anthropic" if has_anthropic else None
    if preference == "gemini":
        return "gemini" if has_gemini else None
    # auto
    if has_anthropic:
        return "anthropic"
    if has_gemini:
        return "gemini"
    return None


_LLM_BACKENDS = {
    "anthropic": score_with_claude,
    "gemini": score_with_gemini,
}


def score_risk(application: dict, ratio_result: dict, benchmark_result: dict,
               policy_result: dict, prefer_llm: bool = True) -> dict:
    """Score risk via the selected LLM when a key is present, else the mock."""
    evidence = build_evidence(application, ratio_result, benchmark_result, policy_result)
    provider = select_provider() if prefer_llm else None
    if provider:
        try:
            verdict = _LLM_BACKENDS[provider](evidence)
            verdict["evidence"] = evidence
            return verdict
        except Exception as exc:
            print(f"[scoring] {provider} call failed ({exc!r}); falling back to mock engine")
    verdict = score_mock(evidence)
    verdict["evidence"] = evidence
    return verdict


if __name__ == "__main__":
    import sys
    from parsing import parse_financials  # noqa: E402
    from ratios import compute_ratios  # noqa: E402
    from benchmarks import compare_to_benchmarks  # noqa: E402
    from policy import evaluate_policy  # noqa: E402

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
    print(f"Application {app_id}  (engine: {verdict['engine']})")
    print(f"  Risk rating:    {verdict['risk_rating']}")
    print(f"  Recommendation: {verdict['recommendation']}\n")
    print(f"  Reasoning: {verdict['reasoning']}\n")
    print("  Key factors:")
    for kf in verdict["key_factors"]:
        print(f"    - {kf}")
    if verdict["conditions"]:
        print("  Conditions:")
        for c in verdict["conditions"]:
            print(f"    - {c}")
