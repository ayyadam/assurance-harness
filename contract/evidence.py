"""Contract *evidence* run — Schemathesis CLI for a client-worthy report.

The pytest contract job is the *gate* (pass/fail). This is the complement: it
runs the Schemathesis **CLI** to produce a detailed, hand-over-able report —
a per-operation summary plus **JUnit XML** and a **VCR cassette** (every request
and response recorded) — answering "what did we actually test?" in a way a client
will accept.

Profile-driven: the OpenAPI URL and auth recipe come from the active SUT profile
([core/profile.py]). **Advisory by design** — this never gates (always exits 0);
the pytest job remains the gate until the coverage gap (skipped operations) is
closed and the CLI is promoted to the gate.

    uv run python -m contract.evidence
    uv run python -m contract.evidence --report-dir reports --max-examples 30
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests

from core.profile import Profile, load_profile

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"


def build_command(
    openapi_url: str,
    report_dir: Path,
    *,
    max_examples: int,
    seed: int,
    phases: str,
    token: str | None = None,
) -> list[str]:
    """Construct the Schemathesis CLI invocation (pure — unit-tested)."""
    cmd = [
        "schemathesis",
        "run",
        openapi_url,
        "-n",
        str(max_examples),
        "--seed",
        str(seed),
        "--phases",
        phases,
        "--report",
        "junit,vcr",
        "--report-dir",
        str(report_dir),
    ]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    return cmd


def fetch_token(profile: Profile) -> str | None:
    """Best-effort bearer token; None (with a note) if auth is unavailable."""
    try:
        resp = requests.post(
            profile.token_url,
            json={"username": profile.auth.username, "password": profile.auth.password},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as exc:  # noqa: BLE001 - token is best-effort; public ops still get exercised
        print(f"[contract-evidence] could not fetch auth token ({exc}); running unauthenticated")
        return None


def main(argv: list[str] | None = None) -> int:
    try:  # make the parent's own output UTF-8-safe (Schemathesis prints box-drawing chars)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - reconfigure unavailable on some streams
        pass

    parser = argparse.ArgumentParser(description="Schemathesis contract evidence run (advisory, non-gating).")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--max-examples", type=int, default=20, help="generated cases per operation")
    parser.add_argument("--seed", type=int, default=1234, help="reproducible generation seed")
    parser.add_argument("--phases", default="fuzzing", help="comma-separated Schemathesis phases")
    args = parser.parse_args(argv)

    profile = load_profile()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    cmd = build_command(
        profile.openapi_url,
        report_dir,
        max_examples=args.max_examples,
        seed=args.seed,
        phases=args.phases,
        token=fetch_token(profile),
    )
    # Force UTF-8 in the child so its rich output encodes cleanly on every OS.
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    print(f"[contract-evidence] schemathesis run {profile.openapi_url} (n={args.max_examples}, phases={args.phases})")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)

    output = (proc.stdout or "") + (proc.stderr or "")
    summary_path = report_dir / "contract-summary.txt"
    summary_path.write_text(output, encoding="utf-8")
    print(output)
    print(f"[contract-evidence] schemathesis exit={proc.returncode} (advisory — does not gate)")
    print(f"[contract-evidence] reports written to {report_dir} (summary, JUnit, VCR cassette)")
    return 0  # advisory: never fail the build on the evidence run


if __name__ == "__main__":
    raise SystemExit(main())
