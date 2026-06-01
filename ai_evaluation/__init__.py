"""AI evaluation harness for the golf-web-app booking assistant.

Replays a labelled golden set of natural-language requests through the SUT's
live endpoint (black-box) and scores the extracted intent. Deterministic field
scoring is the workhorse; an LLM-judge tier is layered on for fuzzy cases.
"""
