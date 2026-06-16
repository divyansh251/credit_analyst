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
from langflow.io import FileInput, MessageTextInput, Output
from langflow.schema import Data


class CreditApplicationIngestComponent(Component):
    display_name = "Credit Application Ingest"
    description = ("Loads application_<id>.json and parses financials_<id>.(pdf|xlsx) "
                   "into a canonical analysis bundle.")
    icon = "file-text"
    name = "CreditApplicationIngest"

    inputs = [
        FileInput(
            name="application_file", display_name="Application JSON",
            info="Optional. Upload the application_<id>.json directly. "
                 "If set, this is used instead of the Application ID lookup.",
            file_types=["json"], required=False,
        ),
        FileInput(
            name="financials_file", display_name="Financials File",
            info="Optional. Upload the financials file (xlsx/xls/pdf) directly. "
                 "If set, this is used instead of the Application ID lookup.",
            file_types=["xlsx", "xlsm", "xls", "pdf"], required=False,
        ),
        MessageTextInput(
            name="application_id", display_name="Application ID",
            info="Used to locate application_<id>.json and financials_<id>.* when "
                 "files are not uploaded above. e.g. 1001",
            value="1001",
        ),
        MessageTextInput(
            name="input_dir", display_name="Input Directory",
            info="Folder to search first; falls back to the bundled samples/ folder.",
            value=os.path.join(_ROOT, "inputs"),
        ),
    ]
    outputs = [Output(name="bundle", display_name="Analysis Bundle", method="ingest")]

    def _resolve(self, app_id: str, input_dir: str) -> tuple[str | None, str | None]:
        """Best-effort id-based lookup; returns (app_path|None, fin_path|None)."""
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
        return app_path, fin_path

    def ingest(self) -> Data:
        from lib.parsing import parse_financials

        app_id = (self.application_id or "").strip()
        input_dir = (self.input_dir or "").strip()

        # Uploaded files take precedence; fall back to id-based lookup for any
        # file that wasn't uploaded.
        app_path = (self.application_file or "").strip() or None
        fin_path = (self.financials_file or "").strip() or None
        if app_path is None or fin_path is None:
            r_app, r_fin = self._resolve(app_id, input_dir)
            app_path = app_path or r_app
            fin_path = fin_path or r_fin

        missing = []
        if not app_path:
            missing.append("application JSON")
        if not fin_path:
            missing.append("financials file (xlsx/pdf)")
        if missing:
            raise FileNotFoundError(
                "Missing " + " and ".join(missing) + ": upload the file(s) on the node, "
                f"or place application_{app_id}.json / financials_{app_id}.* in "
                f"{input_dir or os.path.join(_ROOT, 'inputs')}.")

        with open(app_path, encoding="utf-8") as fh:
            application = json.load(fh)
        # Prefer the id inside the uploaded JSON so it stays correct even when the
        # Application ID box still holds its default.
        app_id = str(application.get("application_id") or app_id or "").strip()
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
