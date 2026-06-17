"""Contract coverage floor — an app-agnostic completeness gate layered on Schemathesis.

Schemathesis answers *"did every executed case conform to the spec?"*. It does
**not** guarantee the run actually *reached* the whole contract — a phase can pass
having skipped an operation, or never traversed a declared link (e.g. the stateful
phase skips a sequence when its source list comes back empty). This module answers
the complementary question a client really asks — *"did we exercise the whole
contract?"* — and lets the gate **fail** if not:

  - every operation the spec declares ran at least ``min_cases_per_op`` times;
  - every declared OpenAPI ``link`` was traversed at least ``min_link_traversals``
    times in the **stateful** phase (an id-parameterised link target is only
    reachable there by following the link, so its appearance is the traversal).

Both the operation set and the link set are read from the **OpenAPI spec**, and
the execution counts from the Schemathesis **ndjson** event stream — nothing here
is SUT-specific. Point it at another API and it checks that API's surface. The
functions are pure (events + spec in, report out) so they unit-test without a SUT.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

# HTTP methods that denote an operation under a spec path (everything else under a
# path item — `parameters`, `summary`, `$ref`, ... — is not an operation).
_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


@dataclass(frozen=True)
class OperationCoverage:
    operation: str  # "METHOD /path"
    executed: int
    ok: bool


@dataclass(frozen=True)
class LinkCoverage:
    name: str
    source: str  # "METHOD /path" the link is declared on
    target: str  # "METHOD /path" the link points at
    traversals: int  # stateful-phase executions of the target
    ok: bool


@dataclass(frozen=True)
class CoverageReport:
    operations: list[OperationCoverage]
    links: list[LinkCoverage]
    min_cases_per_op: int
    min_link_traversals: int

    @property
    def operation_breaches(self) -> list[OperationCoverage]:
        return [o for o in self.operations if not o.ok]

    @property
    def link_breaches(self) -> list[LinkCoverage]:
        return [link for link in self.links if not link.ok]

    @property
    def passed(self) -> bool:
        return not self.operation_breaches and not self.link_breaches


def spec_operations(spec: dict) -> set[str]:
    """Every operation the spec declares, as ``"METHOD /path"`` strings."""
    ops: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(op, dict):
                ops.add(f"{method.upper()} {path}")
    return ops


def _resolve_operation_ref(ref: str) -> str | None:
    """Resolve a local ``operationRef`` JSON pointer to ``"METHOD /path"``.

    e.g. ``#/paths/~1api~1v1~1tee-times~1{tee_time_id}/get`` -> ``GET /api/v1/tee-times/{tee_time_id}``.
    """
    prefix = "#/paths/"
    if not ref.startswith(prefix):
        return None
    pointer, _, method = ref[len(prefix) :].rpartition("/")
    if method.lower() not in _HTTP_METHODS or not pointer:
        return None
    path = pointer.replace("~1", "/").replace("~0", "~")
    return f"{method.upper()} {path}"


def _resolve_operation_id(operation_id: str, spec: dict) -> str | None:
    """Resolve an ``operationId`` to ``"METHOD /path"`` by scanning the spec."""
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return f"{method.upper()} {path}"
    return None


def declared_links(spec: dict) -> list[tuple[str, str, str]]:
    """Every declared OpenAPI link as ``(name, source_op, target_op)``.

    Supports both ``operationRef`` (a JSON pointer) and ``operationId`` targets.
    Links whose target cannot be resolved are skipped (nothing to assert against).
    """
    out: list[tuple[str, str, str]] = []
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            source = f"{method.upper()} {path}"
            for response in (op.get("responses") or {}).values():
                if not isinstance(response, dict):
                    continue
                for name, link in (response.get("links") or {}).items():
                    if not isinstance(link, dict):
                        continue
                    target = None
                    if link.get("operationRef"):
                        target = _resolve_operation_ref(str(link["operationRef"]))
                    elif link.get("operationId"):
                        target = _resolve_operation_id(str(link["operationId"]), spec)
                    if target:
                        out.append((name, source, target))
    return out


def _operation_of_case(case: dict) -> str | None:
    value = case.get("value") or {}
    method = (value.get("method") or "").upper()
    path = value.get("path") or ""
    return f"{method} {path}" if method and path else None


def tally_executions(events: list[dict], spec_ops: set[str]) -> tuple[Counter, Counter]:
    """Count executed cases per operation: (total across phases, stateful only).

    A case counts as *executed* only if it produced an interaction (a real
    request/response) — abandoned stateful link transitions never built a request
    and so never appear here. Cases whose ``METHOD /path`` is not a declared
    operation (e.g. coverage's wrong-method probes) are ignored.
    """
    total: Counter = Counter()
    stateful: Counter = Counter()
    for event in events:
        scenario = event.get("ScenarioFinished")
        if not scenario:
            continue
        phase = scenario.get("phase")
        recorder = scenario.get("recorder") or {}
        interactions = set((recorder.get("interactions") or {}).keys())
        for case_id, case in (recorder.get("cases") or {}).items():
            if case_id not in interactions:
                continue
            op = _operation_of_case(case)
            if op in spec_ops:
                total[op] += 1
                if phase == "Stateful":
                    stateful[op] += 1
    return total, stateful


def assess_coverage(
    events: list[dict],
    spec: dict,
    *,
    min_cases_per_op: int = 1,
    min_link_traversals: int = 1,
) -> CoverageReport:
    """Assess the floor: pure function over the ndjson events and the spec."""
    ops = spec_operations(spec)
    total, stateful = tally_executions(events, ops)
    operations = [OperationCoverage(op, total.get(op, 0), total.get(op, 0) >= min_cases_per_op) for op in sorted(ops)]
    links = [
        LinkCoverage(name, source, target, stateful.get(target, 0), stateful.get(target, 0) >= min_link_traversals)
        for name, source, target in declared_links(spec)
    ]
    return CoverageReport(operations, links, min_cases_per_op, min_link_traversals)


def parse_ndjson(path) -> list[dict]:
    """Read a Schemathesis ndjson report into a list of event dicts."""
    events: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def format_report(report: CoverageReport) -> str:
    """Human-readable coverage summary for the console + client report."""
    lines = ["## Coverage floor (app-agnostic completeness gate)\n"]
    lines.append(
        f"Thresholds: >= {report.min_cases_per_op} case(s)/operation, "
        f">= {report.min_link_traversals} traversal(s)/declared link\n"
    )
    lines.append(f"Operations ({len(report.operations)} declared):")
    for o in report.operations:
        mark = "ok" if o.ok else "FAIL"
        lines.append(f"  [{mark}] {o.operation} — {o.executed} case(s)")
    if report.links:
        lines.append(f"\nDeclared links ({len(report.links)}):")
        for link in report.links:
            mark = "ok" if link.ok else "FAIL"
            lines.append(f"  [{mark}] {link.name}: {link.source} -> {link.target} — {link.traversals} traversal(s)")
    else:
        lines.append("\nDeclared links: none in the spec.")
    verdict = "PASS" if report.passed else "FAIL"
    lines.append(f"\nCoverage floor: {verdict}")
    return "\n".join(lines)
