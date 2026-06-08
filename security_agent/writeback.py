"""Write-back — reconcile the agent's judgement against the live SCA allowlist.

The security agent (``run.py``) judges each finding but changes nothing. This
step closes the loop: it compares the agent's ``allowlist``-disposition findings
(cached in ``reports/report.json``) against the live
``nonfunctional/security/sca_allowlist.txt`` and proposes a diff. Mirrors
``risk_agent``'s propose-don't-apply stance — it advises; a human (or ``--apply``)
commits the change.

Reconciliation runs in both directions:

  - in_sync      : CVE is in the allowlist AND the agent judges it ``allowlist``.
  - propose_add  : agent judges ``allowlist`` but the CVE is not in the file yet.
  - propose_remove (re-arm) : a CVE is in the file but the agent did not encounter
                   it this run — the dependency was bumped/removed, so the line
                   suppresses nothing and the gate should re-arm.
  - conflict     : the CVE is in the file but the agent now judges it something
                   other than ``allowlist`` (e.g. ``remediate``). Flagged for a
                   human — never auto-changed (a judgement disagreement is not a
                   mechanical edit).

Default is **propose**: print + write a reconciliation report and a unified diff,
touching nothing. ``--apply`` rewrites the allowlist — adding proposed lines and
removing only the *stale* (re-arm) entries; conflicts are never auto-applied.

Usage:
  uv run python -m security_agent.writeback              # propose (no file change)
  uv run python -m security_agent.writeback --apply      # apply adds + stale removals
  uv run python -m security_agent.writeback --refresh    # re-run the agent first, then propose
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # assurance-harness/
ALLOWLIST_FILE = ROOT / "nonfunctional" / "security" / "sca_allowlist.txt"
REPORTS_DIR = HERE / "reports"


@dataclass
class Reconciliation:
    in_sync: list[str] = field(default_factory=list)  # CVE ids present + agreed
    propose_add: list[dict] = field(default_factory=list)  # {cve, line, finding}
    propose_remove: list[dict] = field(default_factory=list)  # {cve, line} — stale / re-arm
    conflict: list[dict] = field(default_factory=list)  # {cve, line, disposition}

    @property
    def has_changes(self) -> bool:
        return bool(self.propose_add or self.propose_remove or self.conflict)


def load_report(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def parse_allowlist(path: Path) -> tuple[list[str], dict[str, str]]:
    """Return (raw lines, {cve_id: full_line}) for the live allowlist."""
    if not path.exists():
        return [], {}
    raw = path.read_text(encoding="utf-8").splitlines()
    by_id: dict[str, str] = {}
    for line in raw:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            by_id[stripped.split()[0]] = line
    return raw, by_id


def _add_line(f: dict) -> str:
    """Render an allowlist line for a newly-justified CVE, in the file's format."""
    cve = f["rule_id"]
    pkg_ver = f.get("location", "").strip()
    fix = f.get("fix") or "see advisory"
    rid = f.get("candidate_risk_id") or "R-???"
    return f"{cve}   # {pkg_ver} -> {fix} ({rid})"


def reconcile(report: list[dict], file_ids: dict[str, str]) -> Reconciliation:
    sca = [f for f in report if f.get("tool") == "pip-audit"]
    run_ids = {f["rule_id"] for f in sca}
    allow = {f["rule_id"]: f for f in sca if f.get("disposition") == "allowlist"}
    not_allow = {f["rule_id"]: f for f in sca if f.get("disposition") != "allowlist"}

    rec = Reconciliation()
    for cve in sorted(allow):
        if cve in file_ids:
            rec.in_sync.append(cve)
        else:
            rec.propose_add.append({"cve": cve, "line": _add_line(allow[cve]), "finding": allow[cve]})
    for cve in sorted(file_ids):
        if cve in run_ids:
            if cve in not_allow:  # encountered, but judged not-allowlist
                rec.conflict.append(
                    {"cve": cve, "line": file_ids[cve], "disposition": not_allow[cve].get("disposition")}
                )
        else:  # not encountered at all this run → stale, re-arm
            rec.propose_remove.append({"cve": cve, "line": file_ids[cve]})
    return rec


def apply_changes(raw: list[str], rec: Reconciliation) -> str:
    """New allowlist content: drop stale lines, append proposed additions. Conflicts untouched."""
    stale = {r["cve"] for r in rec.propose_remove}
    kept: list[str] = []
    for line in raw:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.split()[0] in stale:
            continue
        kept.append(line)
    if rec.propose_add:
        if kept and kept[-1].strip():
            kept.append("")
        kept.append("# Proposed by security_agent.writeback:")
        kept.extend(r["line"] for r in rec.propose_add)
    return "\n".join(kept) + "\n"


def render_diff(rec: Reconciliation) -> str:
    if not rec.has_changes:
        return "```\n(no changes — allowlist is in sync with the agent's judgement)\n```"
    lines = ["```diff"]
    for r in rec.propose_remove:
        lines.append(f"- {r['line']}    # re-arm: {r['cve']} no longer present in the scan")
    for r in rec.conflict:
        lines.append(f"! {r['line']}    # conflict: agent now judges this '{r['disposition']}' (review)")
    for r in rec.propose_add:
        lines.append(f"+ {r['line']}")
    lines.append("```")
    return "\n".join(lines)


def render_markdown(rec: Reconciliation, applied: bool, today: date | None = None) -> str:
    today = today or date.today()
    out: list[str] = []
    out.append("# security_agent — allowlist write-back")
    out.append("")
    out.append(f"_Run: {today.isoformat()}_  •  mode: **{'apply' if applied else 'propose'}**")
    out.append("")
    out.append(
        "Reconciles the agent's `allowlist`-disposition findings (cached in "
        "[`reports/report.json`](report.json)) against the live "
        "[`nonfunctional/security/sca_allowlist.txt`](../../nonfunctional/security/sca_allowlist.txt). "
        "Propose-by-default; `--apply` adds proposed lines and removes only stale (re-arm) entries."
    )
    out.append("")
    out.append("## Reconciliation")
    out.append("")
    out.append("| State | Count | CVEs |")
    out.append("|---|---|---|")
    out.append(f"| in sync | {len(rec.in_sync)} | {', '.join(rec.in_sync) or '—'} |")
    out.append(f"| propose add | {len(rec.propose_add)} | {', '.join(r['cve'] for r in rec.propose_add) or '—'} |")
    out.append(
        f"| propose remove (re-arm) | {len(rec.propose_remove)} | "
        f"{', '.join(r['cve'] for r in rec.propose_remove) or '—'} |"
    )
    out.append(f"| conflict (review) | {len(rec.conflict)} | {', '.join(r['cve'] for r in rec.conflict) or '—'} |")
    out.append("")
    out.append("## Proposed diff")
    out.append("")
    out.append(render_diff(rec))
    out.append("")
    if applied:
        out.append("**Applied** — additions written and stale entries removed. Conflicts (if any) left for review.")
    elif rec.has_changes:
        out.append("Run with `--apply` to write the additions + stale removals. Conflicts are never auto-applied.")
    else:
        out.append("Nothing to apply.")
    out.append("")
    out.append("---")
    out.append("")
    out.append("_Generated by `security_agent.writeback`._")
    out.append("")
    return "\n".join(out)


def to_json(rec: Reconciliation, applied: bool) -> str:
    return json.dumps(
        {
            "mode": "apply" if applied else "propose",
            "in_sync": rec.in_sync,
            "propose_add": [{"cve": r["cve"], "line": r["line"]} for r in rec.propose_add],
            "propose_remove": rec.propose_remove,
            "conflict": rec.conflict,
        },
        indent=2,
    )


def refresh_run(sut: str, model: str, host: str | None) -> None:
    from security_agent.run import main as agent_main

    argv = ["--sut", sut, "--refresh", "--model", model]
    if host:
        argv += ["--host", host]
    rc = agent_main(argv)
    if rc != 0:
        raise RuntimeError(f"security_agent.run refresh failed with rc={rc}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="security_agent — reconcile + propose SCA allowlist diffs.")
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST_FILE)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--apply", action="store_true", help="Write the proposed additions + stale removals.")
    parser.add_argument("--refresh", action="store_true", help="Re-run the agent before reconciling (slow).")
    parser.add_argument("--sut", default="../golf-web-app", help="SUT path for --refresh.")
    parser.add_argument("--model", default="qwen2.5:32b-instruct-q4_K_M")
    parser.add_argument("--host", default=None)
    parser.add_argument("--no-write", action="store_true", help="Print but do not save the write-back report.")
    args = parser.parse_args(argv)

    if args.refresh:
        print("refreshing security report...", file=sys.stderr)
        refresh_run(args.sut, args.model, args.host)

    report = load_report(args.reports_dir / "report.json")
    raw, file_ids = parse_allowlist(args.allowlist)
    rec = reconcile(report, file_ids)

    if args.apply and rec.has_changes and (rec.propose_add or rec.propose_remove):
        args.allowlist.write_text(apply_changes(raw, rec), encoding="utf-8")
        print(f"applied: +{len(rec.propose_add)} / -{len(rec.propose_remove)} → {args.allowlist}", file=sys.stderr)

    md = render_markdown(rec, applied=args.apply)
    print(md)

    if not args.no_write:
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        (args.reports_dir / "writeback-report.md").write_text(md, encoding="utf-8")
        (args.reports_dir / "writeback-report.json").write_text(to_json(rec, args.apply), encoding="utf-8")
        print(
            f"\nWrote: {args.reports_dir / 'writeback-report.md'}\n       {args.reports_dir / 'writeback-report.json'}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
