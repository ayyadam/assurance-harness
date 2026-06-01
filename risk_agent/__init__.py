"""Risk-prioritisation agent (phase 9).

Given a PR diff and the project's risk register, the agent produces a ranked
test plan: which risks are most plausibly raised by this change, which test
layer already covers each, where the coverage gaps are, and a short list of
exploratory probes a human reviewer should consider.

Determinism boundary: the agent is *advisory*, not a gate. It runs locally on
demand against an Ollama model. The structured-output schema constrains the
shape of the response so the markdown rendering is deterministic; the ranking
itself is the judgement layer.
"""
