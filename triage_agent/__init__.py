"""Triage agent (phase 10).

Clusters failed CI runs by likely root cause and assigns a category (flake /
defect / infra / env). Cross-references against the risk register so each
cluster carries a candidate R-ID where one applies.

Determinism boundary: the parser, fetcher, and heuristic grouping are
deterministic. The LLM (Ollama) supplies the cluster *category* and rationale,
and the candidate R-ID — the judgement layer. Advisory only.
"""
