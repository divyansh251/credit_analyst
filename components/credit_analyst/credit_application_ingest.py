"""Langflow component (pipeline stage 1): Credit Application Ingest.

Entry point of the Credit Analyst flow. Given an application id, it loads the
structured application JSON and parses the matching financial-statements file
into the canonical structure, emitting an accumulating "analysis bundle" Data
object that flows through the rest of the graph.
"""

from __future__ import annotations

import json
import os
import sys

# --- bootstrap: put the project root (with lib/) on sys.path ---
_ROOT = os.environ.get("CREDIT_ANALYST_ROOT")
if not _ROOT:
    try:
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:  # pragma: no cover - pasted into UI editor
        _ROOT = os.getcwd()
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from langflow.custom import Component
from langflow.io import MessageTextInput, Output
from langflow.schema import Data


class CreditApplicationIngestComponent(Component):
    display_name = "Credit Application Ingest"
    description = ("Loads application_<id>.json and parses financials_<id>.(pdf|xlsx) "
                   "into a canonical analysis bundle.")
    icon = "file-text"
    name = "CreditApplicationIngest"

    inputs = [
        MessageTextInput(
            name="application_id", display_name="Application ID",
            info="e.g. 1001 — used to locate application_<id>.json and financials_<id>.*",
            value="1001",
        ),
        MessageTextInput(
            name="input_dir", display_name="Input Directory",
            info="Folder to search first; falls back to the bundled samples/ folder.",
            value=os.path.join(_ROOT, "inputs"),
        ),
    ]
    outputs = [Output(name="bundle", display_name="Analysis Bundle", method="ingest")]

    def _resolve(self, app_id: str, input_dir: str) -> tuple[str, str]:
        search_dirs = [input_dir, os.path.join(_ROOT, "inputs"), os.path.join(_ROOT, "samples")]
        app_path = fin_path = None
        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            cand_app = os.path.join(d, f"application_{app_id}.json")
            if app_path is None and os.path.isfile(cand_app):
                app_path = cand_app
            for ext in (".pdf", ".xlsx", ".xlsm", ".xls"):
                cand_fin = os.path.join(d, f"financials_{app_id}{ext}")
                if fin_path is None and os.path.isfile(cand_fin):
                    fin_path = cand_fin
        if not app_path or not fin_path:
            raise FileNotFoundError(
                f"Could not locate application_{app_id}.json and financials_{app_id}.* "
                f"in {search_dirs}")
        return app_path, fin_path

    def ingest(self) -> Data:
        from lib.parsing import parse_financials

        app_id = (self.application_id or "").strip()
        input_dir = (self.input_dir or "").strip()
        app_path, fin_path = self._resolve(app_id, input_dir)

        with open(app_path, encoding="utf-8") as fh:
            application = json.load(fh)
        parsed = parse_financials(fin_path)
        if not parsed.get("sector_code"):
            parsed["sector_code"] = application.get("applicant", {}).get("sector_code")

        bundle = {
            "application_id": app_id,
            "application": application,
            "parsed": parsed,
            "sources": {"application": app_path, "financials": fin_path},
        }
        self.status = (f"Ingested application {app_id}: "
                       f"{len(parsed.get('years', []))} year(s), "
                       f"{len(parsed.get('balance_sheet', {}))} balance-sheet items")
        return Data(data=bundle)
