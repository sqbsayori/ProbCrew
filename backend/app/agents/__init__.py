"""Agent 包。

**新增 Agent 只需在本目录新建一个 .py 文件**，在里面声明：

    SPEC = AgentSpec(id="xxx", name="XXX Agent", role="generator", ...)
    async def run(state: AgentState, ctx: RunContext) -> AgentResult: ...

`kernel.registry.discover_agents()` 会在启动时自动发现它，
`kernel.graph.build_graph()` 会自动把它挂进并行 fan-out。
**不需要修改 __init__.py、不需要改 graph.py、不需要改路由表。**

以 `_` 开头的文件（如 `_router.py`）不会被当作 Agent。
"""
