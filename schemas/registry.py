
from __future__ import annotations

from schemas.tool_contract import ToolContract


SANDBOX_TOOL = ToolContract(
    name="sandbox_transform",
    version="1.0.0",
    description=(
        "Apply one allowlisted text transformation using bounded input, "
        "execution, and output limits."
    ),
    input_model="SandboxInput",
    output_model="SandboxOutput",
    access="write",
    allowed_roles=[
        "support_writer",
        "admin",
    ],
    allowed_operations=[
        "uppercase",
        "lowercase",
        "reverse",
        "word_count",
        "truncate",
    ],
    timeout_seconds=2.0,
    max_output_chars=1_000,
)

TOOL_REGISTRY: dict[str, ToolContract] = {
    SANDBOX_TOOL.name: SANDBOX_TOOL,
}


def get_tool(name: str) -> ToolContract | None:
    """Return registered metadata, or None for an unknown tool."""
    return TOOL_REGISTRY.get(name)


def registry_summary() -> list[dict[str, object]]:
    """Return a JSON-serializable view of registered tool metadata."""
    return [
        {
            "name": tool.name,
            "version": tool.version,
            "access": tool.access,
            "allowed_roles": tool.allowed_roles,
            "allowed_operations": tool.allowed_operations,
            "timeout_seconds": tool.timeout_seconds,
            "max_output_chars": tool.max_output_chars,
        }
        for tool in TOOL_REGISTRY.values()
    ]
