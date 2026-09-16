"""pytest 全局夹具：**把测试数据与真实库隔开**。

为什么必须做
-----------
加了账号体系之后，测试会真的**建账号、写作答记录、写审计**。
不隔离的话，跑一次 `pytest` 就会往 `backend/data/learning.sqlite`
（老师的真实数据所在）里塞一堆 `t_*` 测试账号和作答记录 —— 测试污染真实数据，
是最容易发生又最难发现的一类事故。

做法：在**任何 app 模块被 import 之前**改掉 `DB_PATH`。
conftest.py 由 pytest 在收集测试之前加载，所以这个时机是可靠的。

注意：`test_deployment.py` 里有一条断言"默认库路径 = backend/data/learning.sqlite"，
它必须显式清掉环境变量才能验证默认值（见该测试）。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_PYTEST_DB = Path(tempfile.gettempdir()) / "probcrew_pytest.sqlite"

os.environ.setdefault("LLM_PROVIDER", "mock")
# bcrypt 强度调到最低档：整套测试要建几十个账号、登录上百次，
# 用生产档（12）光哈希就要好几分钟。强度写在哈希串里，校验不受影响。
os.environ.setdefault("AUTH_BCRYPT_ROUNDS", "4")
os.environ["DB_PATH"] = str(_PYTEST_DB)
# DB_URL 会覆盖 DB_PATH，留着它隔离就失效了
os.environ.pop("DB_URL", None)
