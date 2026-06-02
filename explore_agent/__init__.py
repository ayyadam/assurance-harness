"""Exploratory testing agent — API-level (phase 12 v1 v1).

Drives from the live OpenAPI spec, asks an LLM to propose request payload
variants per endpoint (happy / edge / abusive), sends them, then asks the
LLM to classify each response. Output is a markdown + JSON findings report.

Local-only by design — same cadence as risk_agent and triage_agent. See
``explore_agent/README.md`` for quick start.
"""
