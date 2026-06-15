"""Shared path bootstrap for the Credit Analyst custom components.

Langflow loads each component file in its own process/namespace, so every
component imports this helper to put the project root (which contains ``lib/``)
on ``sys.path``. The root is resolved from, in order:

1. the ``CREDIT_ANALYST_ROOT`` environment variable, then
2. the parent directory of this file (``components/`` -> project root).

It also exposes default paths to the bundled data files so components can offer
sensible defaults in the Langflow UI.
"""

from __future__ import annotations

import os
import sys


def project_root() -> str:
    env = os.environ.get("CREDIT_ANALYST_ROOT")
    if env and os.path.isdir(env):
        root = env
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


ROOT = project_root()
DEFAULT_BENCHMARK_CSV = os.path.join(ROOT, "data", "benchmarks", "industry_benchmarks.csv")
DEFAULT_POLICY_MD = os.path.join(ROOT, "data", "policy", "credit_policy.md")
DEFAULT_CHROMA_DIR = os.path.join(ROOT, ".chroma")
DEFAULT_INPUT_DIR = os.path.join(ROOT, "inputs")
DEFAULT_SAMPLES_DIR = os.path.join(ROOT, "samples")
DEFAULT_OUTPUT_DIR = os.path.join(ROOT, "outputs")
