"""Utilities for making LLM JSON output usable before it reaches protocols."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from services.protocols.validation import validate_protocol


class LLMJsonError(RuntimeError):
    """Base error for LLM JSON extraction or validation failures."""


class LLMJsonParseError(LLMJsonError):
    """Raised when no valid JSON object can be extracted."""


class LLMJsonValidationError(LLMJsonError):
    """Raised when extracted JSON does not match the expected shape."""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def extract_json_object(content: str) -> dict[str, Any]:
    """Extract the first JSON object from raw model text."""
    text = _strip_code_fence(content.strip())
    if not text:
        raise LLMJsonParseError("LLM returned empty content.")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        raise LLMJsonParseError(f"Expected JSON object, got {type(parsed).__name__}.")
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise LLMJsonParseError("No valid JSON object found in LLM output.")


def validate_json_payload(
    payload: dict[str, Any],
    *,
    required_fields: list[str] | tuple[str, ...] | None = None,
    field_types: dict[str, type | tuple[type, ...]] | None = None,
    enum_fields: dict[str, set[Any] | list[Any] | tuple[Any, ...]] | None = None,
    schema_name: str | None = None,
    custom_validator: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Run lightweight shape checks plus optional project protocol validation."""
    if required_fields:
        missing = [field for field in required_fields if field not in payload]
        if missing:
            raise LLMJsonValidationError(f"Missing required fields: {', '.join(missing)}")

    for field, expected_type in (field_types or {}).items():
        if field not in payload or payload[field] is None:
            continue
        if not isinstance(payload[field], expected_type):
            expected = _type_name(expected_type)
            actual = type(payload[field]).__name__
            raise LLMJsonValidationError(
                f"Field '{field}' must be {expected}, got {actual}."
            )

    for field, allowed_values in (enum_fields or {}).items():
        if field not in payload or payload[field] is None:
            continue
        if payload[field] not in set(allowed_values):
            raise LLMJsonValidationError(
                f"Field '{field}' has invalid value: {payload[field]!r}."
            )

    if custom_validator:
        try:
            custom_validator(payload)
        except LLMJsonError:
            raise
        except Exception as exc:
            raise LLMJsonValidationError(str(exc)) from exc

    if schema_name:
        try:
            validate_protocol(schema_name, payload)
        except Exception as exc:
            raise LLMJsonValidationError(str(exc)) from exc


def build_repair_prompt(
    *,
    original_user_prompt: str,
    raw_content: str,
    error: Exception,
) -> str:
    """Build a repair request that asks the model to return only valid JSON."""
    return (
        "上一次输出没有通过 JSON 解析或结构校验，请修复为一个合法 JSON object。\n"
        "不要输出 Markdown、解释文字或代码块，只输出 JSON。\n\n"
        f"校验错误：{error}\n\n"
        "原始任务如下：\n"
        f"{original_user_prompt}\n\n"
        "上一次模型输出如下：\n"
        f"{raw_content}"
    )


def _strip_code_fence(text: str) -> str:
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text


def _type_name(value: type | tuple[type, ...]) -> str:
    if isinstance(value, tuple):
        return " or ".join(item.__name__ for item in value)
    return value.__name__
