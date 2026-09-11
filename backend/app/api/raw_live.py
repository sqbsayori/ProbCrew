"""`/raw-live/` —— 给原始动画页"在线注入"悬浮窗（**不修改磁盘上的文件**）。

为什么需要这个模块
----------------
团队要的是"在 `F:\\学习资料\\大创\\动画` 那些页面上看到悬浮窗"。有三条路：

1. **直接改那 8 个 html** —— ❌ 违背"动画文件一字不改"的原则。
   它们要能离线、能单独分发、能塞进数字教材，不能被我们污染。
2. **油猴脚本** —— ✅ 可行且不改文件，但要求每个人装 Tampermonkey、
   配 `@require`、允许本地地址，第一次试用的摩擦太大。
3. **本模块** —— ✅ 读取原文件，在响应的最后一刻把 loader 注入到 `</body>` 前面再返回。

于是：

    /raw/贝叶斯公式(g).html        → 原始文件，一个字没动
    /raw-live/贝叶斯公式(g).html   → 同一个文件 + 悬浮窗

而且 `/raw-live/` 与后端**同源**，所以：跨域问题没有、iframe 能读、动画能驱动。

顺带一个好处：`/raw-live/index.html` 是那个导航页，它里面的相对链接
（`./贝叶斯公式(g).html`）会自动解析到 `/raw-live/贝叶斯公式(g).html`，
所以整个文件夹在 `/raw-live/` 下是一个"带悬浮窗的完整镜像"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ..config import RAW_ANIMATIONS_DIR

router = APIRouter(tags=["raw-live"])

#: 注入的脚本。data-api="" 表示与页面同源（也就是后端自己）。
INJECT_SNIPPET = """
<!-- 概率论伴学助手（由后端在响应时注入，磁盘上的原文件未被修改） -->
<script src="/widget/loader.js" data-api="" data-auto-open="false" data-skin="pet"></script>
"""


def _safe_resolve(filename: str) -> Path:
    """把请求路径解析到 RAW_ANIMATIONS_DIR 内的真实文件，杜绝目录穿越。"""
    # 只取最后一段，丢掉任何 ../ 或子目录
    name = Path(filename.replace("\\", "/")).name
    if not name:
        raise HTTPException(status_code=404, detail="未指定文件")

    base = RAW_ANIMATIONS_DIR.resolve()
    target = (base / name).resolve()

    # 双保险：解析后必须仍在基目录内
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径越界") from None

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{name}")
    return target


def _inject(html: str) -> str:
    """把 loader 注入到最后一个 </body> 之前（大小写不敏感）。"""
    lowered = html.lower()
    idx = lowered.rfind("</body>")
    if idx < 0:
        return html + INJECT_SNIPPET
    return html[:idx] + INJECT_SNIPPET + html[idx:]


@router.get(
    "/raw-live/",
    summary="原始动画导航页（带悬浮窗）",
    response_class=HTMLResponse,
)
async def raw_live_index() -> HTMLResponse:
    """`/raw-live/` 直接给导航页，省得手打 index.html。"""
    index = RAW_ANIMATIONS_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="原始动画文件夹里没有 index.html")
    return HTMLResponse(
        content=_inject(index.read_text(encoding="utf-8")),
        media_type="text/html; charset=utf-8",
    )


@router.get(
    "/raw-live/{filename}",
    summary="任意原始动画页（带悬浮窗）",
    response_class=HTMLResponse,
)
async def raw_live_page(filename: str) -> HTMLResponse:
    path = _safe_resolve(filename)

    if path.suffix.lower() not in (".html", ".htm"):
        raise HTTPException(status_code=415, detail="只处理 html 文件")

    try:
        html = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = path.read_text(encoding="utf-8", errors="replace")

    return HTMLResponse(content=_inject(html), media_type="text/html; charset=utf-8")


@router.get("/api/raw-live/list", summary="可注入的原始动画清单")
async def raw_live_list() -> dict[str, Any]:
    """列出 `/raw-live/` 下可访问的页面，方便前端做入口。"""
    base = RAW_ANIMATIONS_DIR
    if not base.is_dir():
        return {"available": False, "dir": str(base), "items": []}

    items = [
        {
            "file": p.name,
            "size": p.stat().st_size,
            "url": "/raw-live/" + p.name,
            "raw_url": "/raw/" + p.name,
        }
        for p in sorted(base.glob("*.html"))
    ]
    return {
        "available": True,
        "dir": str(base),
        "count": len(items),
        "items": items,
        "note": "这些页面由后端在响应时注入悬浮窗，磁盘上的原始文件未被修改。",
    }
