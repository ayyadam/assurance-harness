"""Security scanning — SAST (Bandit) + SCA (pip-audit) + secrets (gitleaks).

The non-functional **security** layer (B1). One orchestrator, runnable locally
and in CI, so *what* security scanning runs and *how it gates* never drift. The
gating posture is the "ratchet" agreed for B1:

  - secrets  (gitleaks)  : HARD gate — any finding fails the build.
  - SCA      (pip-audit) : gate on ANY vulnerability whose ID is not in the
                           allowlist (``sca_allowlist.txt``); accepted CVEs are
                           recorded there with a risk-register pointer.
  - SAST     (bandit)    : advisory — reported, never fails (yet). Ratchets to a
                           gate once the baseline is clean.

Targets: SAST and app-SCA run against the SUT (golf-web-app, the system under
assurance); SCA also covers the harness's own environment; secret scanning covers
both repos. CodeQL (deeper SAST) and OWASP ZAP (DAST) run as their own CI jobs.

Raw JSON per tool is written under ``reports/`` (git-ignored) for CI artifact
upload; the human summary prints to stdout. Exit code reflects the gate.

Usage:
  uv run python nonfunctional/security/scan.py                 # scan + gate
  uv run python nonfunctional/security/scan.py --sut ../golf-web-app
  uv run python nonfunctional/security/scan.py --no-gate       # report only (exit 0)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # assurance-harness/
DEFAULT_SUT = ROOT.parent / "golf-web-app"
ALLOWLIST_FILE = HERE / "sca_allowlist.txt"
REPORTS_DIR = HERE / "reports"


def _run(cmd: list[str]) -> str:
    """Run a command, return stdout (stderr captured, never raises on exit code)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    return proc.stdout


def _read_sca_allowlist() -> list[str]:
    """Vulnerability IDs accepted for this round (one per non-comment line)."""
    if not ALLOWLIST_FILE.exists():
        return []
    ids: list[str] = []
    for raw in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            ids.append(line.split()[0])
    return ids


def run_bandit(sut: Path) -> list[dict]:
    """SAST over the SUT application code. Advisory — returns the findings.

    JSON only (artifact + summary); deep SAST on the GitHub Security tab is
    provided by the CodeQL job, so bandit does not need the SARIF formatter plugin.
    """
    targets = [str(p) for p in (sut / "app", sut / "seed.py", sut / "run.py") if p.exists()]
    report = REPORTS_DIR / "bandit.json"
    _run(["bandit", "-r", *targets, "-f", "json", "-o", str(report), "-q"])
    if not report.exists():
        return []
    data = json.loads(report.read_text(encoding="utf-8") or "{}")
    return data.get("results", [])


def run_pip_audit(pip_args: list[str], ignore: list[str], fname: str) -> list[dict]:
    """SCA via pip-audit. Returns vulnerabilities NOT in the allowlist."""
    cmd = ["pip-audit", "--format", "json", *pip_args]
    for vid in ignore:
        cmd += ["--ignore-vuln", vid]
    stdout = _run(cmd)
    data = json.loads(stdout) if stdout.strip().startswith("{") else {"dependencies": []}
    (REPORTS_DIR / fname).write_text(json.dumps(data, indent=2), encoding="utf-8")
    vulns: list[dict] = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            vulns.append(
                {
                    "package": dep.get("name"),
                    "version": dep.get("version"),
                    "id": v.get("id"),
                    "fix": v.get("fix_versions"),
                }
            )
    return vulns


def run_gitleaks(targets: list[tuple[str, Path]]) -> list[dict] | None:
    """Secret scan (git history + tree). None if gitleaks is not installed.

    ``targets`` is a list of ``(role, path)`` pairs (e.g. ``("harness", ...)``,
    ``("sut", ...)``). The SARIF filename encodes the *role*, not the checkout
    directory name, so the outputs are stable across a harness self-run and a
    reusable-workflow call (where the harness lands in a dir named after the
    caller). Each SARIF is then uploaded to the GitHub Security tab under its own
    category — code scanning rejects multiple SARIF runs sharing one category.

    Emits one SARIF per role and returns the flattened results for the hard-gate
    count.
    """
    if not shutil.which("gitleaks"):
        return None
    findings: list[dict] = []
    for role, p in targets:
        sarif = REPORTS_DIR / f"gitleaks-{role}.sarif"
        _run(
            [
                "gitleaks",
                "detect",
                "--source",
                str(p),
                "--report-format",
                "sarif",
                "--report-path",
                str(sarif),
                "--no-banner",
                "--exit-code",
                "0",
            ]
        )
        if sarif.exists():
            data = json.loads(sarif.read_text(encoding="utf-8") or "{}")
            for run in data.get("runs", []):
                findings += run.get("results", [])
    return findings


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Security scanning — SAST + SCA + secrets (B1).")
    parser.add_argument("--sut", default=str(DEFAULT_SUT), help="Path to the SUT checkout (golf-web-app).")
    parser.add_argument("--no-gate", action="store_true", help="Report only; always exit 0.")
    args = parser.parse_args(argv)
    sut = Path(args.sut).resolve()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ignore = _read_sca_allowlist()

    print("# Security scan (B1 — SAST / SCA / secrets)\n")
    print(f"SUT: `{sut}`  •  SCA allowlist: {len(ignore)} id(s)\n")

    # ── SAST (advisory) ──
    bandit_findings = run_bandit(sut)
    sev = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in bandit_findings:
        sev[f.get("issue_severity", "LOW")] = sev.get(f.get("issue_severity", "LOW"), 0) + 1
    print(
        f"## SAST (bandit) — advisory\n\n{len(bandit_findings)} finding(s): "
        f"HIGH={sev['HIGH']} MED={sev['MEDIUM']} LOW={sev['LOW']}"
    )
    for f in bandit_findings:
        loc = f.get("filename", "").split("golf-web-app")[-1]
        print(
            f"  - [{f.get('issue_severity')}/{f.get('issue_confidence')}] {f.get('test_id')} "
            f"{loc}:{f.get('line_number')} — {f.get('issue_text', '')[:80]}"
        )

    # ── SCA (gate any non-allowlisted) ──
    sca: list[dict] = []
    for req in (p for p in (sut / "requirements.txt", sut / "requirements-dev.txt") if p.exists()):
        sca += run_pip_audit(["-r", str(req)], ignore, f"pip-audit-sut-{req.stem}.json")
    sca += run_pip_audit([], ignore, "pip-audit-harness.json")  # harness environment
    print(f"\n## SCA (pip-audit) — gate any non-allowlisted\n\n{len(sca)} non-allowlisted vuln(s):")
    for v in sca:
        print(f"  - {v['package']} {v['version']} — {v['id']} (fix: {v['fix'] or 'none'})")

    # ── secrets (hard gate) ──
    gitleaks = run_gitleaks([("harness", ROOT), ("sut", sut)])
    if gitleaks is None:
        print("\n## secrets (gitleaks) — hard gate\n\n  (skipped — gitleaks not installed; runs in CI)")
    else:
        print(f"\n## secrets (gitleaks) — hard gate\n\n{len(gitleaks)} finding(s)")
        for g in gitleaks[:20]:
            loc = g.get("locations", [{}])[0].get("physicalLocation", {}).get("artifactLocation", {}).get("uri", "?")
            print(f"  - {g.get('ruleId', '?')} {loc}")

    # ── gate ──
    secrets_fail = bool(gitleaks)
    sca_fail = bool(sca)
    gate_failed = secrets_fail or sca_fail
    print("\n## Gate\n")
    print(f"  secrets : {'FAIL' if secrets_fail else 'pass'} (hard gate)")
    print(f"  SCA     : {'FAIL' if sca_fail else 'pass'} (any non-allowlisted)")
    print(f"  SAST    : advisory ({len(bandit_findings)} finding(s) — not gating)")
    print(f"\nRESULT: {'FAIL' if gate_failed else 'PASS'}")

    if args.no_gate:
        return 0
    return 1 if gate_failed else 0


if __name__ == "__main__":
    sys.exit(main())
