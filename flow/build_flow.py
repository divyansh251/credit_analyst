"""Generate the importable Langflow flow JSON from the custom components.

Rather than hand-authoring the (fragile) ReactFlow node/edge JSON, this builds
the flow with Langflow's own ``flow_builder`` API: it instantiates each custom
component, serialises its frontend node, registers them, then wires the six
stages into a linear chain and lays them out. The result is written to
``flow/credit_analyst_flow.json`` and is directly importable in the Langflow UI.

Run:
    CREDIT_ANALYST_ROOT="$(pwd)" python flow/build_flow.py
"""

from __future__ import annotations

import importlib
import json
import os
import sys

_ROOT = os.environ.get("CREDIT_ANALYST_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["CREDIT_ANALYST_ROOT"] = _ROOT
sys.path.insert(0, _ROOT)
# Components live in a category subfolder (components/credit_analyst/) so that
# Langflow's LANGFLOW_COMPONENTS_PATH scan registers them under that category.
sys.path.insert(0, os.path.join(_ROOT, "components", "credit_analyst"))

from lfx.graph.flow_builder.flow import empty_flow  # noqa: E402
from lfx.graph.flow_builder.component import add_component  # noqa: E402
from lfx.graph.flow_builder.connect import add_connection  # noqa: E402
from lfx.graph.flow_builder.layout import layout_flow  # noqa: E402

# (module file stem, class name, node id, output port name) — in pipeline order.
COMPONENTS = [
    ("credit_application_ingest", "CreditApplicationIngestComponent", "CreditApplicationIngest", "bundle"),
    ("ratio_calculator", "RatioCalculatorComponent", "RatioCalculator", "bundle_out"),
    ("benchmark_comparator", "BenchmarkComparatorComponent", "BenchmarkComparator", "bundle_out"),
    ("policy_compliance", "PolicyComplianceComponent", "PolicyCompliance", "bundle_out"),
    ("risk_scoring", "RiskScoringComponent", "RiskScoring", "bundle_out"),
    ("memo_generator", "MemoGeneratorComponent", "MemoGenerator", "result"),
]
TARGET_INPUT = "bundle"  # every downstream component receives the bundle here


def build_registry() -> tuple[dict, list]:
    """Instantiate each component and build the {type: node_template} registry."""
    registry: dict[str, dict] = {}
    order = []
    for stem, cls_name, node_id, out_name in COMPONENTS:
        module = importlib.import_module(stem)
        comp = getattr(module, cls_name)()
        node = comp.to_frontend_node()["data"]["node"]
        registry[node_id] = node          # key the registry by our explicit node id
        order.append((node_id, out_name))
    return registry, order


def main() -> str:
    registry, order = build_registry()

    flow = empty_flow(
        name="Credit Analyst",
        description=("Automated commercial credit memo drafting: ingest -> ratios -> "
                     "benchmarks -> policy (RAG) -> risk scoring (Claude) -> PDF memo."),
    )

    # Add each component as a node with a stable, dash-free id.
    for node_id, _ in order:
        add_component(flow, node_id, registry, component_id=node_id)

    # Wire the linear chain: each output -> next component's `bundle` input.
    for (src_id, src_out), (tgt_id, _) in zip(order, order[1:]):
        add_connection(flow, src_id, src_out, tgt_id, TARGET_INPUT)

    layout_flow(flow)

    # Flow-level metadata for import + REST triggering.
    flow["endpoint_name"] = "credit-analyst"
    flow["is_component"] = False

    out_path = os.path.join(_ROOT, "flow", "credit_analyst_flow.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(flow, fh, indent=2)

    print(f"Wrote {os.path.relpath(out_path, _ROOT)}")
    print(f"  nodes: {len(flow['data']['nodes'])}  edges: {len(flow['data']['edges'])}")
    for e in flow["data"]["edges"]:
        sh = e["data"]["sourceHandle"]; th = e["data"]["targetHandle"]
        print(f"  {sh['id']}.{sh['name']} -> {th['id']}.{th['fieldName']}")
    return out_path


if __name__ == "__main__":
    main()
