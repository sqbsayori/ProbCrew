"""LLM Provider 的抽象基类。

统一接口
-------
    async for piece in provider.stream(system=..., user=..., agent=...): ...
    text = await provider.complete(system=..., user=..., agent=...)

抽象层的四个理由
---------------
1. **零配置可跑**：没有 API Key 时自动降级到 `MockProvider`，
   全组 5 人当天就能跑通端到端，不必等某个人申请到 Key。
2. **可换厂商**：DeepSeek / Qwen / GLM 都走 OpenAI 兼容端点，换 base_url 即可。
3. **可测试**：CI 里强制用 mock，不花钱、不联网、结果确定。
4. **分权选型**：生成型 Agent 用强模型、验证型 Agent 可用轻模型降本
   （见 `docs/开发计划.md` 的成本控制）。
"""
from __future__ import annotations

from typing import AsyncIterator


class LLMProvider:
    name = "base"

    async def stream(self, *, system: str, user: str, agent: str = "") -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover —— 让类型检查认出这是异步生成器

    async def complete(self, *, system: str, user: str, agent: str = "") -> str:
        chunks: list[str] = []
        async for piece in self.stream(system=system, user=user, agent=agent):
            chunks.append(piece)
        return "".join(chunks)
