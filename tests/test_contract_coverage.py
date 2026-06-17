"""Gated unit tests for the app-agnostic contract coverage floor.

No SUT, no network. Deliberately uses a *fictional* "library" API (not
golf-web-app) to prove the floor reads operations and links from the spec rather
than any hardcoded SUT knowledge: spec + ndjson events in, pass/fail out.
"""

from __future__ import annotations

from contract.coverage import (
    assess_coverage,
    declared_links,
    spec_operations,
    tally_executions,
)

# A small fictional spec: list books, read one, create one — with a link from the
# list to the read operation (operationRef) and to the create (operationId).
SPEC = {
    "paths": {
        "/books": {
            "parameters": [{"name": "q", "in": "query"}],  # not an operation — must be ignored
            "get": {
                "responses": {
                    "200": {
                        "links": {
                            "ReadBook": {
                                "operationRef": "#/paths/~1books~1{book_id}/get",
                                "parameters": {"book_id": "$response.body#/0/id"},
                            },
                            "AddSimilar": {  # resolved via operationId instead of operationRef
                                "operationId": "createBook",
                            },
                        }
                    }
                }
            },
            "post": {"operationId": "createBook", "responses": {"201": {}}},
        },
        "/books/{book_id}": {
            "get": {"responses": {"200": {}, "404": {}}},
        },
    }
}


def _case(method: str, path: str):
    return {"value": {"method": method, "path": path}}


def _scenario(phase: str, label: str, cases: dict, *, executed: set | None = None):
    """Build a ScenarioFinished event. `executed` = ids that produced an
    interaction (default: all); ids not in it model skipped transitions."""
    executed = executed if executed is not None else set(cases)
    return {
        "ScenarioFinished": {
            "phase": phase,
            "status": "success",
            "recorder": {
                "label": label,
                "cases": cases,
                "interactions": {cid: {"response": {"status_code": 200}} for cid in executed},
            },
        }
    }


def test_spec_operations_lists_methods_and_ignores_non_operations():
    assert spec_operations(SPEC) == {
        "GET /books",
        "POST /books",
        "GET /books/{book_id}",
    }


def test_declared_links_resolves_operationref_and_operationid():
    links = sorted(declared_links(SPEC))
    assert ("AddSimilar", "GET /books", "POST /books") in links
    assert ("ReadBook", "GET /books", "GET /books/{book_id}") in links


def test_full_coverage_passes():
    events = [
        _scenario("Coverage", "GET /books", {"a": _case("GET", "/books")}),
        _scenario("Fuzzing", "POST /books", {"b": _case("POST", "/books")}),
        _scenario("Fuzzing", "GET /books/{book_id}", {"c": _case("GET", "/books/{book_id}")}),
        # stateful sequence reaches both link targets
        _scenario(
            "Stateful",
            "Stateful tests",
            {
                "s1": _case("GET", "/books"),
                "s2": _case("GET", "/books/{book_id}"),
                "s3": _case("POST", "/books"),
            },
        ),
    ]
    report = assess_coverage(events, SPEC)
    assert report.passed
    assert report.operation_breaches == []
    assert report.link_breaches == []


def test_operation_with_zero_cases_breaches():
    # POST /books never runs anywhere → operation breach
    events = [
        _scenario("Fuzzing", "GET /books", {"a": _case("GET", "/books")}),
        _scenario("Fuzzing", "GET /books/{book_id}", {"c": _case("GET", "/books/{book_id}")}),
        _scenario("Stateful", "Stateful tests", {"s1": _case("GET", "/books"), "s2": _case("GET", "/books/{book_id}")}),
    ]
    report = assess_coverage(events, SPEC)
    assert not report.passed
    assert [o.operation for o in report.operation_breaches] == ["POST /books"]


def test_link_target_never_traversed_in_stateful_breaches():
    # Every op runs, but GET /books/{book_id} is only hit in Fuzzing, never in a
    # stateful sequence → the ReadBook link was never traversed.
    events = [
        _scenario("Fuzzing", "GET /books", {"a": _case("GET", "/books")}),
        _scenario("Fuzzing", "POST /books", {"b": _case("POST", "/books")}),
        _scenario("Fuzzing", "GET /books/{book_id}", {"c": _case("GET", "/books/{book_id}")}),
        _scenario("Stateful", "Stateful tests", {"s1": _case("GET", "/books"), "s3": _case("POST", "/books")}),
    ]
    report = assess_coverage(events, SPEC)
    assert not report.passed
    breached = {link.name for link in report.link_breaches}
    assert breached == {"ReadBook"}


def test_skipped_transitions_and_wrong_method_probes_dont_count():
    # 's2' is a skipped transition (no interaction); a TRACE wrong-method probe is
    # not a declared operation. Neither should count as a real execution.
    events = [
        _scenario("Coverage", "GET /books", {"t": _case("TRACE", "/books"), "a": _case("GET", "/books")}),
        _scenario("Fuzzing", "POST /books", {"b": _case("POST", "/books")}),
        _scenario(
            "Stateful",
            "Stateful tests",
            {"s1": _case("GET", "/books"), "s2": _case("GET", "/books/{book_id}")},
            executed={"s1"},  # s2 abandoned — no id to chain
        ),
    ]
    total, stateful = tally_executions(events, spec_operations(SPEC))
    assert total["TRACE /books"] == 0  # wrong-method probe ignored (not a spec op)
    assert stateful["GET /books/{book_id}"] == 0  # skipped transition not counted
    # GET /books/{book_id} never really ran anywhere → operation breach
    report = assess_coverage(events, SPEC)
    assert any(o.operation == "GET /books/{book_id}" for o in report.operation_breaches)


def test_thresholds_are_respected():
    events = [
        _scenario("Fuzzing", "GET /books", {f"a{i}": _case("GET", "/books") for i in range(3)}),
        _scenario("Fuzzing", "POST /books", {f"b{i}": _case("POST", "/books") for i in range(3)}),
        _scenario("Fuzzing", "GET /books/{book_id}", {f"c{i}": _case("GET", "/books/{book_id}") for i in range(3)}),
        _scenario(
            "Stateful", "Stateful tests", {"s2": _case("GET", "/books/{book_id}"), "s3": _case("POST", "/books")}
        ),
    ]
    # 3 cases/op clears a floor of 3 but not of 5
    assert assess_coverage(events, SPEC, min_cases_per_op=3).operation_breaches == []
    assert {o.operation for o in assess_coverage(events, SPEC, min_cases_per_op=5).operation_breaches} == {
        "GET /books",
        "POST /books",
        "GET /books/{book_id}",
    }
