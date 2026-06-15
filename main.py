"""Convenience CLI entrypoint for the Credit Analyst pipeline.

Runs the full analysis directly (no Langflow server) on one application id and
writes the PDF memo + JSON summary to outputs/.

Examples:
    python main.py 1001
    python main.py 1002 --llm           # use Claude if ANTHROPIC_API_KEY is set
    python main.py 1001 --no-vector      # force keyword policy retrieval

For the Langflow-server path and the folder watcher, see the README.
"""

from __future__ import annotations

import argparse
import os

from lib.pipeline import run_from_id

_ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a draft credit memo for one application.")
    parser.add_argument("application_id", help="e.g. 1001 (looks in inputs/ then samples/)")
    parser.add_argument("--llm", action="store_true", help="Use Claude for scoring (needs ANTHROPIC_API_KEY).")
    parser.add_argument("--no-vector", action="store_true", help="Force keyword policy retrieval.")
    parser.add_argument("--output-dir", default=os.path.join(_ROOT, "outputs"))
    args = parser.parse_args()

    result = run_from_id(
        args.application_id,
        input_dir=os.path.join(_ROOT, "inputs"),
        samples_dir=os.path.join(_ROOT, "samples"),
        output_dir=args.output_dir,
        prefer_vector=not args.no_vector,
        prefer_llm=args.llm,
        verbose=True,
    )
    memo = result["memo"]
    print(f"\n{memo['company_name']}: {memo['risk_rating']} risk / {memo['recommendation']}")
    print(f"  PDF : {result['paths']['pdf']}")
    print(f"  JSON: {result['paths']['json']}")
    print(f"  done in {result['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
