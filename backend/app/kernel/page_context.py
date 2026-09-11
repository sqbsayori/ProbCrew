"""页面上下文（Page Context）—— 让助手"看得见学生正在看什么"。

这是"在线课程网站学习助手"区别于通用聊天机器人的**根本能力**：
用户问"这段是什么意思"时，系统必须知道"这段"是哪段。

多 frame 现实
------------
第三方课程平台（超星、智慧树等）的课件**大量嵌套在 iframe 里**，而且正文往往不在顶层页面。
因此注入脚本在每个 frame 各自抽取内容，再汇总到顶层渲染 UI。

本模块负责把多份 frame 上下文**归并成一份**：
- 选内容最丰富的 frame 作为主上下文（`text`/`headings`/`formulas`）；
- 其余 frame 挂在 `frames` 里，作为补充检索源；
- 顶层页面自己的导航/侧栏文字通常很少，自然会被比下去。

数据量控制
---------
页面正文可能几万字。`MAX_TEXT` 做硬截断，超出部分交给 `page_search` 工具按需检索，
避免把整页塞进 prompt（既贵又容易让模型"看花眼"）。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

#: 单个页面文本上限（字符）。超出部分仍可由 page_search 检索到。
MAX_TEXT = 12000
#: 注入 prompt 的正文上限
PROMPT_TEXT = 4000


class FrameContext(BaseModel):
    """一个 frame（顶层页或某个 iframe）抽取到的内容。"""

    url: str = ""
    title: str = ""
    headings: list[dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    selection: str = ""
    formulas: list[str] = Field(default_factory=list)
    #: {"kind": "video"|"audio", "currentTime": 12.3, "duration": 300, "title": "..."}
    media: Optional[dict[str, Any]] = None
    #: 如果这个 frame 是我们的交互动画（adapter 上报）
    animation: Optional[dict[str, Any]] = None
    scroll_pct: Optional[float] = None
    #: 内容丰富度评分，用于选出主 frame
    score: float = 0.0


class PageContext(BaseModel):
    """归并后的页面上下文（送给 Agent 的那一份）。"""

    url: str = ""
    title: str = ""
    headings: list[dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    selection: str = ""
    formulas: list[str] = Field(default_factory=list)
    media: Optional[dict[str, Any]] = None
    animation: Optional[dict[str, Any]] = None
    scroll_pct: Optional[float] = None
    frames: list[FrameContext] = Field(default_factory=list)
    source: str = "widget"  # widget | userscript | api | spa

    # ---- 派生信息 ----

    @property
    def char_count(self) -> int:
        return len(self.text or "")

    @property
    def has_selection(self) -> bool:
        return bool((self.selection or "").strip())

    @property
    def has_content(self) -> bool:
        return self.char_count > 0 or self.has_selection

    def outline(self, limit: int = 20) -> str:
        """把标题层级压成一行行的目录，给模型一个整体结构感。"""
        lines: list[str] = []
        for h in (self.headings or [])[:limit]:
            level = int(h.get("level") or 2)
            text = str(h.get("text") or "").strip()
            if text:
                lines.append(f"{'  ' * max(level - 1, 0)}- {text}")
        return "\n".join(lines)

    def summary_line(self) -> str:
        """给用户看的一句话：「已读取《…》共 3,240 字，含 12 个公式」。"""
        bits: list[str] = []
        if self.title:
            bits.append(f"《{self.title}》")
        bits.append(f"{self.char_count:,} 字")
        if self.formulas:
            bits.append(f"{len(self.formulas)} 个公式")
        if self.has_selection:
            bits.append(f"已选中 {len(self.selection.strip())} 字")
        if self.media:
            bits.append("含视频进度")
        if self.animation:
            bits.append(f"交互动画《{self.animation.get('title') or self.animation.get('id')}》")
        if len(self.frames) > 1:
            bits.append(f"跨 {len(self.frames)} 个框架")
        return "已读取 " + "、".join(bits)

    # ---- 给 LLM 的文本块 ----

    def to_prompt(self, max_chars: int = PROMPT_TEXT) -> str:
        """把页面上下文格式化成 prompt 片段。"""
        parts: list[str] = []
        if self.title:
            parts.append(f"【当前页面标题】{self.title}")
        if self.url:
            parts.append(f"【当前页面地址】{self.url}")

        outline = self.outline()
        if outline:
            parts.append(f"【页面大纲】\n{outline}")

        if self.has_selection:
            sel = self.selection.strip()
            parts.append(
                "【用户当前选中的文字】（这是用户提问的直接对象，优先解释它）\n"
                f"<<<\n{sel[:2000]}\n>>>"
            )

        if self.media:
            cur = self.media.get("currentTime")
            dur = self.media.get("duration")
            if cur is not None:
                pos = f"{float(cur):.0f} 秒"
                if dur:
                    pos += f" / 共 {float(dur):.0f} 秒"
                parts.append(
                    f"【学生视频进度】看到 {pos}"
                    + (f"（标题：{self.media.get('title')}）" if self.media.get("title") else "")
                )

        if self.animation:
            parts.append(
                "【学生正在操作的动画】"
                f"{self.animation.get('title') or self.animation.get('id')}"
                + (f"，当前状态：{self.animation.get('state')}" if self.animation.get("state") else "")
            )

        if self.text:
            body = self.text[:max_chars]
            truncated = "\n…（页面较长，此处截断；需要更多内容请调用 page_search 工具检索）" if self.char_count > max_chars else ""
            parts.append(f"【当前页面正文】\n{body}{truncated}")

        if self.formulas:
            parts.append("【页面中出现的公式】\n" + "\n".join(f"- {f}" for f in self.formulas[:12]))

        return "\n\n".join(parts)


# --------------------------------------------------------------------------
# 多 frame 归并
# --------------------------------------------------------------------------


def _frame_score(f: FrameContext) -> float:
    """内容丰富度：正文长度为主，公式/标题/选中文字加分。"""
    return (
        len(f.text or "")
        + 40 * len(f.formulas or [])
        + 20 * len(f.headings or [])
        + 600 * (1 if f.selection else 0)
        + 200 * (1 if f.media else 0)
    )


def merge_frames(frames: list[FrameContext], *, source: str = "userscript") -> PageContext:
    """把多个 frame 的抽取结果归并成一份 PageContext。

    主上下文取"内容最丰富"的那个 frame —— 在真实课程平台上，
    这通常就是装着课件正文的那个 iframe，而不是顶层导航壳。
    """
    frames = [f for f in frames if f is not None]
    if not frames:
        return PageContext(source=source)

    for f in frames:
        f.score = _frame_score(f)
    ordered = sorted(frames, key=lambda f: f.score, reverse=True)
    primary = ordered[0]

    # 选中文字可能出现在任意 frame（用户可能在 iframe 里划词）—— 优先取非空的第一个
    selection = next((f.selection for f in ordered if (f.selection or "").strip()), "")
    media = next((f.media for f in ordered if f.media), None)
    animation = next((f.animation for f in ordered if f.animation), None)

    # 补充正文：把其他 frame 的正文按需拼接（总额受 MAX_TEXT 限制）
    text = primary.text or ""
    if len(text) < MAX_TEXT:
        for f in ordered[1:]:
            extra = (f.text or "").strip()
            if not extra:
                continue
            room = MAX_TEXT - len(text)
            if room < 200:
                break
            text += f"\n\n---\n\n{f.url or f.title or '其他框架'}\n{extra[:room]}"

    return PageContext(
        url=primary.url,
        title=primary.title or primary.url,
        headings=primary.headings or [],
        text=text[:MAX_TEXT],
        selection=selection,
        formulas=primary.formulas or [],
        media=media,
        animation=animation,
        scroll_pct=primary.scroll_pct,
        frames=frames,
        source=source,
    )


def from_payload(payload: dict[str, Any] | None) -> Optional[PageContext]:
    """从前端请求体里解析 page_context。容错优先：解析失败返回 None 而不是报错。"""
    if not payload:
        return None
    try:
        frames_raw = payload.get("frames") or []
        frames = [FrameContext(**f) for f in frames_raw if isinstance(f, dict)]
        if frames:
            ctx = merge_frames(frames, source=payload.get("source") or "widget")
            # 顶层单独传来的 selection 优先（用户在顶层页面划词）
            if (payload.get("selection") or "").strip():
                ctx.selection = payload["selection"]
            return ctx
        ctx = PageContext(**{k: v for k, v in payload.items() if k in PageContext.model_fields})
        ctx.text = (ctx.text or "")[:MAX_TEXT]
        return ctx if ctx.has_content else ctx
    except Exception:  # noqa: BLE001 —— 上下文解析失败绝不能阻塞提问
        return None


def chunk_text(text: str, size: int = 420, overlap: int = 80) -> list[str]:
    """把页面正文切成带重叠的块，供 page_search 做页内检索。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    step = max(size - overlap, 1)
    for i in range(0, len(text), step):
        piece = text[i : i + size]
        if piece.strip():
            chunks.append(piece)
        if i + size >= len(text):
            break
    return chunks
