import os
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from services.llm.json_guard import (
    LLMJsonError,
    build_repair_prompt,
    extract_json_object,
    validate_json_payload,
)


load_dotenv()


class DeepSeekClient:
    """
    DeepSeek API 客户端。
    使用 OpenAI-compatible API 格式。
    """

    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

        if not api_key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY，请先在 .env 中配置。")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.fast_model = os.getenv("DEEPSEEK_MODEL_FAST", "deepseek-v4-flash")
        self.reasoning_model = os.getenv(
            "DEEPSEEK_MODEL_REASONING",
            "deepseek-v4-pro",
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 2000,
        required_fields: list[str] | tuple[str, ...] | None = None,
        field_types: dict[str, type | tuple[type, ...]] | None = None,
        enum_fields: dict[str, set[Any] | list[Any] | tuple[Any, ...]] | None = None,
        schema_name: str | None = None,
        custom_validator: Callable[[dict[str, Any]], None] | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        """Request JSON, extract it, validate it, and retry repair once by default."""
        selected_model = model or self.fast_model
        retries = (
            int(os.getenv("LLM_JSON_REPAIR_RETRIES", "1"))
            if max_retries is None
            else max_retries
        )
        current_system_prompt = system_prompt
        current_user_prompt = user_prompt
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            content = self._complete_json_text(
                system_prompt=current_system_prompt,
                user_prompt=current_user_prompt,
                model=selected_model,
                max_tokens=max_tokens,
            )

            try:
                payload = extract_json_object(content)
                validate_json_payload(
                    payload,
                    required_fields=required_fields,
                    field_types=field_types,
                    enum_fields=enum_fields,
                    schema_name=schema_name,
                    custom_validator=custom_validator,
                )
                return payload
            except LLMJsonError as exc:
                last_error = exc
                if attempt >= retries:
                    raise
                current_system_prompt = (
                    "你是一个严格的 JSON 修复器。"
                    "你只能输出一个合法 JSON object，不能输出 Markdown 或解释文字。"
                )
                current_user_prompt = build_repair_prompt(
                    original_user_prompt=user_prompt,
                    raw_content=content,
                    error=exc,
                )

        raise LLMJsonError(f"LLM JSON repair failed: {last_error}")

    def _complete_json_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
    ) -> str:
        """Call the model once and return raw message content."""
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            stream=False,
        )

        content = response.choices[0].message.content

        if not content:
            raise RuntimeError("DeepSeek 返回了空内容。")

        return content


_client_instance: DeepSeekClient | None = None


def get_deepseek_client() -> DeepSeekClient:
    """返回共享的 DeepSeekClient 实例（延迟初始化单例）。"""
    global _client_instance
    if _client_instance is None:
        _client_instance = DeepSeekClient()
    return _client_instance
