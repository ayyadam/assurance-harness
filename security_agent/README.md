# Security agent (B1c)

The agentic-layer interpreter over the security findings produced by the
deterministic [`nonfunctional/security/`](../nonfunctional/security/) gate (B1).
The scanners **detect**; this agent **judges**. It is the mirror of
[`triage_agent`](../triage_agent/) — same heuristic-spine / LLM-judgement /
golden-set-eval shape — applied to SAST + SCA findings instead of CI failures.
Advisory, per [test strategy](../docs/test-strategy.md) Principle 5: judgement,
not a gate.

## Why it earns its place

Security scanners are noisy on day one — that is the single biggest reason
shift-left security gets ignored. A reviewer who sees *"3 SAST hits, 4
dependency CVEs"* has to do the same tedious triage every run: which of these is
a real problem, which is the scanner pattern-matching a non-secret string, and
which already has an owning risk-register row.

This agent does that triage and shows its working. Per finding it returns:

- **verdict** — `true_positive` / `false_positive` / `expected_by_design`. This is
  the headline: it turns *"3 scary red SAST hits"* into *"0 real, 3 explained."*
- **disposition** — `remediate` / `allowlist` / `accept`.
- **candidate_risk_id** — a register cross-reference (closed-vocabulary enum: the
  model can only pick an R-ID that exists, or `null`), so a real dependency CVE
  points straight at the row that owns it ([R-020](../docs/risk-register.md)).
- **rationale** — grounded in the specific symptom (the flagged value, the file,
  the CVE), not generic security talk.

It effectively re-derives, automatically and scorably, the manual B1 triage
written up as F-029.

## Design

```
security_agent/
├── findings.py    # run the RAW scanners (no allowlist) + normalise every tool's
│                  #   output into one Finding(tool, rule_id, location, severity, …)
├── judge.py       # LLM judgement per finding: verdict + disposition + R-ID xref
├── render.py      # markdown + json
├── run.py         # CLI (local on-demand; --refresh re-runs the scanners)
├── eval.py        # golden-set scorer (deterministic, no LLM)
├── golden_set.yaml
└── reports/       # committed evidence (report.md/json, eval-report.md/json)
    └── raw/       # gitignored — cached scanner JSON (echoes SUT source)
```

Decisions worth calling out:

- **Raw scanners, not the gate's view.** The B1 gate (`scan.py`) applies the
  [SCA allowlist](../nonfunctional/security/sca_allowlist.txt) before it reports,
  so its output hides the very CVEs that need judging. The agent runs pip-audit
  **raw** (no `--ignore-vuln`) so it can re-derive the allowlist recommendation
  itself rather than trusting a human's prior decision. Detect-and-suppress is the
  gate's job; judge-what-was-suppressed is the agent's.
- **Heuristic spine, LLM judgement.** Normalising and deduping findings (the same
  CVE appears in `requirements.txt` *and* `requirements-dev.txt`) is deterministic.
  Only the verdict/disposition/R-ID needs judgement, and that is all the LLM does.
- **Closed-vocabulary R-ID.** The register is fed to the model as an enum; it
  cannot invent a risk ID, only pick a real one or `null`. Same guard as
  `triage_agent`.
- **Decision-procedure prompt.** The system prompt anchors the call in an ordered
  procedure (verdict → disposition → R-ID → rationale) with the classic
  false-positive shapes named explicitly — the lesson from F-027, where rules
  buried in prose didn't move the model.

## Quick start

Local on-demand — needs a local Ollama runtime and the SUT checked out as a
sibling (`../golf-web-app`).

```bash
uv run python -m security_agent.run --refresh        # re-scan + judge
uv run python -m security_agent.run                  # judge cached findings
uv run python -m security_agent.run --no-llm         # normalise only, no judgement
uv run python -m security_agent.eval                 # score against the golden set
uv run python -m security_agent.eval --refresh       # re-run the agent, then score
```

Outputs under [`reports/`](reports/): `report.md` / `report.json` (the judged
findings) and `eval-report.md` / `eval-report.json` (the golden-set score).

## Evidence: this repo's real B1 findings

The committed [`reports/report.md`](reports/report.md) is the agent run against
`golf-web-app`'s live scanner output. Seven findings, and the agent reproduced
the hand triage exactly:

| Finding | Kind | Verdict | Disposition | Risk | Why |
|---|---|---|---|---|---|
| `B105` auth.py:16 `'api-v1-token'` | SAST | false_positive | accept | — | the `TOKEN_SALT` salt string, not a credential |
| `B105` views.py:57 `'Bearer'` | SAST | false_positive | accept | — | the HTTP auth-scheme keyword, not a secret |
| `B104` run.py:7 bind `0.0.0.0` | SAST | expected_by_design | accept | — | binding all interfaces is required inside the container |
| `CVE-2025-47278` flask 3.1.0 | SCA | **true_positive** | allowlist | **R-020** | real fallback-key CVE; fix is a deferred bump to 3.1.1 |
| `CVE-2026-27205` flask 3.1.0 | SCA | **true_positive** | allowlist | **R-020** | real CVE; fix 3.1.3 |
| `CVE-2026-28684` python-dotenv 1.0.1 | SCA | **true_positive** | allowlist | **R-020** | real arbitrary-file-overwrite CVE; fix 1.2.2 |
| `CVE-2025-71176` pytest 8.3.4 | SCA | **true_positive** | allowlist | **R-020** | real CVE in the SUT's dev deps; fix 9.0.3 |

Every SAST finding is scanner noise and the agent said so with the right reason;
every SCA finding is a genuine CVE that the agent correctly routed to *accept-and-track*
against the dependency-CVE register row.

## Evaluation tier — golden-set baseline

The agent is scored against a labelled golden set on every change.
[`golden_set.yaml`](golden_set.yaml) records the (verdict, disposition, R-ID) a
reviewer assigns per finding — this set *is* the F-029 triage made
machine-checkable. The scorer (`security_agent.eval`) reads the cached
`reports/report.json` and reports per-axis accuracy plus a combined
all-three-right score; deterministic, no LLM in the scoring path.

### Baseline (v1, seven findings)

Reported in [`reports/eval-report.md`](reports/eval-report.md):

| Metric | Value |
|---|---|
| Cases | 7 |
| Findings matched in report | 7 / 7 |
| **Verdict accuracy** | **1.000** (7/7) |
| **Disposition accuracy** | **1.000** (7/7) |
| **R-ID accuracy** | **1.000** (7/7) |
| **Combined (all three right)** | **1.000** (7/7) |

The baseline is the deliverable: any future regression below 7/7 is immediately
visible, and any change (prompt, model, schema) is measurable against it.

### Honest caveats on the baseline

A 100% result with seven findings needs context:

- **The dataset is small and clean-cut.** Three obvious SAST false positives and
  four obvious dependency CVEs. There is no genuinely ambiguous case (a
  borderline true-positive, a CVE that should be *remediated now* rather than
  allowlisted) to stress the judgement — the SUT simply doesn't have one yet.
- **SCA verdicts are nearly free.** "A named CVE in a pinned version is real" is a
  low bar; the agent's value on SCA is the *disposition + R-ID*, not the verdict.
  The harder, more valuable calls are the SAST false-positives, and there are
  only three.
- **One SUT, one register.** All findings come from `golf-web-app` and map to one
  register row (R-020). A second owning row, or cross-repo findings, would make
  the R-ID axis non-trivial.

These limit how strong the *single number* is — but the **process** stands: a
labelled set in the repo, a deterministic scorer in the repo, a numeric baseline
future changes are measured against.

## Known limits / roadmap

- [x] v1: SAST (bandit) + SCA (pip-audit) findings, verdict + disposition + R-ID,
      7/7 golden-set baseline.
- [ ] **Secrets + SARIF tools.** gitleaks (secrets), CodeQL and ZAP (SARIF) are
      out of v1 — gitleaks adds little FP-triage signal here (clean), and CodeQL/ZAP
      output is a CI artifact, not produced locally. Folding them in needs a SARIF
      normaliser in `findings.py`.
- [ ] **Write-back.** The agent recommends `allowlist` + R-020 but does not edit
      `sca_allowlist.txt` or the register; a human still applies it. A propose-diff
      step (mirroring `risk_agent`'s plan output) is the natural next move.
- [ ] **Harder cases.** The eval only bites once the SUT grows a finding that
      should be *remediated now* or a genuinely ambiguous SAST hit.
