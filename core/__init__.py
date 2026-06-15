"""Shared harness infrastructure that is NOT pillar-specific.

Home for the cross-cutting seams that make the harness re-pointable (Workstream
B / G1, personal-toolkit sense): the declarative SUT `profile` today, and the
pluggable LLM provider later. Pillars import from here instead of hardcoding
SUT-specific facts.
"""
