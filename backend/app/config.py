"""全局配置。所有可调项集中在此，便于 R5 统一管理环境。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> app -> backend -> ProbCrew
#   parents[0]=app  parents[1]=backend  parents[2]=ProbCrew
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
ANIMATIONS_DIR = FRONTEND_DIR / "assets" / "animations"

#: 团队原始的动画文件夹，挂到 `/raw` 与 `/raw-live/` 由 http 提供。
#:
#: 为什么必须用 http 而不是 file://：`file://` 下浏览器把页面视为 opaque origin ——
#: 既调不通后端（CORS 被拒），也读不到 iframe，悬浮窗等于废掉。
#: 换成 http 之后一次性解决，而且**不修改那 8 个原始文件**。
#:
#: 候选顺序（取第一个存在的）：
#:   1. `<工作区根>/动画`                  —— 开发时的实际摆放
#:   2. `<工作区根>/大创/动画`              —— 若 ProbCrew 直接放在工作区根
#:   3. `ProbCrew/../动画`               —— 若动画文件夹被移进 大创/
#:   4. `frontend/assets/animations/_raw`   —— ★ 分发包专用：清单里已经带了这 8 个动画的
#:                                            副本，所以演示包解压后开箱即用，
#:                                            不依赖外部文件夹
_RAW_CANDIDATES = (
    PROJECT_ROOT.parent.parent / "动画",
    PROJECT_ROOT.parent.parent / "大创" / "动画",
    PROJECT_ROOT.parent / "动画",
    ANIMATIONS_DIR / "_raw",
)


def _pick_raw_animations_dir() -> Path:
    for cand in _RAW_CANDIDATES:
        if cand.is_dir():
            return cand
    return _RAW_CANDIDATES[0]  # 都不存在时返回首选，挂载逻辑会跳过


RAW_ANIMATIONS_DIR = _pick_raw_animations_dir()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 服务 ----
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # ---- LLM ----
    # auto = 有 API Key 用 DeepSeek，否则自动降级为 mock（保证零配置可跑）
    llm_provider: str = "auto"  # auto | deepseek | mock
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_timeout_s: int = 60

    # ---- 协作机制开关（对应架构重构建议的 P0 机制）----
    hitl_enabled: bool = True  # 人机协同闸门
    verify_enabled: bool = True  # 生成/验证分权

    # ---- 演示友好项 ----
    mock_delay_ms: int = 18  # mock 模式下每个流式片段的延迟，让轨迹可见

    @property
    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "deepseek" if self.deepseek_api_key.strip() else "mock"


settings = Settings()
