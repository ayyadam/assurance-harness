"""Render the regression-report markdown from the two JSON dumps.

Run after ``RUN_AGENT_REGRESSION=1 uv run pytest tests/agents/``. Reads
``reports/regression-report-{risk,triage}.json`` and emits
``reports/regression-report.md``. Idempotent — re-run after any future
regression run to refresh the committed evidence.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _format_metrics(metrics: dict) -> str:
    parts = []
    for k, v in metrics.items():
        if isinstance(v, float):
            parts.append(f"`{k}={v:.3f}`")
        else:
            parts.append(f"`{k}={v}`")
    return " • ".join(parts)


def render() -> str:
    lines: list[str] = []
    lines.append("# Agent regression — risk_agent + triage_agent")
    lines.append("")
    lines.append(f"_Run: {date.today().isoformat()}_")
    lines.append("")
    lines.append(
        "Treats `risk_agent` and `triage_agent` as software under test. For each "
        "cached fixture, runs the agent N times against the same input and "
        "asserts invariants that should hold regardless of LLM jitter:"
    )
    lines.append("")
    lines.append(
        "- **HARD** — schema validity per run, closed-vocabulary on every emitted id/category, relevance in {2, 3}"
    )
    lines.append("- **SOFT** — top-result stability ≥ 0.66 across runs; presence-rate of expected top result ≥ 0.66")
    lines.append("")
    lines.append("Local-only, gated on `RUN_AGENT_REGRESSION=1` — not in CI. Run with:")
    lines.append("")
    lines.append("```bash")
    lines.append("RUN_AGENT_REGRESSION=1 uv run pytest tests/agents/ -v")
    lines.append("uv run python tests/agents/render_report.py")
    lines.append("```")
    lines.append("")

    # Collect cases and detect stable-divergent ones up front so the summary
    # can render them prominently and the dedicated section knows what to list.
    divergent_cases: list[tuple[str, str, dict]] = []  # (agent_label, case_id, metrics)

    # Combined summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Agent | Case | Runs | Schema | Vocab | Top-result stability | Top-match vs golden | Status |")
    lines.append("|---|---|---|---|---|---|---|---|")

    for agent_file, agent_label in (
        ("regression-report-risk.json", "risk_agent"),
        ("regression-report-triage.json", "triage_agent"),
    ):
        path = REPORTS_DIR / agent_file
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data["cases"]:
            last_metrics = (c["runs"][-1]["output"] or {}).get("_metrics", {})
            ok_runs = c["successful"]
            schema_ok = "✓" if ok_runs == c["n_runs"] else f"✗ ({ok_runs}/{c['n_runs']})"
            vocab_ok = "✓"  # test passed → vocab held
            is_divergent = bool(last_metrics.get("stable_divergent"))
            if is_divergent:
                divergent_cases.append((agent_label, c["case_id"], last_metrics))
            if agent_label == "risk_agent":
                stab = last_metrics.get("top_value_stability", 0)
                top_mode = last_metrics.get("top_value_mode", "—")
                match = last_metrics.get("expected_top_match_rate", 0)
                stab_str = f"`{top_mode}` × {stab:.0%}"
                match_str = f"**{match:.0%}**" if is_divergent else f"{match:.0%}"
            else:  # triage
                stab = last_metrics.get("category_stability", 0)
                rid_stab = last_metrics.get("rid_stability", 0)
                cat_mode = last_metrics.get("category_mode", "—")
                rid_mode = last_metrics.get("rid_mode", "—")
                cat_match = last_metrics.get("category_match_rate", 0)
                rid_match = last_metrics.get("rid_match_rate", 0)
                stab_str = f"cat=`{cat_mode}` × {stab:.0%}; rid=`{rid_mode}` × {rid_stab:.0%}"
                match_str = f"cat {cat_match:.0%}; rid {rid_match:.0%}"
                if is_divergent:
                    match_str = f"**{match_str}**"
            status = "⚠ stable-divergent" if is_divergent else "✓"
            row = (
                f"| `{agent_label}` | `{c['case_id']}` | {c['n_runs']} | "
                f"{schema_ok} | {vocab_ok} | {stab_str} | {match_str} | {status} |"
            )
            lines.append(row)
    lines.append("")

    # Dedicated stable-divergent section — only renders when there's something to flag.
    if divergent_cases:
        lines.append("## ⚠ Stable-divergent cases")
        lines.append("")
        lines.append(
            "Cases where the agent's answer was *internally stable* across runs "
            "(no LLM-jitter explanation) but *disagreed with the golden truth* on "
            "the top-1 result. Hard invariants (schema, closed-vocab) still held, "
            "so the test passed. These are documented prompt or golden-set "
            "divergences worth investigating — not regression failures."
        )
        lines.append("")
        for agent_label, case_id, m in divergent_cases:
            lines.append(f"### `{agent_label}` / `{case_id}`")
            lines.append("")
            if agent_label == "risk_agent":
                lines.append(
                    f"- Agent's stable top-1: `{m.get('top_value_mode')}` "
                    f"(stability {m.get('top_value_stability', 0):.0%})"
                )
                lines.append(f"- Top-match vs golden: **{m.get('expected_top_match_rate', 0):.0%}**")
                lines.append(
                    f"- Expected-top presence (anywhere in ranking): {m.get('expected_top_presence_rate', 0):.0%}"
                )
            else:
                lines.append(
                    f"- Category mode: `{m.get('category_mode')}` × {m.get('category_stability', 0):.0%}; "
                    f"match vs expected: **{m.get('category_match_rate', 0):.0%}**"
                )
                lines.append(
                    f"- R-ID mode: `{m.get('rid_mode')}` × {m.get('rid_stability', 0):.0%}; "
                    f"match vs expected: **{m.get('rid_match_rate', 0):.0%}**"
                )
            lines.append("")
        lines.append("")

    # Per-agent detail
    for agent_file, agent_label, agent_blurb in (
        (
            "regression-report-risk.json",
            "risk_agent",
            "Top-value stability = how often the highest-ranked R-ID was the same across runs. "
            "Expected-top hit-rate = how often the golden-set's expected top R-ID appeared *anywhere* in the ranking.",
        ),
        (
            "regression-report-triage.json",
            "triage_agent",
            "Stability of the emitted category and candidate R-ID across runs. "
            "Triage outputs are a single (category, R-ID), so a perfect run set "
            "is `category_stability=1.0`, `rid_stability=1.0`.",
        ),
    ):
        path = REPORTS_DIR / agent_file
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        lines.append(f"## `{agent_label}` — detail")
        lines.append("")
        lines.append(agent_blurb)
        lines.append("")
        for c in data["cases"]:
            last_metrics = (c["runs"][-1]["output"] or {}).get("_metrics", {})
            lines.append(f"### `{c['case_id']}`")
            lines.append("")
            lines.append(f"- **Runs:** {c['successful']} / {c['n_runs']} successful")
            elapsed = sum(r["elapsed_s"] for r in c["runs"])
            lines.append(f"- **Elapsed (total):** {elapsed:.1f} s")
            if last_metrics:
                lines.append(f"- **Metrics:** {_format_metrics(last_metrics)}")
            # Per-run summary one-liner
            lines.append("")
            lines.append("| Run | Elapsed (s) | Result |")
            lines.append("|---|---|---|")
            for r in c["runs"]:
                if r["error"]:
                    summary = f"ERROR — {r['error']}"
                elif agent_label == "risk_agent":
                    rr = r["output"].get("ranked_risks") or []
                    summary = ", ".join(f"`{x['id']}`({x['relevance']})" for x in rr) if rr else "(no risks emitted)"
                else:
                    cat = r["output"].get("category", "—")
                    rid = r["output"].get("candidate_risk_id") or "null"
                    summary = f"cat=`{cat}` rid=`{rid}`"
                lines.append(f"| {r['n']} | {r['elapsed_s']:.1f} | {summary} |")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `tests/agents/render_report.py` (phase 12 v2 v2). "
        "Source: cached JSON in this directory. Re-run after a new "
        "`RUN_AGENT_REGRESSION=1 pytest tests/agents/` pass to refresh._"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    md = render()
    out = REPORTS_DIR / "regression-report.md"
    out.write_text(md, encoding="utf-8")
    print(f"Wrote: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
