"""Parse pytest / Playwright failure signals out of a GitHub Actions log dump.

The ``gh run view --log-failed`` output is tab-separated:
    <JOB NAME>\\t<STEP NAME>\\t<TIMESTAMP> <message>

We extract one ``Failure`` per pytest FAILED summary line. The summary
line carries the test id, the error class, and a short error excerpt — which
is everything the clustering layer needs without parsing the verbose traceback
section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Pytest summary line, e.g.
#   FAILED functional/test_foo.py::test_bar[chromium] - AssertionError: Page URL...
_FAILED_LINE = re.compile(
    r"FAILED\s+([^:\s]+\.py)::([^\[\s]+)(\[[^\]]*\])?\s+-\s+([\w\.]+(?:Error|Exception)):\s*(.*?)\s*$"
)

# Standalone error class+message line in the FAILURES section, e.g.
#   E   playwright._impl._errors.TimeoutError: Timeout 30000ms exceeded.
_E_LINE = re.compile(r"^E\s+([\w\.]+(?:Error|Exception)):\s*(.*?)\s*$")

# GHA log prefix: tab-separated job-name, step-name, then a leading timestamp
_GHA_PREFIX = re.compile(r"^(?P<job>[^\t]*)\t(?P<step>[^\t]*)\t(?P<rest>.*)$")
_TIMESTAMP = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s*")


@dataclass(frozen=True)
class Failure:
    kind: str  # "pytest" | "step"
    job_name: str
    test_path: str  # e.g. "functional/test_booking_assistant.py" — empty for step failures
    test_name: str  # e.g. test name OR "<job>::<step>" for step failures
    test_params: str  # e.g. "[chromium]" or ""
    error_class: str  # e.g. "AssertionError" or "<step-failure>"
    error_message: str  # short excerpt

    @property
    def signature(self) -> tuple[str, str, str]:
        """Heuristic cluster key — failures with the same signature are grouped."""
        return (self.test_path or "<step>", self.test_name, self.error_class)


def parse_log(log: str) -> list[Failure]:
    """Extract Failure records from a GHA log dump.

    First pass: pytest FAILED summary lines (the canonical case). Second pass:
    if no pytest failures were found, fall back to GHA step-level failures
    flagged by ``##[error]Process completed with exit code N``. The two layers
    cover the two failure shapes the harness produces — test assertions and
    tool-driven gates (ruff, k6, docker compose).
    """
    failures: list[Failure] = []
    seen: set[tuple[str, str, str, str]] = set()

    for raw_line in log.splitlines():
        job, body = _strip_prefix(raw_line)
        m = _FAILED_LINE.search(body)
        if not m:
            continue
        path, test_name, params, error_class, error_msg = m.groups()
        key = (path, test_name, params or "", error_class)
        if key in seen:
            continue
        seen.add(key)
        failures.append(
            Failure(
                kind="pytest",
                job_name=job,
                test_path=path,
                test_name=test_name,
                test_params=params or "",
                error_class=error_class,
                error_message=_clip(error_msg),
            )
        )

    if failures:
        return failures
    return _parse_step_failures(log)


def _parse_step_failures(log: str) -> list[Failure]:
    """Fall back to GHA step-level failures when no pytest failures are present.

    A step failure is signalled by ``##[error]Process completed with exit code N``.
    The most useful context is the previous output line from the same step
    (e.g. ruff's ``Would reformat: X``, k6's threshold breach line).
    """
    failures: list[Failure] = []
    seen: set[tuple[str, str]] = set()
    last_meaningful: dict[tuple[str, str], str] = {}  # (job, step) -> last non-trivial line

    for raw_line in log.splitlines():
        job, body = _strip_prefix(raw_line)
        step = _step_from_line(raw_line)
        if "##[error]Process completed with exit code" in body:
            key = (job, step)
            if key in seen:
                continue
            seen.add(key)
            excerpt = last_meaningful.get(key, body.strip())
            failures.append(
                Failure(
                    kind="step",
                    job_name=job,
                    test_path="",
                    test_name=f"{job}::{step}" if step else job,
                    test_params="",
                    error_class="<step-failure>",
                    error_message=_clip(excerpt),
                )
            )
            continue
        stripped = body.strip()
        if not stripped or stripped.startswith("##["):
            continue
        last_meaningful[(job, step)] = stripped

    return failures


def _step_from_line(line: str) -> str:
    parts = line.split("\t", 2)
    return parts[1] if len(parts) >= 3 else ""


def _strip_prefix(line: str) -> tuple[str, str]:
    """Return (job_name, message-with-no-timestamp) for a GHA log line.

    Falls back to ("", line) for lines that don't match the GHA shape.
    """
    m = _GHA_PREFIX.match(line)
    if not m:
        return "", line
    rest = _TIMESTAMP.sub("", m.group("rest"))
    return m.group("job"), rest


def _clip(text: str, max_len: int = 200) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"
