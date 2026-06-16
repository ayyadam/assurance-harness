"""Contract gate + evidence run — Schemathesis CLI, one job that gates *and* reports.

This is the contract pillar's single entry point: it runs the Schemathesis **CLI**
against the live SUT and produces a client-worthy report — a per-operation summary
plus **JUnit XML** and a **VCR cassette** (every request and response recorded) —
*and* gates the build on the result. It replaces the old split of a thin pytest
wrapper (the gate) beside an advisory CLI run (the report): the CLI now does both,
so "what did we actually test?" and "did it pass?" come from the same run.

Three phases run by default:
  - **coverage** — deterministic boundary testing: one targeted case per schema
    facet (each enum value, numeric boundaries, missing-required, wrong type).
  - **fuzzing** — every operation is fuzzed against its declared schema; the
    contract hook ([contract/hooks.py]) injects a real bookable id so the
    parameterised ops hit their success paths deterministically.
  - **stateful** — Schemathesis follows the OpenAPI ``links`` (golf-web-app's
    ``GET /tee-times`` → ``GetTeeTimeById`` / ``BookTeeTime``) to test operation
    *sequences*, not just operations in isolation. Sequences whose source list
    comes back empty (Schemathesis fuzzes the ``date`` filter with implausible
    dates) are *skipped*, not failed — there is simply no id to chain.

Profile-driven: the OpenAPI URL and auth recipe come from the active SUT profile
([core/profile.py]). Gating by default (exit code mirrors Schemathesis); pass
``--advisory`` for an ad-hoc local run that always exits 0.

    uv run python -m contract.evidence                       # gate (CI)
    uv run python -m contract.evidence --advisory            # report only
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

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_CONFIG_PATH = REPO_ROOT / "schemathesis.toml"


def build_command(
    openapi_url: str,
    report_dir: Path,
    *,
    max_examples: int,
    seed: int,
    phases: str,
    token: str | None = None,
    config_path: Path | None = None,
) -> list[str]:
    """Construct the Schemathesis CLI invocation (pure — unit-tested).

    ``--config-file`` is placed before the ``run`` subcommand (it is a top-level
    option), so the same ``schemathesis.toml`` the suite relies on is loaded
    explicitly regardless of the working directory.
    """
    cmd = ["schemathesis"]
    if config_path is not None:
        cmd += ["--config-file", str(config_path)]
    cmd += [
        "run",
        openapi_url,
        "-n",
        str(max_examples),
        "--seed",
        str(seed),
        "--phases",
        phases,
        # Hypothesis health checks (filter_too_much / data_too_large / too_slow /
        # large_base_example) flag test-data *generation* inefficiency, not API
        # *contract* conformance. On a gate they are noise: in a fast environment
        # they can trip and mark an operation "failed" with zero failing cases —
        # observed in CI as a phantom "Fuzzing: 3 failed" while case totals,
        # JUnit, and "No issues found" all reported clean. Suppress them so the
        # gate fails only on genuine contract violations (schema mismatch,
        # undocumented status, server error), deterministically across machines.
        "--suppress-health-check",
        "all",
        "--report",
        "junit,vcr,ndjson",
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
        print(f"[contract] could not fetch auth token ({exc}); running unauthenticated")
        return None


def main(argv: list[str] | None = None) -> int:
    try:  # make the parent's own output UTF-8-safe (Schemathesis prints box-drawing chars)
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - reconfigure unavailable on some streams
        pass

    parser = argparse.ArgumentParser(description="Schemathesis contract gate + evidence run.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--max-examples", type=int, default=20, help="generated cases per operation")
    parser.add_argument("--seed", type=int, default=1234, help="reproducible generation seed")
    parser.add_argument(
        "--phases",
        default="coverage,fuzzing,stateful",
        help="comma-separated Schemathesis phases (default: coverage,fuzzing,stateful)",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="report only — always exit 0 (default: gate on the Schemathesis result)",
    )
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
        config_path=DEFAULT_CONFIG_PATH,
    )
    # Force UTF-8 in the child so its rich output encodes cleanly on every OS, and
    # load the contract hooks (real tee_time_id injection) so the fuzzing phase's
    # parameterised ops hit their success paths deterministically.
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "SCHEMATHESIS_HOOKS": "contract.hooks",
        "PYTHONPATH": str(REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    print(f"[contract] schemathesis run {profile.openapi_url} (n={args.max_examples}, phases={args.phases})")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)

    output = (proc.stdout or "") + (proc.stderr or "")
    summary_path = report_dir / "contract-summary.txt"
    summary_path.write_text(output, encoding="utf-8")
    print(output)
    print(f"[contract] reports written to {report_dir} (summary, JUnit, VCR cassette)")

    if args.advisory:
        print(f"[contract] schemathesis exit={proc.returncode} (advisory — does not gate)")
        return 0
    print(f"[contract] schemathesis exit={proc.returncode} (gating)")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
