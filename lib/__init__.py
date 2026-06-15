"""Core, framework-agnostic credit-analysis logic.

These modules contain the real pipeline logic and have no dependency on
Langflow. The Langflow custom components in ``components/`` import and wrap
them, and ``tests/run_pipeline.py`` calls them directly so the whole pipeline
can be verified without a running Langflow server.
"""
