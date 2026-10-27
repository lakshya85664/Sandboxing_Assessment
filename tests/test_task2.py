
import pytest

from sandbox.runner import (
    SandboxTimeoutError,
    run_sandbox,
)


def call(operation: str, text: str, limit: int = 100):
    return run_sandbox(
        {
            "operation": operation,
            "text": text,
            "limit": limit,
        }
    )


def test_uppercase_transformation():
    response = call("uppercase", "hello")
    assert response["status"] == "ok"
    assert response["data"]["result"] == "HELLO"


def test_lowercase_transformation():
    response = call("lowercase", "HELLO")
    assert response["data"]["result"] == "hello"


def test_reverse_transformation():
    response = call("reverse", "sandbox")
    assert response["data"]["result"] == "xobdnas"


def test_word_count_transformation():
    response = call("word_count", "one two three")
    assert response["data"]["result"] == 3


def test_truncate_transformation():
    response = call("truncate", "abcdefgh", limit=4)
    assert response["data"]["result"] == "abcd"


def test_unknown_operation_is_rejected():
    response = call("execute_python", "print('hello')")
    assert response["status"] == "invalid"


def test_null_byte_is_rejected():
    response = call("uppercase", "hello\x00world")
    assert response["status"] == "invalid"


def test_invalid_timeout_configuration_is_rejected():
    with pytest.raises(ValueError, match="Timeout"):
        run_sandbox(
            {"operation": "uppercase", "text": "hello"},
            timeout_seconds=0,
        )
