"""End-to-end orchestrator (framework-agnostic).

Chains all six pipeline stages directly, without Langflow. This is what the
test script and the watcher's offline fallback call, and it mirrors exactly the
sequence the Langflow flow wires together::

    ingest -> ratios -> benchmark -> policy -> score -> memo

Returns the structured memo plus the output file paths.
"""

from __future__ import annotations

import json
import os
import time

from .parsing import parse_financials
from .ratios import compute_ratios
from .benchmarks import compare_to_benchmarks
from .policy import PolicyStore, evaluate_policy
from .scoring import score_risk
from .memo import build_memo, generate_outputs


def run_analysis(
    application: dict,
    financials_path: str,
    output_dir: str = "outputs",
    prefer_vector: bool = True,
    prefer_llm: bool = True,
    verbose: bool = False,
) -> dict:
    """Run the full pipeline on an in-memory application + financials file."""
    t0 = time.time()

    def log(msg: str):
        if verbose:
            print(f"  [{time.time() - t0:5.1f}s] {msg}")

    parsed = parse_financials(financials_path)
    if not parsed.get("sector_code"):
        parsed["sector_code"] = application.get("applicant", {}).get("sector_code")
    log(f"parsed {len(parsed.get('years', []))} year(s) from {os.path.basename(financials_path)}")

    ratios = compute_ratios(parsed)
    log(f"computed {len(ratios['ratios'])} ratios")

    benchmark = compare_to_benchmarks(ratios, parsed["sector_code"])
    log(f"benchmarked vs {benchmark['sector_code']}: {len(benchmark['flags'])} flag(s)")

    store = PolicyStore.build(prefer_vector=prefer_vector)
    policy = evaluate_policy(application, parsed, ratios, benchmark, store=store)
    log(f"policy ({policy['retrieval_mode']}): {policy['summary']}")

    verdict = score_risk(application, ratios, benchmark, policy, prefer_llm=prefer_llm)
    log(f"scored: {verdict['risk_rating']} / {verdict['recommendation']} ({verdict['engine']})")

    memo = build_memo(application, parsed, ratios, benchmark, policy, verdict)
    paths = generate_outputs(memo, output_dir)
    log(f"wrote {os.path.basename(paths['pdf'])} and {os.path.basename(paths['json'])}")

    return {
        "memo": memo,
        "paths": paths,
        "elapsed_seconds": round(time.time() - t0, 2),
    }


def run_from_id(
    application_id: str,
    input_dir: str = "inputs",
    samples_dir: str = "samples",
    output_dir: str = "outputs",
    **kwargs,
) -> dict:
    """Locate application_<id>.json + financials_<id>.* and run the pipeline."""
    app_path = None
    fin_path = None
    for d in (input_dir, samples_dir):
        if not d or not os.path.isdir(d):
            continue
        cand = os.path.join(d, f"application_{application_id}.json")
        if app_path is None and os.path.isfile(cand):
            app_path = cand
        for ext in (".pdf", ".xlsx", ".xlsm", ".xls"):
            cand_f = os.path.join(d, f"financials_{application_id}{ext}")
            if fin_path is None and os.path.isfile(cand_f):
                fin_path = cand_f
    if not app_path or not fin_path:
        raise FileNotFoundError(
            f"Missing application_{application_id}.json or financials_{application_id}.* "
            f"in {input_dir!r}/{samples_dir!r}")

    with open(app_path, encoding="utf-8") as fh:
        application = json.load(fh)
    return run_analysis(application, fin_path, output_dir=output_dir, **kwargs)
