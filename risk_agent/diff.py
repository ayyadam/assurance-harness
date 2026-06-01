"""Fetch a PR diff (via ``gh``) or load one from a file.

Diffs can be large. We keep the full file list (cheap) but cap the body fed to
the LLM at a configurable line count, hunk-aware, so the prompt stays under a
reasonable token budget. Trimming is announced in the rendered output so the
reviewer knows the agent didn't see every line.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_DIFF_LINES = 800


@dataclass
class DiffBundle:
    repo: str | None  # "owner/name" if from a PR
    pr_number: int | None
    title: str | None
    files: list[str]  # changed file paths
    body: str  # the diff text (possibly truncated)
    truncated: bool
    total_lines: int


def fetch_pr(pr: int, repo: str, max_lines: int = DEFAULT_MAX_DIFF_LINES) -> DiffBundle:
    """Fetch a PR diff and title from GitHub via ``gh``."""
    diff = _run(["gh", "pr", "diff", str(pr), "--repo", repo])
    title = _run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", "title", "-q", ".title"]).strip()
    bundle = _bundle(diff, max_lines)
    bundle.repo = repo
    bundle.pr_number = pr
    bundle.title = title
    return bundle


def load_file(path: Path, max_lines: int = DEFAULT_MAX_DIFF_LINES) -> DiffBundle:
    """Load a unified diff from a file path."""
    return _bundle(path.read_text(encoding="utf-8"), max_lines)


# ── internals ──────────────────────────────────────────────────────────────


_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$")


def _bundle(diff: str, max_lines: int) -> DiffBundle:
    lines = diff.splitlines()
    files: list[str] = []
    for line in lines:
        m = _FILE_HEADER.match(line)
        if m:
            files.append(m.group(2))
    body, truncated = _trim(lines, max_lines)
    return DiffBundle(
        repo=None,
        pr_number=None,
        title=None,
        files=files,
        body=body,
        truncated=truncated,
        total_lines=len(lines),
    )


def _trim(lines: list[str], max_lines: int) -> tuple[str, bool]:
    """Trim diff to ``max_lines``, breaking at a file boundary if possible."""
    if len(lines) <= max_lines:
        return "\n".join(lines), False
    # Cut at the last file-header line at or before max_lines so we don't truncate mid-hunk.
    cut = max_lines
    for i in range(max_lines, 0, -1):
        if _FILE_HEADER.match(lines[i - 1]):
            cut = i - 1
            break
    return "\n".join(lines[:cut]), True


def _run(cmd: list[str]) -> str:
    """Run a subprocess and return stdout; raise on non-zero exit."""
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout
