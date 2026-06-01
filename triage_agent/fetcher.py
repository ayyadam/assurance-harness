"""Fetch failed CI runs and their logs via the ``gh`` CLI.

Logs are large and slow to download. We cache each run's failed-log dump under
``triage_agent/reports/raw/<run_id>.log`` (gitignored), so repeat invocations
during golden-set iteration are free.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_RAW_DIR = Path(__file__).resolve().parent / "reports" / "raw"


@dataclass
class Run:
    id: int
    number: int
    workflow_name: str
    event: str
    branch: str
    sha: str
    title: str
    conclusion: str
    created_at: datetime
    url: str

    @property
    def pr_number(self) -> int | None:
        """Extract trailing ``(#NN)`` from the run title if present."""
        title = self.title
        if title.endswith(")") and "#" in title:
            try:
                return int(title.rsplit("#", 1)[1].rstrip(")"))
            except ValueError:
                return None
        return None


def list_failed_runs(repo: str, since_days: int = 30, limit: int = 100) -> list[Run]:
    """List recent failed runs in ``repo``, newest first."""
    proc = _gh(
        [
            "run",
            "list",
            "--repo",
            repo,
            "--limit",
            str(limit),
            "--json",
            "databaseId,number,workflowName,event,headBranch,headSha,displayTitle,conclusion,createdAt,url",
        ]
    )
    cutoff = datetime.now(UTC) - timedelta(days=since_days)
    runs: list[Run] = []
    for r in json.loads(proc):
        if r["conclusion"] != "failure":
            continue
        created = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        if created < cutoff:
            continue
        runs.append(
            Run(
                id=r["databaseId"],
                number=r["number"],
                workflow_name=r["workflowName"],
                event=r["event"],
                branch=r["headBranch"],
                sha=r["headSha"],
                title=r["displayTitle"],
                conclusion=r["conclusion"],
                created_at=created,
                url=r["url"],
            )
        )
    return runs


def fetch_failed_log(run_id: int, repo: str, raw_dir: Path = DEFAULT_RAW_DIR) -> str:
    """Fetch the failed-job log for a run (or read from cache)."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{run_id}.log"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")
    log = _gh(["run", "view", str(run_id), "--repo", repo, "--log-failed"])
    cache_path.write_text(log, encoding="utf-8")
    return log


def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
