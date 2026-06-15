"""End-to-end pipeline test on the bundled sample data.

Runs both sample applications through the full analysis pipeline (directly via
``lib.pipeline`` — no Langflow server required) and verifies that each produces
a PDF memo + JSON summary with the expected risk rating, well under 5 minutes.

Usage:
    python tests/run_pipeline.py
    python tests/run_pipeline.py --llm        # use Claude if ANTHROPIC_API_KEY is set
    python tests/run_pipeline.py --no-vector   # force keyword policy retrieval
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Make the project root importable when run as `python tests/run_pipeline.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.pipeline import run_from_id  # noqa: E402

# (application_id, expected_risk_rating, expected_recommendation_contains)
EXPECTED = [
    ("1001", "Low", "Approve"),
    ("1002", "High", "Refer"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Credit Analyst pipeline on sample data.")
    parser.add_argument("--llm", action="store_true",
                        help="Use Claude for scoring (requires ANTHROPIC_API_KEY).")
    parser.add_argument("--no-vector", action="store_true",
                        help="Force keyword policy retrieval instead of Chroma.")
    parser.add_argument("--output-dir", default=os.path.join(_ROOT, "outputs"))
    args = parser.parse_args()

    samples_dir = os.path.join(_ROOT, "samples")
    inputs_dir = os.path.join(_ROOT, "inputs")

    print("=" * 72)
    print("Credit Analyst — end-to-end pipeline test")
    print(f"  scoring engine : {'Claude (if key set)' if args.llm else 'deterministic mock'}")
    print(f"  policy retrieval: {'keyword' if args.no_vector else 'vector (Chroma) w/ fallback'}")
    print("=" * 72)

    overall_start = time.time()
    failures = 0

    for app_id, exp_rating, exp_rec in EXPECTED:
        print(f"\n--- Application {app_id} ---")
        result = run_from_id(
            app_id,
            input_dir=inputs_dir,
            samples_dir=samples_dir,
            output_dir=args.output_dir,
            prefer_vector=not args.no_vector,
            prefer_llm=args.llm,
            verbose=True,
        )
        memo = result["memo"]
        pdf, js = result["paths"]["pdf"], result["paths"]["json"]

        print(f"  company       : {memo['company_name']}")
        print(f"  engine        : {memo['engine']}  | retrieval: {memo['retrieval_mode']}")
        print(f"  risk rating   : {memo['risk_rating']}")
        print(f"  recommendation: {memo['recommendation']}")
        print(f"  elapsed       : {result['elapsed_seconds']}s")

        checks = [
            ("PDF exists", os.path.isfile(pdf) and os.path.getsize(pdf) > 0),
            ("JSON exists", os.path.isfile(js) and os.path.getsize(js) > 0),
            (f"rating == {exp_rating}", memo["risk_rating"] == exp_rating),
            (f"recommendation contains '{exp_rec}'", exp_rec.lower() in (memo["recommendation"] or "").lower()),
        ]
        for name, ok in checks:
            print(f"    [{'PASS' if ok else 'FAIL'}] {name}")
            failures += 0 if ok else 1
        print(f"    -> {os.path.relpath(pdf, _ROOT)}")
        print(f"    -> {os.path.relpath(js, _ROOT)}")

    total = round(time.time() - overall_start, 2)
    print("\n" + "=" * 72)
    status = "ALL CHECKS PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED"
    print(f"{status}  |  total wall time: {total}s "
          f"({'within' if total < 300 else 'OVER'} the 5-minute target)")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
