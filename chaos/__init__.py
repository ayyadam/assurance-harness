"""Resilience / chaos testing of the golf-web-app compose stack (B4).

Fault-injects the running stack and asserts *graceful degradation* + *automatic
recovery* — the one risk surface a green functional/E2E/load suite never touches.

Scope is deliberately bounded: one representative fault per distinct failure
*axis* the architecture can exhibit (dependency-gone, app-process-death; grey
dependency-latency added in v2), each written as a steady-state → fault →
recovery hypothesis with a pre-stated correct behaviour. See README.md.
"""
