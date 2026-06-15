# Credit Analyst — AI Commercial Credit Memo Generator

An AI agent (built as a **Langflow** flow with custom Python components) that
automates the **first draft of a commercial credit memo**. It ingests a credit
application and financial statements, computes financial ratios, benchmarks them
against industry norms, checks compliance against an internal credit policy
(RAG), scores risk with **Claude**, and renders a polished **PDF memo** plus a
JSON audit summary — in **well under 5 minutes** (the bundled samples run in
seconds).

> ⚠️ Every memo is watermarked as an **AI-generated draft** that requires review
> and sign-off by a qualified human credit analyst before any lending decision.

---

## What it does

A human analyst typically spends 4–8 hours per application reviewing financials,
checking ratios against benchmarks, and verifying policy compliance before
writing a memo. This agent produces that first draft automatically.

**Trigger** (local dev): a watcher polls `inputs/` for a matching pair —
`application_<id>.json` + `financials_<id>.pdf|xlsx` — and fires the flow.

**Pipeline:**

```
 inputs/                          Credit Analyst flow (6 custom components)
  application_<id>.json  ─┐    ┌────────────────────────────────────────────┐
  financials_<id>.pdf    ─┼──▶ │ 1. Credit Application Ingest  (parse)       │
                          │    │ 2. Ratio Calculator                         │
  trigger/watcher.py      │    │ 3. Benchmark Comparator   (industry CSV)    │
  POSTs to Langflow REST  │    │ 4. Policy Compliance (RAG, Chroma)          │
                          │    │ 5. Risk Scoring           (Claude)          │
                          │    │ 6. Memo Generator         (PDF + JSON)      │
                          │    └────────────────────────────────────────────┘
                          │                        │
                          └────────────────────────┴──▶ outputs/
                                                         credit_memo_<id>.pdf
                                                         analysis_<id>.json
```

The memo contains: Executive Summary · Applicant Overview · Financial Analysis
(multi-year ratio tables) · Industry Comparison · Policy Compliance Notes · Risk
Assessment · Recommendation.

---

## Architecture: `lib/` core + thin Langflow wrappers

All real logic lives in plain, unit-testable Python modules in **`lib/`**. The
Langflow components in **`components/`** are thin wrappers that import `lib/` and
pass an accumulating "analysis bundle" (`Data`) down the graph.

This means the pipeline runs **two ways**, with identical results:

| Path | How | Use |
|------|-----|-----|
| **Direct** | `lib.pipeline.run_from_id()` | tests, CI, fast offline demo |
| **Langflow** | flow JSON in a running server, triggered over REST | the agent / UI |

Two capabilities are **optional with graceful fallbacks**, so the pipeline always
produces a memo:

- **Risk scoring** uses **Claude** (`claude-opus-4-8`) when `ANTHROPIC_API_KEY`
  is set; otherwise a deterministic engine that applies the policy's own rating
  rules.
- **Policy retrieval** uses a **Chroma** vector store (local ONNX embeddings, no
  API key); if Chroma is unavailable it falls back to keyword retrieval.

Numeric threshold checks (hard/soft fails) are always **deterministic** — the LLM
reasons over pre-computed, verified facts rather than parsing raw statements.

---

## Folder structure

```
credit_risk_narrative_generator/
├── README.md
├── requirements.txt
├── .env.example                 # ANTHROPIC_API_KEY, LANGFLOW_URL, ...
├── flow/
│   ├── credit_analyst_flow.json # exported Langflow flow (importable)
│   └── build_flow.py            # regenerates the flow JSON from the components
├── components/                  # Langflow custom components (one per stage)
│   ├── credit_application_ingest.py
│   ├── ratio_calculator.py
│   ├── benchmark_comparator.py
│   ├── policy_compliance.py
│   ├── risk_scoring.py
│   └── memo_generator.py
├── lib/                         # framework-agnostic core logic
│   ├── parsing.py  ratios.py  benchmarks.py
│   ├── policy.py   scoring.py  memo.py
│   └── pipeline.py              # direct end-to-end orchestrator
├── trigger/
│   └── watcher.py               # watches inputs/, calls Langflow REST (or --direct)
├── data/
│   ├── benchmarks/industry_benchmarks.csv
│   └── policy/credit_policy.md
├── samples/                     # 2 applications + mock financials (+ generator)
├── inputs/                      # watched folder (drop pairs here)
├── outputs/                     # generated memos + JSON land here
└── tests/run_pipeline.py        # end-to-end test on the sample data
```

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # optional: add ANTHROPIC_API_KEY for live Claude
```

(Re)generate the mock financial-statement PDFs if needed:

```bash
python samples/generate_mock_financials.py
```

---

## Quick verification (no Langflow needed) — under 5 minutes

```bash
python tests/run_pipeline.py            # deterministic mock scoring
python tests/run_pipeline.py --llm      # use Claude (needs ANTHROPIC_API_KEY)
```

This runs **both** sample applications end-to-end and writes
`outputs/credit_memo_<id>.pdf` + `outputs/analysis_<id>.json`, asserting the
expected risk ratings. Expect:

| Application | Company | Result |
|---|---|---|
| 1001 | Apex Precision (Manufacturing) | **Low risk → Approve** |
| 1002 | Brightway Retail (Retail) | **High risk → Refer to senior analyst** |

---

## Running it as the Langflow agent

> Requires `langflow` installed (`pip install langflow`; it is heavy). The custom
> components import `lib/`, so we point Langflow at this project.

The flow JSON is generated from the components with
`python flow/build_flow.py` (already committed as `flow/credit_analyst_flow.json`).

1. **Start Langflow** with this project on the path so the custom components can
   import `lib/`. `PYTHONPATH` is the key bit — Langflow execs the embedded
   component code in a worker where a runtime `sys.path` insert doesn't persist,
   so the project root must be on `PYTHONPATH`:

   ```bash
   export CREDIT_ANALYST_ROOT="$(pwd)"
   export PYTHONPATH="$(pwd)"                       # so components can import lib/
   export LANGFLOW_COMPONENTS_PATH="$(pwd)/components"
   export LANGFLOW_CONFIG_DIR="$(pwd)/.langflow"
   export LANGFLOW_AUTO_LOGIN=true
   export LANGFLOW_SKIP_AUTH_AUTO_LOGIN=true        # allow REST runs under auto-login (v1.5+)
   langflow run --backend-only --host 127.0.0.1 --port 7860
   ```

2. **Import the flow**: either use the UI (http://localhost:7860 → *New* →
   *Import* → `flow/credit_analyst_flow.json`), or create it over the API:

   ```bash
   TOKEN=$(curl -s http://127.0.0.1:7860/api/v1/auto_login | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
   curl -s -X POST http://127.0.0.1:7860/api/v1/flows/ -H "Authorization: Bearer $TOKEN" \
        -H 'Content-Type: application/json' \
        -d "{\"name\":\"Credit Analyst\",\"endpoint_name\":\"credit-analyst\",\"data\":$(python -c 'import json;print(json.dumps(json.load(open("flow/credit_analyst_flow.json"))["data"]))')}"
   # create an API key for triggering:
   curl -s -X POST http://127.0.0.1:7860/api/v1/api_key/ -H "Authorization: Bearer $TOKEN" \
        -H 'Content-Type: application/json' -d '{"name":"watcher"}'
   ```

   The six Credit Analyst components appear as a connected chain. (Optionally
   paste your Anthropic key into the *Risk Scoring* node; otherwise it runs the
   mock engine.)

3. **Configure `.env`** with the flow endpoint + API key:

   ```ini
   LANGFLOW_URL=http://127.0.0.1:7860
   LANGFLOW_FLOW_ID=credit-analyst
   LANGFLOW_API_KEY=sk-...            # from the api_key call above
   LANGFLOW_INGEST_NODE_ID=CreditApplicationIngest
   ```

4. **Trigger it** by starting the watcher and dropping a pair into `inputs/`:

   ```bash
   python trigger/watcher.py                        # polls inputs/, calls the REST API
   # in another shell:
   cp samples/application_1001.json samples/financials_1001.pdf inputs/
   ```

   The watcher detects the matched pair and POSTs to
   `/api/v1/run/<flow_id>`, overriding the ingest node's `application_id` via
   tweaks. The flow runs server-side and the memo lands in `outputs/`.

   To run the same trigger logic without a server (in-process):

   ```bash
   python trigger/watcher.py --direct --once
   ```

---

## Data sources

| Source | File | Purpose |
|---|---|---|
| Credit application | `samples/application_<id>.json` | applicant, loan request, relationship |
| Financial statements | `samples/financials_<id>.pdf` | balance sheet, income, cash flow (3 yrs) |
| Industry benchmarks | `data/benchmarks/industry_benchmarks.csv` | ratio mean/std-dev by sector |
| Credit policy | `data/policy/credit_policy.md` | clause-level lending rules (CP-x.y) |

---

## Tech stack

- **Langflow** — agent flow + custom components
- **pdfplumber / openpyxl** — statement parsing
- **reportlab** — mock financials + memo PDF rendering
- **Chroma** (local ONNX embeddings) — credit-policy vector store
- **Anthropic Claude** (`claude-opus-4-8`) — risk synthesis & reasoning
- **requests** — Langflow REST trigger

See `requirements.txt` for pinned versions.
