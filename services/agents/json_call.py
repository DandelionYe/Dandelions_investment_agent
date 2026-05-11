"""Compatibility wrapper for validated LLM JSON calls."""

from typing import Any

from services.llm.json_guard import validate_json_payload


def chat_json_checked(
    client,
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    max_tokens: int,
    metadata: dict[str, Any] | None = None,
    **validation: Any,
) -> dict:
    """Call client.chat_json with validation, while tolerating old test doubles."""
    try:
        payload = client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            **validation,
        )
        if metadata is not None:
            payload = dict(payload)
            payload["metadata"] = metadata
        return payload
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise

    payload = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        max_tokens=max_tokens,
    )
    validate_json_payload(payload, **validation)
    if metadata is not None:
        payload = dict(payload)
        payload["metadata"] = metadata
    return payload
