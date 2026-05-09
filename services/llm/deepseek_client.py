import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


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
    ) -> dict[str, Any]:
        """
        要求模型返回 JSON，并解析为 dict。
        """

        selected_model = model or self.fast_model

        response = self.client.chat.completions.create(
            model=selected_model,
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

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "DeepSeek 返回内容不是合法 JSON"
            ) from exc


_client_instance: DeepSeekClient | None = None


def get_deepseek_client() -> DeepSeekClient:
    """返回共享的 DeepSeekClient 实例（延迟初始化单例）。"""
    global _client_instance
    if _client_instance is None:
        _client_instance = DeepSeekClient()
    return _client_instance