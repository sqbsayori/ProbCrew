"""API 路由包。

**新增 API 模块不需要改 main.py**：本目录下每个 `*.py` 只要导出
`router: APIRouter`，就会被 `main.py` 自动 include。
这与 Agent/Tool 的自动发现机制一致 —— 目的是让 5 个人并行开发零冲突。
"""
