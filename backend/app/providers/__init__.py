"""LLM Provider 工厂。

`get_provider()` 是唯一的取用入口：Agent 永远不直接 new 具体 provider，
因此换模型 / 换厂商 / 切 mock 都只改这一处。
"""
from __future__ import annotations

from .base import LLMProvider
from .mock import MockProvider

__all__ = ["LLMProvider", "MockProvider", "get_provider"]


def get_provider(settings) -> LLMProvider:
    """按配置返回 provider。auto 模式：有 Key 用 DeepSeek，没有就用 Mock。"""
    resolved = settings.resolved_provider
    if resolved == "deepseek":
        # 延迟导入：只有真要用真模型时才需要 langchain-openai
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(settings)
    return MockProvider(settings)
