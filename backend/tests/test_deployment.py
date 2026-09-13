"""部署无关化的后端单测（任务 3 / docs/13 §2.3）。

守的是什么
----------
"一套代码、两种环境，靠配置切换，**不靠改源码**"（docs/13 §2）。
这条约定最容易在本地被破坏：为了图方便把 host/port/数据库路径写回代码，
本地全绿，直到部署那天才发现改不动。

这组测试把四件事变成红灯：
  1. `APP_HOST` / `APP_PORT` / `CORS_ORIGINS` / `DB_PATH` 能被配置覆盖；
  2. CORS 白名单收窄后，中间件真的只放行白名单；
  3. 数据库路径由配置决定，且**相对路径按仓库根解析**（不受启动目录影响）；
  4. `/api/health` 把数据库连通性与语料条数如实报出来（失败必须显式）。

运行：
    cd ProbCrew/backend
    python -m pytest tests -q
或：
    python tests/test_deployment.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PROVIDER", "mock")

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# 配置：默认值不变 + 可被覆盖
# --------------------------------------------------------------------------


def test_config_defaults_match_previous_local_behavior() -> None:
    """本地默认值必须与改造前**逐字一致**，否则"本地行为零变化"就是空话。"""
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.app_host == "127.0.0.1"
    assert s.app_port == 8000
    assert s.cors_origin_list == ["*"]
    assert s.resolved_db_path == ROOT / "backend" / "data" / "learning.sqlite"


def test_config_can_be_overridden_by_env() -> None:
    """部署时的差异（监听全网卡 / 换端口 / CORS 白名单 / 换库位置）全部走配置。"""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        app_host="0.0.0.0",
        app_port=9001,
        cors_origins="https://probstat.example.edu, https://a.example.edu/ ",
        db_path="backend/data/other.sqlite",
    )
    assert (s.app_host, s.app_port) == ("0.0.0.0", 9001)
    assert s.cors_origin_list == ["https://probstat.example.edu", "https://a.example.edu"]
    assert s.resolved_db_path == ROOT / "backend" / "data" / "other.sqlite"


def test_db_url_overrides_db_path(tmp_path: Path) -> None:
    from app.config import Settings

    s = Settings(_env_file=None, db_url=f"sqlite:///{tmp_path / 'x.sqlite'}")
    assert s.resolved_db_path == tmp_path / "x.sqlite"


def test_db_path_relative_is_resolved_against_repo_root() -> None:
    """相对库路径必须锚在仓库根 —— 否则从不同目录启动会写到两个不同的库里。"""
    from app.config import Settings

    s = Settings(_env_file=None, db_path="data/relative.sqlite")
    assert s.resolved_db_path.is_absolute()
    assert s.resolved_db_path == ROOT / "data" / "relative.sqlite"


def test_cors_origins_empty_falls_back_to_star() -> None:
    from app.config import Settings

    assert Settings(_env_file=None, cors_origins="  ,  ").cors_origin_list == ["*"]


# --------------------------------------------------------------------------
# CORS 中间件：白名单真的生效
# --------------------------------------------------------------------------


def _cors_for(origins: str, credentials: bool = False) -> tuple[list[str], bool]:
    """用给定 CORS 配置装配一个最小 app，取出中间件里生效的参数。"""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.config import Settings

    s = Settings(_env_file=None, cors_origins=origins, cors_allow_credentials=credentials)
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=s.cors_allow_credentials and "*" not in s.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return list(mw.kwargs["allow_origins"]), bool(mw.kwargs["allow_credentials"])
    raise AssertionError("CORS 中间件没装上")


def test_cors_default_is_star() -> None:
    origins, credentials = _cors_for("")
    assert origins == ["*"]
    assert credentials is False


def test_cors_whitelist_narrows() -> None:
    origins, _ = _cors_for("https://probstat.example.edu")
    assert origins == ["https://probstat.example.edu"]
    assert "*" not in origins


def test_cors_credentials_disabled_when_wildcard() -> None:
    """`*` + allow_credentials 是浏览器里的无效组合，不允许"看起来配了"。"""
    _, credentials = _cors_for("*", credentials=True)
    assert credentials is False
    _, credentials_ok = _cors_for("https://a.example.edu", credentials=True)
    assert credentials_ok is True


# --------------------------------------------------------------------------
# 健康检查：数据库连通性 + 语料条数
# --------------------------------------------------------------------------


def test_health_reports_database_and_corpus() -> None:
    from fastapi.testclient import TestClient

    from app.main import build_app

    client = TestClient(build_app())
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()

    assert body["status"] == "ok"
    # 语料条数（部署后 L1 教材换进来时，这个数字是"部署成功"的直接证据）
    assert body["knowledge_base"]["sections"] > 0
    assert body["knowledge_base"]["exists"] is True
    # 数据库连通性
    assert body["database"]["connected"] is True, body["database"]
    assert body["database"]["path"].endswith(".sqlite")
    # 部署参数可见（答辩/排障时一眼看出跑的是哪种环境）
    assert body["deployment"]["app_host"] == "127.0.0.1"
    assert body["deployment"]["cors_origins"] == ["*"]
    # 检索层状态：权重装没装、有没有降级，一眼可见
    assert body["retrieval"]["embedding"]["backend"]
    assert "available" in body["retrieval"]["embedding"]
    assert "available" in body["retrieval"]["reranker"]


def test_health_reflects_non_local_deployment(tmp_path: Path) -> None:
    """把配置换成"服务器环境"后，健康检查要跟着变 —— 证明读的是配置而不是常量。"""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import build_app

    app = build_app()
    app.state.settings = Settings(
        _env_file=None,
        app_host="0.0.0.0",
        app_port=9001,
        cors_origins="https://probstat.example.edu",
        db_path=str(tmp_path / "server.sqlite"),
    )
    body = TestClient(app).get("/api/health").json()

    assert body["deployment"] == {
        "app_host": "0.0.0.0",
        "app_port": 9001,
        "cors_origins": ["https://probstat.example.edu"],
    }
    assert body["database"]["path"] == str(tmp_path / "server.sqlite")


def test_health_reports_database_failure_explicitly(tmp_path: Path) -> None:
    """库连不上时必须**说出来**，不能装作一切正常（失败必须显式）。"""
    from app.api.system import _database_health

    bad = _database_health(tmp_path / "no" / "such" / "dir" / "x.sqlite")
    assert bad["connected"] is False
    assert bad["error"]


def test_health_lists_student_tables(tmp_path: Path) -> None:
    """L2 敏感表以 `student_` 前缀命名，便于机械判定（docs/13 §1.1 约束 2）。"""
    import sqlite3

    from app.api.system import _database_health

    db = tmp_path / "probe.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE student_answers (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE qa_log (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    info = _database_health(db)
    assert info["connected"] is True
    assert info["student_tables"] == ["student_answers"]


def test_learning_log_uses_configured_db_path(tmp_path: Path) -> None:
    """`DB_PATH` 换位置后，写入要跟着换 —— 这是"配置生效"的端到端证据。"""
    import asyncio

    from app.config import settings
    from app.tools import learning_log

    original = settings.db_path
    target = tmp_path / "learning-probe.sqlite"
    try:
        settings.db_path = str(target)
        assert learning_log._db_path() == target
        asyncio.run(
            learning_log.log_qa(ctx=None, session_id="deploy-test", query="测试配置生效", intent="knowledge")
        )
        assert target.exists(), "配置的库路径没有被真正使用"
    finally:
        settings.db_path = original


# --------------------------------------------------------------------------
# 手动运行入口（无 pytest 时）
# --------------------------------------------------------------------------


def _run_all() -> int:
    import inspect
    import tempfile
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in tests:
            try:
                params = inspect.signature(fn).parameters
                fn(Path(tmp)) if params else fn()
                print(f"  ✔ {name}")
            except Exception:  # noqa: BLE001
                failed += 1
                print(f"  ✘ {name}")
                traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
