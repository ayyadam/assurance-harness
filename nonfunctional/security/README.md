# Security (non-functional) — B1

The security discipline of the non-functional layer, a peer of
[`accessibility/`](../accessibility/) and [`performance/`](../performance/).
Security is a quality attribute (an "-ility"), so it lives under `nonfunctional/`
rather than as its own top level. It applies the same shift-left, gate-in-CI
posture as the rest of the spine.

> Scope of B1 (this round): **deterministic scanning** — SAST, SCA, secret
> scanning, and a DAST baseline. The *interpretation* layer (a `security_agent`
> that clusters findings against the risk register, mirroring `triage_agent`)
> is a tracked fast-follow and would live in the agentic layer, not here.

## What runs

| Technique | Tool | Target | Gate (ratchet) |
|---|---|---|---|
| **SAST** (static analysis) | Bandit | SUT app code | advisory |
| **SAST** (deep dataflow) | CodeQL (CI) | SUT/harness Python | advisory → Security tab |
| **SCA** (dependency CVEs) | pip-audit | SUT requirements + harness env | gate any non-allowlisted |
| **secrets** | gitleaks | both repos (history + tree) | hard gate |
| **DAST** (live) | OWASP ZAP baseline | running SUT | advisory *(B1b)* |

### The ratchet gating posture

Security scanners are noisy on day one, so we **ratchet** rather than hard-gate
everything immediately:

- **secrets → hard gate.** Any committed secret fails the build, now.
- **SCA → gate any non-allowlisted vuln.** pip-audit fails on any known CVE
  whose ID is not in [`sca_allowlist.txt`](sca_allowlist.txt). Accepted CVEs are
  listed there with a risk-register pointer (R-020) and a remediation note.
  (pip-audit does not expose CVSS reliably, so we gate on *presence*, not
  severity; the allowlist controls noise. Trivy is the upgrade path if true
  severity-based gating is wanted later.)
- **SAST (Bandit, CodeQL) → advisory.** Reported, not gating yet; ratchets to a
  gate once the baseline is clean.
- **DAST (ZAP baseline) → advisory.**

### Findings handling — detect + report

B1 **detects and reports**; it does not remediate the SUT this round. Real
findings are triaged into [`docs/risk-register.md`](../../docs/risk-register.md)
(e.g. R-020 for the dependency CVEs); remediation is tracked separately. See
**F-029** in [`docs/test-strategy.md`](../../docs/test-strategy.md) for the
write-up and the baseline triage.

## Running it

```bash
# SUT must be checked out as a sibling (default ../golf-web-app)
uv run python nonfunctional/security/scan.py
uv run python nonfunctional/security/scan.py --sut ../golf-web-app
uv run python nonfunctional/security/scan.py --no-gate     # report only (exit 0)
```

`scan.py` is the single source of truth for *what runs* and *how it gates*
(secrets + SCA via exit code; SAST advisory). It writes raw JSON per tool under
`reports/` (git-ignored) for CI artifact upload and prints a human summary.
gitleaks is skipped locally if its binary is absent; CI installs it. CodeQL and
ZAP run as their own CI jobs (not via `scan.py`).

Reports are **CI artifacts + the GitHub Security tab (SARIF)**, not committed —
matching the accessibility/performance convention, not the advisory agent
layers (which do commit their reports).
