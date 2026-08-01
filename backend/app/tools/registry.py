"""The tool registry: name -> (Anthropic schema, input model, handler).

One place that knows every tool. The agent loop dispatches through this and
nothing else, so a tool cannot be reachable without a validated input model.

Order is deliberate and stable. Tool definitions render BEFORE the system
prompt, so any reordering changes the cached prefix and invalidates the prompt
cache for every request. Do not sort this at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..envelope import ToolEnvelope

# Symbols are imported directly rather than as modules. Each tool module
# re-exports a function with the same name as the module itself (via
# tools/__init__.py), so `from . import describe_coverage` binds the FUNCTION
# and every `.TOOL_NAME` lookup below would fail on it.
from .describe_coverage import (
    ANTHROPIC_TOOL as DESCRIBE_COVERAGE_SCHEMA,
    TOOL_NAME as DESCRIBE_COVERAGE,
    DescribeCoverageInput,
    describe_coverage as run_describe_coverage,
)
from .get_brand_share import (
    ANTHROPIC_TOOL as GET_BRAND_SHARE_SCHEMA,
    TOOL_NAME as GET_BRAND_SHARE,
    GetBrandShareInput,
    get_brand_share as run_get_brand_share,
)
from .get_market_size import (
    ANTHROPIC_TOOL as GET_MARKET_SIZE_SCHEMA,
    TOOL_NAME as GET_MARKET_SIZE,
    GetMarketSizeInput,
    get_market_size as run_get_market_size,
)
from .get_segment_penetration import (
    ANTHROPIC_TOOL as GET_SEGMENT_PENETRATION_SCHEMA,
    TOOL_NAME as GET_SEGMENT_PENETRATION,
    GetSegmentPenetrationInput,
    get_segment_penetration as run_get_segment_penetration,
)
from .list_dimension_values import (
    ANTHROPIC_TOOL as LIST_DIMENSION_VALUES_SCHEMA,
    TOOL_NAME as LIST_DIMENSION_VALUES,
    ListDimensionValuesInput,
    list_dimension_values as run_list_dimension_values,
)
from .render_chart import (
    ANTHROPIC_TOOL as RENDER_CHART_SCHEMA,
    TOOL_NAME as RENDER_CHART,
    RenderChartInput,
    render_chart as run_render_chart,
)
from .run_sql import (
    ANTHROPIC_TOOL as RUN_SQL_SCHEMA,
    TOOL_NAME as RUN_SQL,
    RunSqlInput,
    run_sql as run_run_sql,
)


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    schema: dict[str, Any]
    input_model: type[BaseModel]
    handler: Callable[..., ToolEnvelope]
    # render_chart alone needs to see earlier results in the turn, to check that
    # the tool call it references exists and has the columns it names.
    needs_turn_results: bool = False


# Ordered: discovery tools first, so the model sees the "check before you
# filter" tools at the top of its list.
TOOLS: tuple[RegisteredTool, ...] = (
    RegisteredTool(
        name=DESCRIBE_COVERAGE,
        schema=DESCRIBE_COVERAGE_SCHEMA,
        input_model=DescribeCoverageInput,
        handler=run_describe_coverage,
    ),
    RegisteredTool(
        name=LIST_DIMENSION_VALUES,
        schema=LIST_DIMENSION_VALUES_SCHEMA,
        input_model=ListDimensionValuesInput,
        handler=run_list_dimension_values,
    ),
    RegisteredTool(
        name=GET_MARKET_SIZE,
        schema=GET_MARKET_SIZE_SCHEMA,
        input_model=GetMarketSizeInput,
        handler=run_get_market_size,
    ),
    RegisteredTool(
        name=GET_SEGMENT_PENETRATION,
        schema=GET_SEGMENT_PENETRATION_SCHEMA,
        input_model=GetSegmentPenetrationInput,
        handler=run_get_segment_penetration,
    ),
    RegisteredTool(
        name=GET_BRAND_SHARE,
        schema=GET_BRAND_SHARE_SCHEMA,
        input_model=GetBrandShareInput,
        handler=run_get_brand_share,
    ),
    RegisteredTool(
        name=RENDER_CHART,
        schema=RENDER_CHART_SCHEMA,
        input_model=RenderChartInput,
        handler=run_render_chart,
        needs_turn_results=True,
    ),
    # Last on purpose: the escape hatch should be the model's final resort,
    # and every invocation is logged so uncovered questions can be promoted.
    RegisteredTool(
        name=RUN_SQL,
        schema=RUN_SQL_SCHEMA,
        input_model=RunSqlInput,
        handler=run_run_sql,
    ),
)

BY_NAME: dict[str, RegisteredTool] = {t.name: t for t in TOOLS}


def anthropic_tool_schemas() -> list[dict[str, Any]]:
    return [t.schema for t in TOOLS]


def dispatch(
    name: str,
    raw_input: dict[str, Any],
    turn_results: dict[str, ToolEnvelope] | None = None,
) -> ToolEnvelope:
    """Validate and run one tool call.

    Every failure path returns an envelope rather than raising. The agent loop
    must be able to hand the model a `tool_result` for every `tool_use` block it
    emitted -- a missing result breaks the conversation -- and a validation
    error the model can read is more useful than a stack trace it cannot.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        return ToolEnvelope.failed(
            f"Unknown tool {name!r}. Available tools: {sorted(BY_NAME)}."
        )

    try:
        parsed = tool.input_model.model_validate(raw_input)
    except ValidationError as exc:
        return ToolEnvelope.failed(
            f"Invalid arguments for {name}: {_readable(exc)}",
            params=raw_input,
        )

    try:
        if tool.needs_turn_results:
            return tool.handler(parsed, turn_results or {})
        return tool.handler(parsed)
    except Exception as exc:  # noqa: BLE001 - the model needs to see this, not a 500
        return ToolEnvelope.failed(
            f"{name} failed: {type(exc).__name__}: {exc}", params=raw_input
        )


def _readable(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
