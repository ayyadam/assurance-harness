"""CLI for the AI evaluation harness.

Two modes:
  * single  — score the model the SUT is currently running (SUT must be up):
        uv run python -m ai_evaluation.run --model-label qwen3:8b-fp16
  * compare — orchestrate: for each model, reconfigure the SUT then score it:
        uv run python -m ai_evaluation.run --models qwen3:8b-fp16,qwen3.6:27b-q4_K_M

The report (markdown + JSON) is written under ai_evaluation/reports/ as the
committed evidence artifact. This is a local, on-demand tool — it needs a real
Ollama-backed SUT and is never run in hosted CI (which uses the stub).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import requests

from .evaluator import DEFAULT_BASE_URL, CaseResult, SUTClient, evaluate_model, load_cases, score_case

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
RAW_PATH = REPORTS_DIR / "raw_responses.json"
DEFAULT_SUT_DIR = Path(__file__).resolve().parents[2] / "golf-web-app"

OVERRIDE_TEMPLATE = """\
# Local-only eval override (gitignored), written by ai_evaluation/run.py.
services:
  web:
    environment:
      - BOOKING_ASSISTANT_PROVIDER=ollama
      - BOOKING_ASSISTANT_MODEL={model}
      - OLLAMA_HOST=http://host.docker.internal:11434
"""


# ── SUT orchestration (compare mode) ──────────────────────────────────────


def wait_for_health(base_url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(base_url + "/", timeout=5).status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"SUT at {base_url} did not become healthy within {timeout:.0f}s")


def configure_sut(sut_dir: Path, model: str, base_url: str) -> None:
    """Point the SUT at ``model`` via the gitignored override and recreate it."""
    (sut_dir / "docker-compose.override.yml").write_text(OVERRIDE_TEMPLATE.format(model=model), encoding="utf-8")
    subprocess.run(["docker", "compose", "up", "-d"], cwd=sut_dir, check=True, capture_output=True, text=True)
    wait_for_health(base_url)


# ── metrics ────────────────────────────────────────────────────────────────


def _accuracy_cases(results: list[CaseResult]) -> list[CaseResult]:
    return [r for r in results if r.kind == "accuracy" and r.error is None]


def field_accuracy(results: list[CaseResult]) -> tuple[int, int]:
    correct = total = 0
    for r in _accuracy_cases(results):
        c, t = r.field_score
        correct += c
        total += t
    return correct, total


def cases_passed(results: list[CaseResult]) -> tuple[int, int]:
    acc = _accuracy_cases(results)
    return sum(r.passed for r in acc), len(acc)


def safety_passed(results: list[CaseResult]) -> tuple[int, int]:
    safety = [r for r in results if r.kind == "safety"]
    return sum(bool(r.safe) for r in safety), len(safety)


def latency_stats(results: list[CaseResult]) -> dict[str, float]:
    lat = [r.latency for r in _accuracy_cases(results)]
    if not lat:
        return {"p50": 0.0, "mean": 0.0, "max": 0.0}
    return {"p50": statistics.median(lat), "mean": statistics.fmean(lat), "max": max(lat)}


def category_accuracy(results: list[CaseResult]) -> dict[str, tuple[int, int]]:
    by_cat: dict[str, list[int]] = {}
    for r in _accuracy_cases(results):
        c, t = r.field_score
        for cat in r.category:
            agg = by_cat.setdefault(cat, [0, 0])
            agg[0] += c
            agg[1] += t
    return {cat: (v[0], v[1]) for cat, v in by_cat.items()}


def _pct(correct: int, total: int) -> str:
    return f"{correct / total * 100:.0f}%" if total else "—"


# ── reporting ──────────────────────────────────────────────────────────────


def render_markdown(meta: dict, per_model: dict[str, list[CaseResult]]) -> str:
    models = list(per_model)
    lines: list[str] = []
    lines.append("# AI evaluation report — booking assistant")
    lines.append("")
    lines.append(f"- **Run:** {meta['run_at']}  (today = {meta['today']})")
    lines.append(f"- **SUT:** {meta['base_url']} (black-box via `/api/v1/booking-assistant`)")
    lines.append(f"- **Golden set:** {meta['cases']} cases")
    lines.append(
        "- **Grading:** deterministic field scoring; safety cases graded on no-5xx + "
        "in-schema + clamped. Latency is warm (model pre-loaded before timing)."
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Model | Field accuracy | Cases fully correct | Safety | Latency p50 / mean / max (s) |")
    lines.append("|---|---|---|---|---|")
    for m in models:
        res = per_model[m]
        fc, ft = field_accuracy(res)
        cp, ct = cases_passed(res)
        sp, st = safety_passed(res)
        lat = latency_stats(res)
        lines.append(
            f"| `{m}` | {_pct(fc, ft)} ({fc}/{ft}) | {cp}/{ct} | {sp}/{st} | "
            f"{lat['p50']:.1f} / {lat['mean']:.1f} / {lat['max']:.1f} |"
        )
    lines.append("")

    cats = sorted({c for res in per_model.values() for r in _accuracy_cases(res) for c in r.category})
    lines.append("## Field accuracy by category")
    lines.append("")
    lines.append("| Category | " + " | ".join(f"`{m}`" for m in models) + " |")
    lines.append("|---" * (len(models) + 1) + "|")
    for cat in cats:
        cells = []
        for m in models:
            ca = category_accuracy(per_model[m]).get(cat, (0, 0))
            cells.append(_pct(ca[0], ca[1]))
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Failures")
    lines.append("")
    for m in models:
        res = per_model[m]
        failed = [r for r in res if not r.passed]
        lines.append(f"### `{m}` — {len(failed)} failing case(s)")
        if not failed:
            lines.append("")
            lines.append("_None._")
            lines.append("")
            continue
        for r in failed:
            if r.kind == "safety":
                lines.append(
                    f"- **{r.case_id}** (safety) — status {r.status_code}, "
                    f"{'error: ' + r.error if r.error else 'not deemed safe'}"
                )
                continue
            diffs = [f"{f.name}: got `{f.got}` want `{f.expected}`" for f in r.fields if not f.ok]
            detail = "; ".join(diffs) if diffs else (r.error or "unknown")
            lines.append(f"- **{r.case_id}** — {detail}")
        lines.append("")

    return "\n".join(lines)


def write_reports(meta: dict, per_model: dict[str, list[CaseResult]]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(exist_ok=True)
    md_path = REPORTS_DIR / "report.md"
    json_path = REPORTS_DIR / "report.json"

    md_path.write_text(render_markdown(meta, per_model), encoding="utf-8")

    payload = {
        "meta": meta,
        "results": {m: [asdict(r) for r in res] for m, res in per_model.items()},
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


def write_raw(meta: dict, per_model: dict[str, list[CaseResult]]) -> None:
    """Cache raw model responses so the golden set can be refined and re-scored
    without re-running the models (the expensive part)."""
    REPORTS_DIR.mkdir(exist_ok=True)
    payload = {
        "meta": meta,
        "models": {
            m: [
                {
                    "case_id": r.case_id,
                    "status": r.status_code,
                    "latency": r.latency,
                    "error": r.error,
                    "intent": r.raw_intent,
                }
                for r in res
            ]
            for m, res in per_model.items()
        },
    }
    RAW_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def score_from_raw(cases: list[dict]) -> tuple[dict, dict[str, list[CaseResult]]]:
    """Re-score cached raw responses against the current golden set (no SUT)."""
    data = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    today = date.fromisoformat(meta["today"])  # score against the capture date
    by_id = {c["id"]: c for c in cases}
    per_model: dict[str, list[CaseResult]] = {}
    for model, records in data["models"].items():
        per_model[model] = [
            score_case(by_id[r["case_id"]], r["status"], r["intent"], r["latency"], today, r["error"])
            for r in records
            if r["case_id"] in by_id
        ]
    return meta, per_model


# ── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AI evaluation harness for the booking assistant.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--models", help="comma-separated models to compare (orchestrates the SUT)")
    parser.add_argument("--model-label", help="label for a single run against the already-running SUT")
    parser.add_argument("--sut-dir", type=Path, default=DEFAULT_SUT_DIR)
    parser.add_argument(
        "--restore-model", default="qwen3:8b-fp16", help="model to leave the SUT on after a compare run"
    )
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument(
        "--score-only",
        action="store_true",
        help="re-score cached raw responses against the current golden set (no SUT)",
    )
    args = parser.parse_args(argv)

    cases = load_cases()
    today = date.today()
    per_model: dict[str, list[CaseResult]] = {}

    if args.score_only:
        meta, per_model = score_from_raw(cases)
        meta["rescored_at"] = datetime.now().isoformat(timespec="seconds")
        meta["cases"] = len(cases)
        md_path, json_path = write_reports(meta, per_model)
        print(f"[eval] re-scored from cache -> {md_path}")
        return

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        for model in models:
            print(f"[eval] configuring SUT -> {model}")
            configure_sut(args.sut_dir, model, args.base_url)
            print(f"[eval] scoring {model} ...")
            per_model[model] = evaluate_model(SUTClient(args.base_url), cases, today, warmup=not args.no_warmup)
        print(f"[eval] restoring SUT -> {args.restore_model}")
        configure_sut(args.sut_dir, args.restore_model, args.base_url)
    else:
        label = args.model_label or "current"
        per_model[label] = evaluate_model(SUTClient(args.base_url), cases, today, warmup=not args.no_warmup)

    meta = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "base_url": args.base_url,
        "cases": len(cases),
    }
    write_raw(meta, per_model)
    md_path, json_path = write_reports(meta, per_model)
    print(f"[eval] wrote {md_path}")
    print(f"[eval] wrote {json_path}")


if __name__ == "__main__":
    main()
