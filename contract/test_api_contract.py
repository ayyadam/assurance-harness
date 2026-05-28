"""Property-based contract tests for the golf-web-app JSON API.

Schemathesis reads the live OpenAPI spec, generates requests that conform to
it, sends them to the running SUT, and validates that every response matches
the declared status codes and schemas. This catches drift between what the
API *says* it does (the spec) and what it *actually* does.

See contract/conftest.py for how to run these (a running SUT is required).
"""

import schemathesis

schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
def test_api_conforms_to_spec(case, auth_token):
    """Each generated operation must produce a spec-conformant response."""
    case.call_and_validate(headers={"Authorization": f"Bearer {auth_token}"})
