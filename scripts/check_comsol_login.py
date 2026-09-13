# -*- coding: utf-8 -*-
"""COMSOLPilot 连接自检：一条命令定位"连不上/认证失败/服务端消失"。

用法（在项目目录里）：
    .\\.venv\\Scripts\\python.exe scripts\\check_comsol_login.py

检查项：
  1. 端口 2036 是否在监听、服务端进程是否存活、启动时间与启动者；
  2. 登录凭据文件（%USERPROFILE%\\.comsol\\v62\\login.properties）是否存在、
     何时被写入、包含哪些用户；
  3. 用 mph 真实连接一次，报出服务端返回的原始错误；
  4. 根据结果给出可执行的下一步建议。
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import socket
import subprocess
import sys

HOST = os.environ.get("COMSOL_HOST", "localhost")
PORT = int(os.environ.get("COMSOL_PORT", "2036"))


def rule(title: str) -> None:
    print("\n" + "-" * 64)
    print(title)
    print("-" * 64)


def port_listening() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def comsol_processes() -> list[str]:
    out = []
    try:
        raw = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process comsolmphserver,comsol -ErrorAction SilentlyContinue | "
             "Select-Object Name,Id,StartTime | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=30)
        text = (raw.stdout or "").strip()
        if text:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                out.append(f"{item.get('Name')} PID={item.get('Id')} "
                           f"started={item.get('StartTime')}")
    except Exception as exc:
        out.append(f"(进程查询失败: {exc})")
    return out


def login_files() -> list[str]:
    home = pathlib.Path(os.environ.get("USERPROFILE") or pathlib.Path.home())
    found = []
    for version in ("v62", "v61", "v60"):
        path = home / ".comsol" / version / "login.properties"
        if path.is_file():
            stat = path.stat()
            users = []
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        users.append(line.split("=", 1)[0].strip())
            except Exception:
                pass
            found.append(
                f"{path}  written={datetime.datetime.fromtimestamp(stat.st_mtime):%Y-%m-%d %H:%M:%S}  "
                f"users={users or '(none)'}")
    return found


def try_connect() -> str | None:
    """None on success, otherwise the raw error text."""
    try:
        import mph
    except Exception as exc:
        return f"mph 未能导入: {exc}"
    try:
        client = mph.Client(host=HOST, port=PORT)
        names = client.names()
        print(f"        连接成功：COMSOL {client.version}，已加载模型 {names}")
        return None
    except Exception as exc:
        return str(exc)


def main() -> int:
    rule("1. 服务端")
    listening = port_listening()
    print(f"    端口 {HOST}:{PORT} " + ("在监听" if listening else "未监听"))
    procs = comsol_processes()
    for line in procs or ["(没有 comsolmphserver / comsol 进程)"]:
        print("    " + line)

    rule("2. 登录凭据")
    files = login_files()
    for line in files or ["(未找到 login.properties)"]:
        print("    " + line)

    rule("3. 实际连接测试")
    error = try_connect()

    rule("4. 结论与建议")
    if not listening:
        print("  ✗ 服务端没在运行。请【双击 start_comsol_server.bat → 选 1 (GUI mode)】")
        print("    注意：不要从脚本/工具里拉起服务端——那样的进程会随调用结束被回收，")
        print("    而且环境与你的交互会话不一致，会导致登录失败。")
        return 2
    if error is None:
        print("  ✓ 一切正常：服务端在跑，凭据可用，mph 能连上。")
        print("    现在可以重新连接/信任 WorkBuddy 里的 comsolpilot 连接器。")
        return 0
    print("  ✗ 服务端在跑但连接失败，原始错误：")
    print("      " + error.strip().replace("\n", "\n      "))
    if "No user name and password" in error:
        print("\n  含义：客户端拿不到可用凭据。最可能的原因（按概率）：")
        print("    1) 服务端是在非交互环境里启动的（脚本/工具拉起）——请用双击 bat 的方式重启；")
        print("    2) 服务端启动后登录库被改写（例如中途用另一个 COMSOL 用户登录过 Desktop）")
        print("       —— 重启服务端与 Desktop 使两侧凭据一致；")
        print("    3) COMSOL 版本不匹配：服务端与客户端必须同一版本（本机 6.2）。")
        print("\n  修复动作：关闭 Desktop → 双击 bat 选 1 → 等『COMSOL Server started』后")
        print("  在 Desktop 里 File > COMSOL Multiphysics Server > Connect to Server 登录一次。")
    elif "Server is in use" in error:
        print("\n  含义：服务端同一时刻只允许一个客户端操作——稍等几秒重试，或先结束另一个客户端。")
    else:
        print("\n  未识别的错误，请把上面的原始错误贴给 AI 一起看。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
