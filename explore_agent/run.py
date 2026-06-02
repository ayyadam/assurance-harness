"""CLI for the exploratory testing agent (phase 12 v1 v1).

Usage:
  uv run python -m explore_agent.run
  uv run python -m explore_agent.run --base-url http://localhost:5000
  uv run python -m explore_agent.run --no-llm   # deterministic happy-path only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

from explore_agent.judge import DEFAULT_MODEL, judge
from explore_agent.probe import (
    Probe,
    Variant,
    gather_seed_context,
    propose_variants,
    send_probe,
)
from explore_agent.render import Result, render_markdown, to_json
from explore_agent.spec import fetch_spec, parse_endpoints

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_BASE_URL = "http://localhost:5000"
DEFAULT_USERNAME = "john.smith"
DEFAULT_PASSWORD = "Password1"  # noqa: S105 — seed fixture credential, not a real secret


def _login(base_url: str, username: str, password: str) -> requests.Session:
    """Get a bearer token from the seeded member account and attach it to a session."""
    resp = requests.post(
        base_url.rstrip("/") + "/api/v1/auth/token",
        json={"username": username, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    return session


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Exploratory testing agent — API-level.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=None, help="Ollama host (default: env or localhost)")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM payload generation and judgement; send a deterministic empty-body "
        "probe per endpoint and report status only.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print markdown to stdout but do not save report files.",
    )
    args = parser.parse_args(argv)

    print(f"fetching OpenAPI spec from {args.base_url}...", file=sys.stderr)
    spec = fetch_spec(args.base_url)
    endpoints = parse_endpoints(spec)
    print(f"discovered {len(endpoints)} endpoint(s) to probe", file=sys.stderr)

    print("logging in as seed member...", file=sys.stderr)
    session = _login(args.base_url, args.username, args.password)
    seed_context = gather_seed_context(session, args.base_url)
    print(f"seed context: {seed_context or '(none)'}", file=sys.stderr)

    results: list[Result] = []
    for i, ep in enumerate(endpoints, start=1):
        print(f"  endpoint {i}/{len(endpoints)}: {ep.signature}", file=sys.stderr)
        if args.no_llm:
            variants = [Variant(label="happy", body=None, rationale="empty-body probe (--no-llm)")]
        else:
            try:
                variants = propose_variants(ep, model=args.model, host=args.host)
            except Exception as exc:
                print(f"    variant proposal failed: {exc}", file=sys.stderr)
                continue
        for v in variants:
            probe = send_probe(session, args.base_url, ep, v, seed_context)
            if probe is None:
                print(f"    skipped (unresolved path params): {v.label}", file=sys.stderr)
                continue
            finding = _finding_for(probe, args.model, args.host, args.no_llm)
            results.append(Result(probe=probe, finding=finding))

    md = render_markdown(results, base_url=args.base_url, model=args.model)
    print(md)

    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "report.md").write_text(md, encoding="utf-8")
        (REPORTS_DIR / "report.json").write_text(to_json(results), encoding="utf-8")
        print(f"\nWrote: {REPORTS_DIR / 'report.md'}", file=sys.stderr)
        print(f"       {REPORTS_DIR / 'report.json'}", file=sys.stderr)
    return 0


def _finding_for(probe: Probe, model: str, host: str | None, no_llm: bool):
    from explore_agent.judge import Finding

    if no_llm:
        # Deterministic fallback: 5xx → unexpected_5xx, everything else → expected.
        if probe.status >= 500:
            return Finding(category="unexpected_5xx", severity="med", rationale="5xx without LLM judgement")
        return Finding(category="expected", severity="low", rationale="status < 500 (no-llm mode)")
    return judge(probe, model=model, host=host)


if __name__ == "__main__":
    sys.exit(main())
