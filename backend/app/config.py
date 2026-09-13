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

    # CORS 白名单：逗号分隔，默认 `*`（本地开发不变）。
    # 部署到服务器时必须收窄，例如 `https://probstat.example.edu,https://a.example.edu`。
    cors_origins: str = "*"
    # 带 Cookie/凭证的跨域请求需要精确 Origin（不能是 `*`），
    # 因此只在把 cors_origins 收窄成白名单后才建议打开。
    cors_allow_credentials: bool = False

    # ---- 存储 ----
    # 默认与改造前完全一致：backend/data/learning.sqlite（该目录已在 .gitignore，不进仓库）。
    # 部署时改 `DB_PATH`（相对路径按仓库根解析）或直接给 `DB_URL`。
    db_path: str = "backend/data/learning.sqlite"
    db_url: str = ""  # 形如 sqlite:///绝对路径；填了就覆盖上面的默认值

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

    # ---- 检索（M2 检索升级，docs/12）----
    # 混合检索：BM25（必留，LaTeX 公式靠它）+ 向量 + 重排。
    # 模型**全部本地跑**（数据不出校），因此这里给的是"本地权重目录/名字"，
    # 不联网下载；缺失时 `embedding`/`reranker` 会显式报 `available=False`，
    # 检索自动退回 BM25 —— 不允许静默降级成"看起来在跑向量"。
    kb_backend: str = "auto"  # auto | hybrid | bm25
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    #: 向量层的候选截断：按**排名**取前 N，而不是按绝对余弦阈值。
    #: 原因：离线降级实现（hash-bigram）的相似度整体偏小（0.1~0.4），
    #: 用绝对阈值会把所有候选都过滤掉，等于向量层静默失效。
    #: 换成真正的 BGE 后若想用阈值，把 `EMBEDDING_MIN_SCORE` 设成 0.3~0.5 即可
    #: （两者同时生效：先按阈值，再按排名取前 N）。
    vector_candidates: int = 12
    #: 余弦相似度的绝对下限：低于它就不算向量候选（挡住"跟谁都有点像"的噪声）。
    #: 默认 0.35 是**实测**出来的：BGE-M3 在中文语料上
    #:   正确片段 ≥0.45、完全无关的问题（红烧肉/换轮胎）≤0.37；
    #: 而离线降级实现（hash-bigram）的相似度整体偏小，那时应设成 0.08 左右。
    embedding_min_score: float = 0.35
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidates: int = 12  # 进入重排的候选数（重排很贵，先粗排收窄）
    models_dir: str = ""  # 本地权重根目录（HF 缓存或直接放模型文件夹）；空=用默认缓存
    allow_model_download: bool = False  # 默认禁止联网下载（数据不出校 / CI 离线）

    @property
    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "deepseek" if self.deepseek_api_key.strip() else "mock"

    @property
    def models_root(self) -> Path:
        """本地模型根目录（不存在时返回默认 HF 缓存位置，只读不创建）。"""
        if self.models_dir.strip():
            p = Path(self.models_dir.strip())
            return p if p.is_absolute() else (PROJECT_ROOT / p)
        return Path.home() / ".cache" / "huggingface" / "hub"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置解析成列表。空值回落为 `*`。"""
        items = [o.strip().rstrip("/") for o in self.cors_origins.split(",")]
        return [o for o in items if o] or ["*"]

    @property
    def resolved_db_path(self) -> Path:
        """学习记录库的绝对路径。相对路径一律按仓库根解析，避免受启动目录影响。"""
        raw = self.db_url or self.db_path
        if raw.startswith("sqlite:///"):
            raw = raw[len("sqlite:///") :]
        p = Path(raw)
        return p if p.is_absolute() else (PROJECT_ROOT / p)


settings = Settings()
