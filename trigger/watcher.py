



"""Trigger: watch the /inputs folder and run the flow on each complete pair.

Simulates the production trigger ("application submitted AND financials uploaded")
for local development. Polls ``inputs/`` for a matching pair

    application_<id>.json   +   financials_<id>.(pdf|xlsx)

and, when both are present, fires the Credit Analyst flow. By default it calls
the running Langflow flow over its REST API; with ``--direct`` it bypasses
Langflow and runs ``lib.pipeline`` in-process (handy for CI / offline demos).

Processed application ids are recorded in ``inputs/.processed/`` so a pair is
only run once.

Env (see .env.example):
    LANGFLOW_URL              default http://localhost:7860
    LANGFLOW_FLOW_ID          flow id or endpoint name to invoke
    LANGFLOW_API_KEY          optional; sent as x-api-key
    LANGFLOW_INGEST_NODE_ID   ingest node id to target with tweaks
                              (default: CreditApplicationIngest)

Usage:
    python trigger/watcher.py                 # poll forever, call Langflow
    python trigger/watcher.py --once          # single sweep then exit
    python trigger/watcher.py --direct        # run pipeline in-process
    python trigger/watcher.py --interval 3
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

FIN_EXTS = (".pdf", ".xlsx", ".xlsm", ".xls")
_APP_RE = re.compile(r"^application_(.+)\.json$")


def _load_dotenv(path: str = os.path.join(_ROOT, ".env")) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def _find_financials(input_dir: str, app_id: str):
    for ext in FIN_EXTS:
        cand = os.path.join(input_dir, f"financials_{app_id}{ext}")
        if os.path.isfile(cand):
            return cand
    return None


def discover_pairs(input_dir: str) -> list[str]:
    """Return application ids in input_dir that have a matching financials file."""
    pairs = []
    if not os.path.isdir(input_dir):
        return pairs
    for fname in sorted(os.listdir(input_dir)):
        m = _APP_RE.match(fname)
        if m and _find_financials(input_dir, m.group(1)):
            pairs.append(m.group(1))
    return pairs


# --------------------------------------------------------------------------- #
# Execution backends
# --------------------------------------------------------------------------- #
def run_direct(app_id: str, input_dir: str, output_dir: str) -> dict:
    from lib.pipeline import run_from_id

    result = run_from_id(app_id, input_dir=input_dir, samples_dir="",
                         output_dir=output_dir, prefer_vector=True, prefer_llm=True)
    memo = result["memo"]
    return {"ok": True, "backend": "direct",
            "risk_rating": memo["risk_rating"], "recommendation": memo["recommendation"],
            "pdf": result["paths"]["pdf"]}


def run_langflow(app_id: str, input_dir: str) -> dict:
    import requests

    base = os.environ.get("LANGFLOW_URL", "http://localhost:7860").rstrip("/")
    flow_id = os.environ.get("LANGFLOW_FLOW_ID", "credit-analyst")
    ingest_node = os.environ.get("LANGFLOW_INGEST_NODE_ID", "CreditApplicationIngest")
    url = f"{base}/api/v1/run/{flow_id}?stream=false"

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LANGFLOW_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    payload = {
        "input_value": app_id,
        "input_type": "text",
        "output_type": "text",
        "tweaks": {
            ingest_node: {"application_id": app_id, "input_dir": os.path.abspath(input_dir)},
        },
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=300)
    resp.raise_for_status()
    return {"ok": True, "backend": "langflow", "status_code": resp.status_code,
            "response": resp.json()}


# --------------------------------------------------------------------------- #
# Watch loop
# --------------------------------------------------------------------------- #
def _processed_marker(input_dir: str, app_id: str) -> str:
    return os.path.join(input_dir, ".processed", f"{app_id}.done")


def process_pair(app_id: str, input_dir: str, output_dir: str, direct: bool) -> None:
    print(f"[watcher] trigger matched for application {app_id} "
          f"({'direct' if direct else 'langflow'} backend)")
    t0 = time.time()
    try:
        result = run_direct(app_id, input_dir, output_dir) if direct \
            else run_langflow(app_id, input_dir)
    except Exception as exc:
        print(f"[watcher] ERROR processing {app_id}: {exc!r}")
        return
    dt = round(time.time() - t0, 2)
    if result.get("backend") == "direct":
        print(f"[watcher] done {app_id} in {dt}s -> {result['risk_rating']} / "
              f"{result['recommendation']}  ({os.path.basename(result['pdf'])})")
    else:
        print(f"[watcher] done {app_id} in {dt}s -> Langflow HTTP {result['status_code']}")

    marker = _processed_marker(input_dir, app_id)
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S"))


def sweep(input_dir: str, output_dir: str, direct: bool) -> int:
    count = 0
    for app_id in discover_pairs(input_dir):
        if os.path.isfile(_processed_marker(input_dir, app_id)):
            continue
        process_pair(app_id, input_dir, output_dir, direct)
        count += 1
    return count


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Watch /inputs and trigger the Credit Analyst flow.")
    parser.add_argument("--input-dir", default=os.path.join(_ROOT, "inputs"))
    parser.add_argument("--output-dir", default=os.path.join(_ROOT, "outputs"))
    parser.add_argument("--interval", type=float, default=5.0, help="Polling interval (seconds).")
    parser.add_argument("--once", action="store_true", help="Single sweep then exit.")
    parser.add_argument("--direct", action="store_true",
                        help="Run lib.pipeline in-process instead of calling Langflow.")
    args = parser.parse_args()

    os.makedirs(args.input_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)
    backend = "direct (in-process)" if args.direct else \
        f"Langflow @ {os.environ.get('LANGFLOW_URL', 'http://localhost:7860')}"
    print(f"[watcher] watching {args.input_dir}  | backend: {backend}")

    if args.once:
        n = sweep(args.input_dir, args.output_dir, args.direct)
        print(f"[watcher] swept once, processed {n} new pair(s).")
        return 0

    try:
        while True:
            sweep(args.input_dir, args.output_dir, args.direct)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[watcher] stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
