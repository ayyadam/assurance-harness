"""Agent regression suite — phase 12 v2 v2.

Treats `risk_agent` and `triage_agent` as software under test. The eval
tiers already measure *accuracy* (does the agent get the right answer);
this suite measures *stability under LLM jitter* — does the agent give the
same answer when run multiple times against the same input, and do its
closed-vocabulary contracts hold every time.

Local-only: each test runs the agent N times against cached fixtures, which
takes minutes per case. Gated on the ``RUN_AGENT_REGRESSION`` env var so it
does not slow the default `pytest` run or the CI gate.

Run with:

    RUN_AGENT_REGRESSION=1 uv run pytest tests/agents/ -v
"""
