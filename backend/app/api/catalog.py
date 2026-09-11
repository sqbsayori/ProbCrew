"""资源目录 API —— 前端用来"自我描述"：有哪些 Agent、工具、动画、分布。

价值：前端不需要硬编码任何清单。新增一个 Agent/动画，前端自动就能看到，
这直接支撑"便于分工协作"（各人加自己的东西，没人需要去改前端列表）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ..domain import distributions as D
from ..kernel.registry import AgentRegistry, ToolRegistry
from ..tools import animation as anim_tool

router = APIRouter(tags=["catalog"])


@router.get("/api/agents", summary="所有已注册的 Agent（自动发现）")
async def list_agents(request: Request) -> dict[str, Any]:
    agents: AgentRegistry = request.app.state.agents
    items = agents.describe()
    return {"count": len(items), "items": items}


@router.get("/api/tools", summary="所有已注册的工具（自动发现）")
async def list_tools(request: Request) -> dict[str, Any]:
    tools: ToolRegistry = request.app.state.tools
    items = tools.describe()
    return {"count": len(items), "items": items}


@router.get("/api/animations", summary="交互动画清单")
async def list_animations(category: str | None = None) -> dict[str, Any]:
    manifest = anim_tool.load_manifest()
    items = anim_tool.all_animations()
    if category and category != "全部":
        items = [a for a in items if a.get("category") == category]
    base = manifest.get("basePath", "/animations/_raw/")
    return {
        "count": len(items),
        "categories": manifest.get("categories", ["全部"]),
        "adapter": manifest.get("adapter", "/animations/adapter.html"),
        "basePath": base,
        "items": [
            {**a, "url": f"{base}{a.get('file')}"}
            for a in items
        ],
    }


class RecommendRequest(BaseModel):
    query: str
    top_k: int = 2


@router.post("/api/animations/recommend", summary="按问题推荐交互动画")
async def recommend_animation(req: RecommendRequest) -> dict[str, Any]:
    matches = anim_tool.recommend(req.query, top_k=max(1, min(req.top_k, 8)))
    return {"query": req.query, "count": len(matches), "matches": matches}


@router.get("/api/distributions", summary="可视化模块支持的分布")
async def list_distributions() -> dict[str, Any]:
    items = D.describe_catalog()
    return {"count": len(items), "items": items}


@router.get("/api/distributions/{dist}/properties", summary="分布性质（SymPy 推导）")
async def distribution_properties(
    dist: str,
    n: float | None = Query(default=None),
    p: float | None = Query(default=None),
    mu: float | None = Query(default=None),
    sigma: float | None = Query(default=None),
    lam: float | None = Query(default=None, alias="lambda"),
    a: float | None = None,
    b: float | None = None,
    alpha: float | None = None,
    beta: float | None = None,
) -> dict[str, Any]:
    if dist not in D.DISTRIBUTIONS:
        raise HTTPException(status_code=404, detail=f"不支持的分布：{dist}")
    raw = {
        k: v
        for k, v in {
            "n": n, "p": p, "mu": mu, "sigma": sigma,
            "lambda": lam, "a": a, "b": b, "alpha": alpha, "beta": beta,
        }.items()
        if v is not None
    }
    return D.properties(dist, raw)


@router.get("/api/distributions/{dist}/series", summary="分布绘图数据（PDF/CDF）")
async def distribution_series(
    dist: str,
    mode: str = Query(default="pdf", pattern="^(pdf|cdf)$"),
    points: int = Query(default=181, ge=21, le=601),
    n: float | None = None,
    p: float | None = None,
    mu: float | None = None,
    sigma: float | None = None,
    lam: float | None = Query(default=None, alias="lambda"),
    a: float | None = None,
    b: float | None = None,
    alpha: float | None = None,
    beta: float | None = None,
) -> dict[str, Any]:
    if dist not in D.DISTRIBUTIONS:
        raise HTTPException(status_code=404, detail=f"不支持的分布：{dist}")
    raw = {
        k: v
        for k, v in {
            "n": n, "p": p, "mu": mu, "sigma": sigma,
            "lambda": lam, "a": a, "b": b, "alpha": alpha, "beta": beta,
        }.items()
        if v is not None
    }
    return D.series(dist, raw, mode=mode, points=points)


@router.get("/api/animations/{animation_id}", summary="单个动画详情")
async def animation_detail(animation_id: str) -> dict[str, Any]:
    manifest = anim_tool.load_manifest()
    base = manifest.get("basePath", "/animations/_raw/")
    for item in anim_tool.all_animations():
        if item.get("id") == animation_id:
            return {**item, "url": f"{base}{item.get('file')}"}
    raise HTTPException(status_code=404, detail=f"未找到动画：{animation_id}")
