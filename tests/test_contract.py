"""Contract tests: validate MCP tools match the OpenAPI schema.

These tests read the exported OpenAPI schema JSON (no live API needed) and
verify each MCP tool maps to a real endpoint with the correct path, method,
auth scheme, and request fields. Run with: pytest tests/test_contract.py
"""
import json
import os
from pathlib import Path

import pytest

SCHEMA_PATH = Path(__file__).parent / "openapi-schema.json"


@pytest.fixture(scope="module")
def schema():
    """Load the OpenAPI schema."""
    assert SCHEMA_PATH.exists(), (
        f"OpenAPI schema not found at {SCHEMA_PATH}. "
        "Export it with: python manage.py spectacular --format openapi-json --file openapi-schema.json"
    )
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def paths(schema):
    return schema["paths"]


@pytest.fixture(scope="module")
def components(schema):
    return schema.get("components", {})


@pytest.fixture(scope="module")
def security_schemes(components):
    return components.get("securitySchemes", {})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_operation(paths, path, method):
    """Get an operation from the schema, failing with a clear message."""
    assert path in paths, f"Path {path} not found in schema. Available: {sorted(paths.keys())}"
    methods = paths[path]
    assert method in methods, f"Method {method} not found at {path}. Available: {list(methods.keys())}"
    return methods[method]


def _has_api_key_auth(operation):
    """Check if an operation accepts API key authentication."""
    security = operation.get("security", [])
    return any("apiKeyAuth" in s for s in security)


def _get_request_schema(operation, components):
    """Resolve the request body schema, following $ref if needed."""
    body = operation.get("requestBody", {})
    content = body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    return _resolve_ref(schema, components)


def _resolve_ref(schema, components):
    """Resolve a $ref to its actual schema."""
    if "$ref" in schema:
        ref_path = schema["$ref"].replace("#/components/schemas/", "")
        return components.get("schemas", {}).get(ref_path, {})
    return schema


def _get_field_names(schema):
    """Get all field names from a schema (including from allOf)."""
    props = set(schema.get("properties", {}).keys())
    for item in schema.get("allOf", []):
        props.update(item.get("properties", {}).keys())
    return props


# ---------------------------------------------------------------------------
# Tool → Endpoint contracts
# ---------------------------------------------------------------------------

TOOL_CONTRACTS = [
    {
        "tool": "post_task",
        "path": "/api/v1/tasks/",
        "method": "post",
        "requires_api_key": True,
        "request_fields": {"title", "description", "category", "budget_amount", "deadline"},
        "tag": "agent",
    },
    {
        "tool": "check_task_status",
        "path": "/api/v1/tasks/{id}/",
        "method": "get",
        "requires_api_key": True,
        "tag": "agent",
    },
    {
        "tool": "list_my_tasks",
        "path": "/api/v1/tasks/",
        "method": "get",
        "requires_api_key": True,
        "tag": "agent",
    },
    {
        "tool": "approve_task",
        "path": "/api/v1/tasks/{id}/approve/",
        "method": "post",
        "requires_api_key": True,
        "tag": "agent",
    },
    {
        "tool": "reject_task",
        "path": "/api/v1/tasks/{id}/reject/",
        "method": "post",
        "requires_api_key": True,
        "request_fields": {"reason"},
        "tag": "agent",
    },
    {
        "tool": "cancel_task",
        "path": "/api/v1/tasks/{id}/cancel/",
        "method": "post",
        "requires_api_key": True,
        "tag": "agent",
    },
    {
        "tool": "respond_to_cancellation_approve",
        "path": "/api/v1/tasks/{id}/cancel/approve/",
        "method": "post",
        "requires_api_key": True,
    },
    {
        "tool": "respond_to_cancellation_decline",
        "path": "/api/v1/tasks/{id}/cancel/decline/",
        "method": "post",
        "requires_api_key": True,
    },
    {
        "tool": "get_templates",
        "path": "/api/v1/templates/",
        "method": "get",
        "requires_api_key": False,  # public endpoint
    },
    {
        "tool": "check_balance",
        "path": "/api/v1/wallet/",
        "method": "get",
        "requires_api_key": True,
    },
    {
        "tool": "send_message",
        "path": "/api/v1/tasks/{id}/messages/",
        "method": "post",
        "requires_api_key": True,
        "request_fields": {"content"},
        "tag": "messaging",
    },
    {
        "tool": "get_messages",
        "path": "/api/v1/tasks/{id}/messages/",
        "method": "get",
        "requires_api_key": True,
        "tag": "messaging",
    },
    {
        "tool": "poll_events",
        "path": "/api/v1/events/",
        "method": "get",
        "requires_api_key": True,
        "tag": "agent",
    },
    {
        "tool": "submit_review",
        "path": "/api/v1/tasks/{id}/review/",
        "method": "post",
        "requires_api_key": True,
        "request_fields": {"rating"},
        "tag": "messaging",
    },
    {
        "tool": "get_categories",
        "path": "/api/v1/tasks/categories/",
        "method": "get",
        "requires_api_key": False,  # public endpoint
        "tag": "public",
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSchemaMetadata:
    """Verify schema basics."""

    def test_schema_version(self, schema):
        assert schema["openapi"].startswith("3.")

    def test_schema_title(self, schema):
        assert schema["info"]["title"] == "GroundTruther API"

    def test_api_key_auth_scheme_exists(self, security_schemes):
        assert "apiKeyAuth" in security_schemes
        assert security_schemes["apiKeyAuth"]["scheme"] == "bearer"

    def test_jwt_auth_scheme_exists(self, security_schemes):
        assert "jwtAuth" in security_schemes
        assert security_schemes["jwtAuth"]["scheme"] == "bearer"


class TestToolEndpointExists:
    """Every MCP tool must have a corresponding endpoint in the schema."""

    @pytest.mark.parametrize("contract", TOOL_CONTRACTS, ids=lambda c: c["tool"])
    def test_endpoint_exists(self, paths, contract):
        path = contract["path"]
        method = contract["method"]
        assert path in paths, f"MCP tool '{contract['tool']}' expects {path} but it's missing from schema"
        assert method in paths[path], (
            f"MCP tool '{contract['tool']}' expects {method.upper()} {path} but only "
            f"{list(paths[path].keys())} are defined"
        )


class TestToolAuthScheme:
    """MCP tools that use API key auth must have apiKeyAuth in their security."""

    @pytest.mark.parametrize(
        "contract",
        [c for c in TOOL_CONTRACTS if c.get("requires_api_key")],
        ids=lambda c: c["tool"],
    )
    def test_api_key_auth_accepted(self, paths, contract):
        op = _get_operation(paths, contract["path"], contract["method"])
        assert _has_api_key_auth(op), (
            f"MCP tool '{contract['tool']}' requires API key auth, but "
            f"{contract['method'].upper()} {contract['path']} doesn't list apiKeyAuth in security"
        )


class TestToolRequestFields:
    """MCP tools with required request fields must have them in the schema."""

    @pytest.mark.parametrize(
        "contract",
        [c for c in TOOL_CONTRACTS if c.get("request_fields")],
        ids=lambda c: c["tool"],
    )
    def test_request_fields_present(self, paths, components, contract):
        op = _get_operation(paths, contract["path"], contract["method"])
        req_schema = _get_request_schema(op, components)
        if not req_schema:
            pytest.skip(f"No request body schema for {contract['path']}")

        field_names = _get_field_names(req_schema)
        missing = contract["request_fields"] - field_names
        assert not missing, (
            f"MCP tool '{contract['tool']}' sends fields {missing} but they're "
            f"not in the schema for {contract['method'].upper()} {contract['path']}. "
            f"Schema has: {field_names}"
        )


class TestToolTags:
    """MCP tools with expected tags must be tagged correctly in the schema."""

    @pytest.mark.parametrize(
        "contract",
        [c for c in TOOL_CONTRACTS if c.get("tag")],
        ids=lambda c: c["tool"],
    )
    def test_tag_matches(self, paths, contract):
        op = _get_operation(paths, contract["path"], contract["method"])
        tags = op.get("tags", [])
        assert contract["tag"] in tags, (
            f"MCP tool '{contract['tool']}' expects tag '{contract['tag']}' but "
            f"{contract['method'].upper()} {contract['path']} has tags: {tags}"
        )


class TestAgentEndpointCompleteness:
    """All agent-tagged endpoints must have a corresponding MCP tool."""

    def test_all_agent_endpoints_covered(self, paths):
        tool_paths = {
            (c["path"], c["method"]) for c in TOOL_CONTRACTS
        }

        uncovered = []
        for path, methods in paths.items():
            for method, operation in methods.items():
                if not isinstance(operation, dict):
                    continue
                tags = operation.get("tags", [])
                if "agent" in tags:
                    if (path, method) not in tool_paths:
                        uncovered.append(f"{method.upper()} {path}")

        # Allow some endpoints to not have MCP tools (e.g., agent creation)
        # But flag them so we can decide
        known_exceptions = {
            "POST /api/v1/agents/",  # Agent creation is done via dashboard, not MCP
            "GET /api/v1/webhooks/",  # Webhook management is optional for agents
            "POST /api/v1/webhooks/",
            "DELETE /api/v1/webhooks/{id}/",
            "POST /api/v1/tasks/{id}/drop/",  # Worker-primary; agents use cancel_task instead
        }

        unexpected = [e for e in uncovered if e not in known_exceptions]
        assert not unexpected, (
            f"Agent-tagged endpoints without MCP tool coverage: {unexpected}. "
            "Either add an MCP tool or add to known_exceptions."
        )
