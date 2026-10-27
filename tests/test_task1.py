
import pytest
from pydantic import ValidationError

from schemas.registry import SANDBOX_TOOL, TOOL_REGISTRY, get_tool
from schemas.tool_contract import SandboxInput, SandboxOutput, ToolContract


def valid_payload() -> dict:
    return {
        "request_id": "req-001",
        "principal_id": "user-001",
        "operation": "uppercase",
        "text": "hello sandbox",
        "limit": 100,
    }


def test_valid_sandbox_input():
    request = SandboxInput.model_validate(valid_payload())

    assert request.operation == "uppercase"
    assert request.text == "hello sandbox"


def test_unknown_operation_is_rejected():
    payload = valid_payload()
    payload["operation"] = "execute_python"

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_unknown_input_field_is_rejected():
    payload = valid_payload()
    payload["arbitrary_code"] = "print('unsafe')"

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_input_rejects_wrong_types():
    payload = valid_payload()
    payload["limit"] = "100"

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_input_rejects_out_of_range_limit():
    payload = valid_payload()
    payload["limit"] = 1001

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_input_rejects_blank_principal():
    payload = valid_payload()
    payload["principal_id"] = "   "

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_input_rejects_null_byte():
    payload = valid_payload()
    payload["text"] = "hello\x00world"

    with pytest.raises(ValidationError):
        SandboxInput.model_validate(payload)


def test_output_contract_accepts_success():
    result = SandboxOutput(
        status="ok",
        request_id="req-001",
        data={"result": "HELLO"},
    )

    assert result.status == "ok"
    assert result.data["result"] == "HELLO"


def test_output_contract_rejects_unknown_status():
    with pytest.raises(ValidationError):
        SandboxOutput(status="success")


def test_registry_contains_sandbox_tool():
    assert "sandbox_transform" in TOOL_REGISTRY
    assert get_tool("sandbox_transform") == SANDBOX_TOOL


def test_unknown_tool_returns_none():
    assert get_tool("not_registered") is None


def test_registry_declares_operations_and_roles():
    assert set(SANDBOX_TOOL.allowed_operations) == {
        "uppercase",
        "lowercase",
        "reverse",
        "word_count",
        "truncate",
    }
    assert "admin" in SANDBOX_TOOL.allowed_roles


def test_registry_declares_resource_limits():
    assert 0 < SANDBOX_TOOL.timeout_seconds <= 10
    assert 1 <= SANDBOX_TOOL.max_output_chars <= 10_000


def test_registry_metadata_is_typed():
    assert isinstance(SANDBOX_TOOL, ToolContract)
    assert SANDBOX_TOOL.version == "1.0.0"
    assert SANDBOX_TOOL.access == "write"
