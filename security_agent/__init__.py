"""Security agent — the agentic-layer interpreter over B1's security findings.

Deterministic scanners (``nonfunctional/security/``) DETECT; this agent JUDGES:
true-positive vs scanner noise, a disposition (remediate / allowlist / accept),
and a risk-register cross-reference. The mirror of ``triage_agent`` (which
triages CI failures), applied to SAST + SCA findings.
"""
