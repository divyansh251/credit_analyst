"""Credit-policy compliance (pipeline stage 4) — RAG retrieval + rule evaluation.

This stage has two complementary halves:

1. **Retrieval (RAG).** The policy markdown is chunked at the clause level
   (each ``CP-x.y`` bullet) and embedded into a local Chroma vector store
   (``PolicyStore``). Given a query built from the applicant's profile and its
   flagged ratios, we retrieve the most relevant policy clauses to cite.

   If ``chromadb`` is unavailable (or model download fails offline), the store
   transparently falls back to a deterministic keyword retriever so the pipeline
   still runs end-to-end.

2. **Evaluation (deterministic rules).** Because the policy encodes explicit
   numeric thresholds, we evaluate hard/soft fails programmatically rather than
   trusting an LLM to do arithmetic. Each finding cites the exact clause text
   (looked up by id), giving auditable, reproducible compliance results. The
   retrieved RAG context is attached as supporting material for the LLM step.
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Optional

DEFAULT_POLICY_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "policy", "credit_policy.md",
)
DEFAULT_CHROMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".chroma"
)

_CLAUSE_RE = re.compile(r"^\s*-\s*\*\*(CP-[\d.]+)\*\*\s*(.*)")
_SECTION_RE = re.compile(r"^#{2,3}\s+(.*)")
_STOPWORDS = set("the a an and or of to for is are be by in on with at from as "
                 "must may be below above between under over each any per".split())


def _strip_md(text: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_policy_clauses(md_path: str = DEFAULT_POLICY_MD) -> list[dict]:
    """Chunk the policy markdown into ``[{clause_id, section, text}]``."""
    clauses: list[dict] = []
    section = "General"
    current: Optional[dict] = None
    with open(md_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            sec = _SECTION_RE.match(line)
            if sec:
                section = _strip_md(sec.group(1))
                current = None
                continue
            clause = _CLAUSE_RE.match(line)
            if clause:
                current = {
                    "clause_id": clause.group(1),
                    "section": section,
                    "text": _strip_md(clause.group(2)),
                }
                clauses.append(current)
            elif current is not None and line.strip() and not line.startswith("#"):
                # continuation line of the current clause bullet
                current["text"] = (current["text"] + " " + _strip_md(line)).strip()
    return clauses


# --------------------------------------------------------------------------- #
# Policy store: Chroma vector retrieval with a keyword fallback
# --------------------------------------------------------------------------- #
class PolicyStore:
    """Retrieves relevant policy clauses. Vector-backed when Chroma is available."""

    def __init__(self, clauses: list[dict], mode: str):
        self.clauses = clauses
        self.by_id = {c["clause_id"]: c for c in clauses}
        self.mode = mode  # "vector" | "keyword"
        self._collection = None

    # -- construction ------------------------------------------------------- #
    @classmethod
    def build(
        cls,
        md_path: str = DEFAULT_POLICY_MD,
        persist_dir: str = DEFAULT_CHROMA_DIR,
        prefer_vector: bool = True,
    ) -> "PolicyStore":
        clauses = parse_policy_clauses(md_path)
        if prefer_vector:
            try:
                return cls._build_vector(clauses, persist_dir)
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"[policy] vector store unavailable ({exc!r}); "
                      f"falling back to keyword retrieval")
        return cls(clauses, mode="keyword")

    @classmethod
    def _build_vector(cls, clauses: list[dict], persist_dir: str) -> "PolicyStore":
        import chromadb

        client = chromadb.PersistentClient(path=persist_dir)
        # Default embedding function = local ONNX MiniLM (no API key, no torch).
        collection = client.get_or_create_collection(name="credit_policy")
        if collection.count() < len(clauses):
            collection.upsert(
                ids=[c["clause_id"] for c in clauses],
                documents=[f"[{c['clause_id']}] ({c['section']}) {c['text']}" for c in clauses],
                metadatas=[{"clause_id": c["clause_id"], "section": c["section"]} for c in clauses],
            )
        store = cls(clauses, mode="vector")
        store._collection = collection
        return store

    # -- retrieval ---------------------------------------------------------- #
    def retrieve(self, query: str, k: int = 5) -> list[dict]:
        if self.mode == "vector" and self._collection is not None:
            res = self._collection.query(query_texts=[query], n_results=min(k, len(self.clauses)))
            ids = res["ids"][0]
            dists = res.get("distances", [[None] * len(ids)])[0]
            out = []
            for cid, dist in zip(ids, dists):
                c = self.by_id[cid]
                out.append({**c, "score": None if dist is None else round(1 - dist, 3)})
            return out
        return self._keyword_retrieve(query, k)

    def _keyword_retrieve(self, query: str, k: int) -> list[dict]:
        q_terms = {t for t in re.findall(r"[a-z]+", query.lower()) if t not in _STOPWORDS}
        scored = []
        for c in self.clauses:
            terms = {t for t in re.findall(r"[a-z]+", c["text"].lower()) if t not in _STOPWORDS}
            overlap = len(q_terms & terms)
            if overlap:
                scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{**c, "score": float(s)} for s, c in scored[:k]]

    def get_clause(self, clause_id: str) -> Optional[dict]:
        return self.by_id.get(clause_id)

    def clause_text(self, clause_id: str) -> str:
        c = self.by_id.get(clause_id)
        return c["text"] if c else ""


# --------------------------------------------------------------------------- #
# Deterministic policy evaluation
# --------------------------------------------------------------------------- #
def _latest(ratio_result: dict, name: str) -> Optional[float]:
    for r in ratio_result.get("ratios", []):
        if r["name"] == name:
            return r["latest"]
    return None


def _is_unsecured(loan: dict) -> bool:
    loan_type = (loan.get("loan_type") or "").lower()
    collateral = (loan.get("collateral_offered") or "").strip().lower()
    if "unsecured" in loan_type:
        return True
    return collateral in ("", "none", "n/a", "none (unsecured request)")


def evaluate_policy(
    application: dict,
    parsed: dict,
    ratio_result: dict,
    benchmark_result: dict,
    store: Optional[PolicyStore] = None,
) -> dict:
    """Evaluate the applicant against credit-policy thresholds.

    Returns findings (with cited clause text), RAG-retrieved supporting context,
    and a roll-up summary of hard/soft fails and conditions.
    """
    store = store or PolicyStore.build()
    applicant = application.get("applicant", {})
    loan = application.get("loan_request", {})
    relationship = application.get("banking_relationship", {})
    sector = (parsed.get("sector_code") or applicant.get("sector_code") or "").upper()

    findings: list[dict] = []

    def add(clause_id: str, title: str, severity: str, detail: str):
        findings.append({
            "clause_id": clause_id,
            "title": title,
            "severity": severity,  # hard_fail | soft_fail | condition | pass
            "detail": detail,
            "policy_text": store.clause_text(clause_id),
        })

    # --- CP-1: operating history ---
    founded = applicant.get("year_founded")
    if founded:
        years_op = date.today().year - int(founded)
        if years_op < 2:
            add("CP-1.3", "Operating history", "hard_fail",
                f"Only {years_op} year(s) of operating history; under the 2-year minimum (refer to Specialty Lending).")
        else:
            add("CP-1.1", "Operating history", "pass",
                f"{years_op} years of operating history meets the 2-year minimum.")

    # --- CP-2.1: current ratio ---
    cr = _latest(ratio_result, "current_ratio")
    if cr is not None:
        if cr < 1.0:
            add("CP-2.1", "Current ratio", "hard_fail",
                f"Current ratio {cr:.2f}x is below the 1.00x hard floor.")
        elif cr < 1.20:
            add("CP-2.1", "Current ratio", "soft_fail",
                f"Current ratio {cr:.2f}x is below the 1.20x minimum (exception eligible).")
        else:
            add("CP-2.1", "Current ratio", "pass",
                f"Current ratio {cr:.2f}x meets the 1.20x minimum.")

    # --- CP-2.2: quick ratio (sector-dependent floor) ---
    qr = _latest(ratio_result, "quick_ratio")
    if qr is not None:
        floor = 0.50 if sector == "RET" else 0.70
        if qr < floor:
            add("CP-2.2", "Quick ratio", "soft_fail",
                f"Quick ratio {qr:.2f}x is below the {floor:.2f}x floor for this borrower type.")
        else:
            add("CP-2.2", "Quick ratio", "pass",
                f"Quick ratio {qr:.2f}x meets the {floor:.2f}x floor.")

    # --- CP-3.1: debt-to-equity ---
    de = _latest(ratio_result, "debt_to_equity")
    if de is not None:
        if de > 3.0:
            add("CP-3.1", "Leverage (D/E)", "hard_fail",
                f"Debt-to-equity {de:.2f}x exceeds the 3.0x ceiling.")
        elif de >= 2.0:
            add("CP-3.1", "Leverage (D/E)", "condition",
                f"Debt-to-equity {de:.2f}x is in the 2.0x-3.0x band; requires an exception and additional collateral.")
        else:
            add("CP-3.1", "Leverage (D/E)", "pass",
                f"Debt-to-equity {de:.2f}x is within the 3.0x ceiling.")

    # --- CP-3.2: debt-to-assets ---
    da = _latest(ratio_result, "debt_to_assets")
    if da is not None and da > 0.70:
        add("CP-3.2", "Leverage (D/A)", "condition",
            f"Debt-to-assets {da:.2f}x exceeds 0.70 and requires senior analyst review.")

    # --- CP-3.3: interest coverage ---
    ic = _latest(ratio_result, "interest_coverage")
    if ic is not None:
        if ic < 2.0:
            add("CP-3.3", "Interest coverage", "hard_fail",
                f"Interest coverage {ic:.2f}x is below the 2.0x hard floor.")
        elif ic < 3.0:
            add("CP-3.3", "Interest coverage", "condition",
                f"Interest coverage {ic:.2f}x is between 2.0x-3.0x; acceptable only with conditions (e.g. debt service reserve).")
        else:
            add("CP-3.3", "Interest coverage", "pass",
                f"Interest coverage {ic:.2f}x meets the 2.0x minimum.")

    # --- CP-4.1 / CP-4.2: profitability ---
    ni_series = parsed.get("income_statement", {}).get("net_income", [])
    if ni_series:
        if len(ni_series) >= 2 and ni_series[0] < 0 and ni_series[1] < 0:
            add("CP-4.2", "Profitability", "hard_fail",
                "Two consecutive years of net losses.")
        elif ni_series[0] < 0:
            add("CP-4.1", "Profitability", "soft_fail",
                f"Net loss of {ni_series[0]:,} in the most recent year; requires an exception and a turnaround plan.")
        else:
            add("CP-4.1", "Profitability", "pass",
                f"Net profitable in the most recent year ({ni_series[0]:,}).")

    # --- CP-4.3: gross margin vs benchmark ---
    for c in benchmark_result.get("comparisons", []):
        if c["ratio"] == "gross_margin" and c["z_score"] <= -1.5:
            add("CP-4.3", "Gross margin vs sector", "soft_fail",
                f"Gross margin is {abs(c['z_score']):.1f} std below the sector mean; must be explained in the memo.")

    # --- CP-5.2 / CP-6.1: unsecured exposure & relationship ---
    amount = loan.get("amount_requested") or 0
    if _is_unsecured(loan) and amount > 1_000_000:
        add("CP-5.2", "Unsecured exposure", "condition",
            f"Unsecured request of {amount:,} above 1,000,000 requires a personal guarantee (20%+ owners) or a compensating deposit relationship.")
        if not relationship.get("existing_customer", False):
            add("CP-6.1", "New-to-bank", "condition",
                "New-to-bank borrower with a large unsecured request; recommendation capped at 'Approve with conditions' pending a personal guarantee.")

    # --- CP-5.3: equipment term vs useful life ---
    term = loan.get("requested_term_months") or 0
    if "equipment" in (loan.get("loan_type") or "").lower() and term > 84:
        add("CP-5.3", "Loan term", "condition",
            f"Requested term {term} months exceeds the 84-month cap for equipment loans.")

    summary = {
        "hard_fails": sum(1 for f in findings if f["severity"] == "hard_fail"),
        "soft_fails": sum(1 for f in findings if f["severity"] == "soft_fail"),
        "conditions": sum(1 for f in findings if f["severity"] == "condition"),
        "passes": sum(1 for f in findings if f["severity"] == "pass"),
    }

    # --- RAG: retrieve supporting policy context for the LLM step ---
    flagged = ", ".join(f["label"] for f in benchmark_result.get("flags", [])) or "none"
    query = (
        f"{applicant.get('industry', '')} borrower, "
        f"{loan.get('loan_type', '')}, amount {amount}, term {term} months. "
        f"Flagged ratios: {flagged}. Liquidity leverage interest coverage profitability "
        f"collateral guarantee exception risk rating recommendation."
    )
    retrieved = store.retrieve(query, k=6)

    return {
        "retrieval_mode": store.mode,
        "findings": findings,
        "summary": summary,
        "retrieved_context": retrieved,
        "query": query,
    }


if __name__ == "__main__":
    import json
    import sys
    from parsing import parse_financials  # noqa: E402
    from ratios import compute_ratios  # noqa: E402
    from benchmarks import compare_to_benchmarks  # noqa: E402

    app_id = sys.argv[1] if len(sys.argv) > 1 else "1001"
    with open(f"samples/application_{app_id}.json", encoding="utf-8") as fh:
        application = json.load(fh)
    parsed = parse_financials(f"samples/financials_{app_id}.pdf")
    if not parsed.get("sector_code"):
        parsed["sector_code"] = application["applicant"].get("sector_code")
    ratios = compute_ratios(parsed)
    bench = compare_to_benchmarks(ratios, parsed["sector_code"])

    result = evaluate_policy(application, parsed, ratios, bench)
    print(f"Policy evaluation for application {app_id}  (retrieval: {result['retrieval_mode']})")
    print(f"Summary: {result['summary']}\n")
    for f in result["findings"]:
        mark = {"pass": "OK  ", "soft_fail": "SOFT", "hard_fail": "HARD", "condition": "COND"}[f["severity"]]
        print(f"  [{mark}] {f['clause_id']:<7} {f['title']:<24} {f['detail']}")
    print("\nTop retrieved policy context:")
    for c in result["retrieved_context"][:4]:
        print(f"  - {c['clause_id']}: {c['text'][:90]}...")
