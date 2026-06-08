"""Collect + normalise security findings into a common ``Finding`` shape.

The deterministic spine of the security agent. It runs the *raw* scanners (no
allowlist applied — the agent must see what the gate suppresses in order to
judge it) and flattens every tool's output into one ``Finding`` record the LLM
can reason over uniformly.

Sources:
  - bandit   (SAST) over the SUT application code (native JSON).
  - pip-audit (SCA) over the SUT ``requirements.txt`` + ``requirements-dev.txt``,
    run RAW (no ``--ignore-vuln``) so the allowlisted CVEs are visible for the
    agent to re-derive the allowlist recommendation itself (native JSON).
  - gitleaks (secrets) over the harness + SUT repos (SARIF). Skipped if the
    gitleaks binary is absent. Secret *values* are redacted — the judge keys off
    the rule id and file path (fixture/example vs app/config), never the match.
  - any SARIF file passed via ``--sarif`` — the agent is SARIF-native, so CodeQL
    (CI → GitHub code-scanning, fetched as SARIF) or any other SARIF tool can be
    judged through the same generic normaliser. ZAP (DAST) does not emit SARIF
    by default and is out of this scope.

Raw tool output is cached under ``reports/raw/`` (gitignored — snippets echo SUT
source). ``--refresh`` re-runs the scanners; the default reads the cache so
re-judging after a prompt change is free.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # assurance-harness/
DEFAULT_SUT = ROOT.parent / "golf-web-app"
RAW_DIR = HERE / "reports" / "raw"


@dataclass
class Finding:
    """One normalised security finding, pre-judgement.

    ``signature`` is the stable identity used both to dedupe (the same CVE shows
    up in requirements.txt AND requirements-dev.txt) and to match against the
    golden set.
    """

    tool: str  # "bandit" | "pip-audit"
    kind: str  # "SAST" | "SCA"
    rule_id: str  # bandit test_id (B105) or CVE id
    location: str  # "app/api/auth.py:16" or "flask 3.1.0"
    severity: str  # tool-reported; pip-audit has none -> "UNKNOWN"
    confidence: str  # bandit confidence; "" for SCA
    title: str  # human summary of the issue
    detail: str  # snippet / fix-version hint for the prompt
    fix: str = ""  # SCA fix version(s); "" for SAST. Used by write-back to render allowlist lines.

    # ── filled by the LLM judge ──
    verdict: str = ""  # "true_positive" | "false_positive" | "expected_by_design"
    disposition: str = ""  # "remediate" | "allowlist" | "accept"
    candidate_risk_id: str | None = None
    rationale: str = ""

    @property
    def signature(self) -> tuple[str, str, str]:
        return (self.tool, self.rule_id, self.location)


def _run(cmd: list[str]) -> str:
    """Run a command, return stdout (never raises on exit code)."""
    proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    return proc.stdout


# ── bandit (SAST) ──────────────────────────────────────────────────────────


def collect_bandit(sut: Path, refresh: bool) -> list[Finding]:
    cache = RAW_DIR / "bandit.json"
    if refresh or not cache.exists():
        targets = [str(p) for p in (sut / "app", sut / "seed.py", sut / "run.py") if p.exists()]
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        _run(["bandit", "-r", *targets, "-f", "json", "-o", str(cache), "-q"])
    if not cache.exists():
        return []
    data = json.loads(cache.read_text(encoding="utf-8") or "{}")
    findings: list[Finding] = []
    for r in data.get("results", []):
        loc = str(r.get("filename", "")).split("golf-web-app")[-1].replace("\\", "/").lstrip("/")
        cwe = (r.get("issue_cwe") or {}).get("id")
        findings.append(
            Finding(
                tool="bandit",
                kind="SAST",
                rule_id=r.get("test_id", "?"),
                location=f"{loc}:{r.get('line_number')}",
                severity=r.get("issue_severity", "UNKNOWN"),
                confidence=r.get("issue_confidence", ""),
                title=r.get("issue_text", ""),
                detail=(
                    f"rule={r.get('test_id')} ({r.get('test_name')}) CWE-{cwe}\n"
                    f"code: {(r.get('code') or '').strip()[:200]}"
                ),
            )
        )
    return findings


# ── pip-audit (SCA) ────────────────────────────────────────────────────────


def collect_pip_audit(sut: Path, refresh: bool) -> list[Finding]:
    """Raw SCA over the SUT's requirement files. Dedupes by (package, CVE)."""
    reqs = [p for p in (sut / "requirements.txt", sut / "requirements-dev.txt") if p.exists()]
    by_sig: dict[tuple[str, str, str], Finding] = {}
    for req in reqs:
        cache = RAW_DIR / f"pip-audit-{req.stem}.json"
        if refresh or not cache.exists():
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            stdout = _run(["pip-audit", "--format", "json", "-r", str(req)])
            data = json.loads(stdout) if stdout.strip().startswith("{") else {"dependencies": []}
            cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            data = json.loads(cache.read_text(encoding="utf-8") or "{}")
        for dep in data.get("dependencies", []):
            for v in dep.get("vulns", []):
                fix = v.get("fix_versions") or []
                f = Finding(
                    tool="pip-audit",
                    kind="SCA",
                    rule_id=v.get("id", "?"),
                    location=f"{dep.get('name')} {dep.get('version')}",
                    severity="UNKNOWN",  # pip-audit does not expose CVSS reliably
                    confidence="",
                    title=f"{dep.get('name')} {dep.get('version')} affected by {v.get('id')}",
                    detail=(
                        f"fix: {', '.join(fix) if fix else 'none'}; "
                        f"found in {req.name}; "
                        f"{(v.get('description') or '').strip()[:200]}"
                    ),
                    fix=", ".join(fix),
                )
                by_sig[f.signature] = f  # dedup flask/dotenv across both req files
    return list(by_sig.values())


# ── SARIF (gitleaks secrets + any SARIF tool, e.g. CodeQL) ─────────────────

_SARIF_SEVERITY = {"error": "HIGH", "warning": "MEDIUM", "note": "LOW", "none": "LOW"}


def normalize_sarif(path: Path, kind: str, redact: bool = False) -> list[Finding]:
    """Parse any SARIF log into Finding records — the generic, tool-agnostic path.

    ``redact`` is set for secret scanners so the matched value never reaches the
    committed report; the judge keys off the rule id and file path instead.
    """
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    findings: list[Finding] = []
    for run in data.get("runs", []):
        tool = (run.get("tool", {}).get("driver", {}) or {}).get("name", "sarif")
        for r in run.get("results", []):
            rule = r.get("ruleId", "?")
            sev = _SARIF_SEVERITY.get(r.get("level", "warning"), "MEDIUM")
            locs = r.get("locations") or [{}]
            phys = (locs[0] or {}).get("physicalLocation", {})
            uri = (phys.get("artifactLocation", {}) or {}).get("uri", "?")
            line = (phys.get("region", {}) or {}).get("startLine")
            location = f"{uri}:{line}" if line else uri
            msg = (r.get("message", {}) or {}).get("text", "") or ""
            if redact:
                title = f"potential secret ({rule})"
                detail = f"rule={rule}; secret value redacted; judge from path + rule"
            else:
                title = msg[:120]
                detail = f"rule={rule}; {msg[:160]}"
            findings.append(
                Finding(
                    tool=tool,
                    kind=kind,
                    rule_id=rule,
                    location=location,
                    severity=sev,
                    confidence="",
                    title=title,
                    detail=detail,
                )
            )
    return findings


def collect_gitleaks(sut: Path, refresh: bool) -> list[Finding]:
    """Secret scan over the harness + SUT repos. [] if gitleaks is not installed."""
    if not shutil.which("gitleaks"):
        return []
    findings: list[Finding] = []
    for repo in (ROOT, sut):
        cache = RAW_DIR / f"gitleaks-{repo.name}.sarif"
        if refresh or not cache.exists():
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            _run(
                [
                    "gitleaks",
                    "detect",
                    "--source",
                    str(repo),
                    "--report-format",
                    "sarif",
                    "--report-path",
                    str(cache),
                    "--no-banner",
                    "--exit-code",
                    "0",
                ]
            )
        if cache.exists():
            findings += normalize_sarif(cache, kind="secret", redact=True)
    return findings


def collect_sarif_files(paths: list[str]) -> list[Finding]:
    """Ingest externally-provided SARIF (e.g. a CodeQL log fetched from CI)."""
    findings: list[Finding] = []
    for p in paths:
        path = Path(p)
        if path.exists():
            findings += normalize_sarif(path, kind="SAST")
    return findings


def collect_findings(sut: Path, refresh: bool = False, sarif_paths: list[str] | None = None) -> list[Finding]:
    """All in-scope findings (SAST + SCA + secrets + any SARIF), deduped + ordered."""
    findings = (
        collect_bandit(sut, refresh)
        + collect_pip_audit(sut, refresh)
        + collect_gitleaks(sut, refresh)
        + collect_sarif_files(sarif_paths or [])
    )
    # Stable order: kind, then rule_id, then location — deterministic reports.
    return sorted(findings, key=lambda f: (f.kind, f.rule_id, f.location))
