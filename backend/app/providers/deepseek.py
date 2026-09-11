"""DeepSeek Provider（OpenAI 兼容端点）。

同时适用于通义千问 / 智谱 GLM —— 只改 `DEEPSEEK_BASE_URL` 与模型名即可，
这也是主计划里"国内模型统一兼容端点"的落地。
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(self, settings: Any) -> None:
        from langchain_openai import ChatOpenAI

        self.settings = settings
        self._client = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_s,
            streaming=True,
        )

    @staticmethod
    def _text(content: Any) -> str:
        """兼容 langchain 不同版本的 content 形态（str 或 content blocks）。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            out: list[str] = []
            for block in content:
                if isinstance(block, str):
                    out.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    out.append(str(block.get("text", "")))
            return "".join(out)
        return str(content or "")

    async def stream(self, *, system: str, user: str, agent: str = "") -> AsyncIterator[str]:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        async for chunk in self._client.astream(messages):
            piece = self._text(getattr(chunk, "content", ""))
            if piece:
                yield piece
