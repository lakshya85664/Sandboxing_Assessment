
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SandboxInput(BaseModel):
    """Validated request for a restricted data transformation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str = Field(min_length=1, max_length=100)
    principal_id: str = Field(min_length=1, max_length=100)
    operation: Literal[
        "uppercase",
        "lowercase",
        "reverse",
        "word_count",
        "truncate",
    ]
    text: str = Field(max_length=10_000)
    limit: int = Field(default=100, ge=1, le=1_000)

    @field_validator("request_id", "principal_id")
    @classmethod
    def reject_blank_identifiers(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Identifier must not be blank")
        return value

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Null bytes are not allowed")
        return value


class SandboxOutput(BaseModel):
    """Public result returned by the sandbox gateway."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal[
        "ok",
        "invalid",
        "denied",
        "timeout",
        "failed",
        "rate_limited",
    ]
    request_id: str | None = None
    data: dict[str, str | int] = Field(default_factory=dict)
    error: str | None = None
    next_action: str | None = None
    events: list[dict[str, str | int | float | bool | None]] = Field(
        default_factory=list
    )


class ToolContract(BaseModel):
    """Registry metadata describing one callable tool."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    version: str
    description: str
    input_model: str
    output_model: str
    access: Literal["read", "write"]
    allowed_roles: list[str]
    allowed_operations: list[str]
    timeout_seconds: float = Field(gt=0, le=10)
    max_output_chars: int = Field(ge=1, le=10_000)
