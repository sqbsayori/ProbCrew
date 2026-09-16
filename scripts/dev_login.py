#!/usr/bin/env python
"""开发用登录助手 —— 让浏览器"先登进去"，不必等登录页做完。

为什么需要它
-----------
账号体系上线后，路由守卫会把未登录的访问一律挡在页面之外，
而登录页（`frontend/app/features/login/`）是另一个人的任务。
在他交付之前，四个页面组的人**没法在浏览器里看见自己写的页**，
这不合理 —— 工具不该让人互相等。

这个脚本只做一件事：调一次 `/api/auth/login`，把返回的令牌
翻译成**浏览器控制台可以直接粘贴的两行**。

它**不是后门**
-------------
- 它必须知道账号密码才能用（和直接用 curl 登录等价，不绕过任何校验）；
- 默认只允许连本机（`--allow-remote` 才连别的地址），避免有人拿它去连生产环境；
- 它不写任何文件，不缓存密码。

用法
----
    # 1) 启动后端（另开一个终端）
    .\\启动.bat            # 或 bash start.sh / scripts/dev.ps1

    # 2) 取令牌（密码可以交互输入，也可以用环境变量）
    python scripts/dev_login.py --username admin
    LIVE_TEST_PASSWORD=xxx python scripts/dev_login.py --username admin

    # 3) 把输出里的两行粘到浏览器控制台，然后刷新页面

想看学生视角就换 `--username <学生用户名>`（管理员能进所有页面，
学生进不了管理页 —— 用它来验证角色过滤正不正常）。
"""
from __future__ import annotations

from _console import utf8_output

utf8_output()

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200]
        raise SystemExit(f"✘ 登录失败（HTTP {exc.code}）：{detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"✘ 连不上后端：{exc.reason}\n  后端起了吗？") from exc


def main() -> int:
    ap = argparse.ArgumentParser(description="开发用：取一个令牌，并打印浏览器可直接粘贴的登录片段")
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="后端地址")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="", help="留空则读 LIVE_TEST_PASSWORD，再留空则交互输入")
    ap.add_argument("--allow-remote", action="store_true", help="允许连非本机地址（默认拒绝）")
    ap.add_argument("--landing", default="", help="顺带打印一个落地页深链接，例如 practice")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    host = base.split("//")[-1].split("/")[0].split(":")[0]
    if host not in LOCAL_HOSTS and not args.allow_remote:
        print(f"✘ 拒绝连接非本机地址 {base}")
        print("  这是开发工具，只该用在本地。确实要连远端请加 --allow-remote。")
        return 2

    password = args.password or os.environ.get("LIVE_TEST_PASSWORD", "")
    if not password:
        password = getpass.getpass(f"账号 {args.username} 的密码：")

    data = post_json(f"{base}/api/auth/login", {"username": args.username, "password": password})
    token, user = data["token"], data["user"]

    print()
    print("=" * 68)
    print(f"  已登录：{user['display_name'] or user['username']}（{user['role']}）")
    print("=" * 68)
    print("  把下面两行粘到**浏览器控制台**（F12 → Console），然后刷新页面：")
    print()
    print(f"  localStorage.setItem('probstat.token', {json.dumps(token)});")
    # ⚠️ 这里必须是**对象字面量**，不能再 json.dumps 一层：
    #    写成 JSON.stringify("{\"role\":...}") 存进去是字符串，
    #    前端 readCachedUser() 解出来拿不到 role，守卫会继续拦人（踩过）。
    print(f"  localStorage.setItem('probstat.user', JSON.stringify({json.dumps(user, ensure_ascii=False)}));")
    print()
    print("  退出：localStorage.removeItem('probstat.token'); localStorage.removeItem('probstat.user');")
    if args.landing:
        print(f"  落地页：{base}/#{'/' + args.landing.lstrip('/')}")
    print()
    print(f"  ⚠️ 令牌有效期 {int((data['expires_at'] - __import__('time').time()) // 3600)} 小时左右；")
    print("     只在本地开发用，别贴到群里、别用在共享机器上。")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
