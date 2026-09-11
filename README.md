<div align="center">

# COMSOLPilot

**Drive COMSOL Multiphysics with AI — through MCP.**
**用 MCP 让 AI 直接驱动 COMSOL 多物理场仿真。**

One MCP server + one-click launcher. 92 tools. From geometry to results —
watch every step live in COMSOL Desktop.

一个 MCP 服务端 + 一键启动脚本，92 个工具。
从几何建模到结果后处理，每一步都在 COMSOL Desktop 里实时可见。

`Windows` `COMSOL 6.x` `MCP` `Python 3.10+` `JPype / MPh`

</div>

---

## What is this? / 这是什么？

COMSOLPilot exposes COMSOL Multiphysics as an MCP server, so any MCP-capable
AI client (WorkBuddy, Claude Code, OpenCode, Codex, Cursor, ...) can build and
run simulations for you — while you watch in COMSOL Desktop.

COMSOLPilot 把 COMSOL Multiphysics 封装为 MCP 服务端，任何支持 MCP 的 AI
客户端（WorkBuddy、Claude Code、OpenCode、Codex、Cursor 等）都可以替你建模
求解——而你在 COMSOL Desktop 里全程围观。

**GUI-sync mode / GUI 同步模式**：the AI connects to the same COMSOL server
as your Desktop. Every geometry node, material, physics setting and result
appears in your model tree in real time. You are never out of the loop.

AI 与你的 Desktop 连接同一个服务端：AI 建的几何、材料、物理场、结果会实时
出现在你的模型树里，随时可以接手检查或手动修改。

---

## Features / 特性

| Feature 特性 | Description 说明 |
|---|---|
| 92 tools / 92 个工具 | geometry (blocks, cylinders, boolean ops), materials, physics (es/ec/ht/spf/solid), mesh, studies, results, plots, parametric sweeps 几何、材料、物理场、网格、求解、结果、绘图、参数扫描 |
| GUI sync / 桌面同步 | AI works on the same server as your Desktop — watch live AI 与 Desktop 共用服务端，操作实时可见 |
| One-click launcher / 一键启动 | first-run bootstrap (venv + deps), GUI/headless modes, custom port 首次运行自动配环境，GUI/无头模式，端口自定义 |
| Multi-client / 多客户端 | register into 9 MCP clients on demand — nothing is written without your explicit command 按需注册进 9 种 MCP 客户端，未经指令绝不写入任何配置 |
| Self-healing / 自愈 | connector detects a dead/restarted server and reconnects on its own 连接器自动识别服务端重启并重连 |
| Easter eggs / 彩蛋 | a binary signature in model parameters + a 15x58 digit-matrix screen in the results tables 参数表里的二进制电报 + 结果表格里的 15x58 点阵屏 |

---

## Requirements / 环境要求

- Windows 10 1903+ (Windows Terminal recommended / 建议安装 Windows Terminal)
- COMSOL Multiphysics 6.x, any license that runs the server / 任何能启动服务端的许可证
- Python 3.10+ (only needed once, by the first-run bootstrap / 仅首次引导需要)
- An MCP-capable AI client / 任一支持 MCP 的 AI 客户端

---

## Quick Start / 快速开始

```bat
git clone https://github.com/<you>/comsolpilot.git
cd comsolpilot
start_comsol_server.bat
```

The launcher does the rest / 启动脚本会完成剩下的所有事情：

1. creates `.venv` and installs dependencies (first run only, 3-5 min)
   首次运行自动创建虚拟环境并安装依赖（仅一次，3~5 分钟）
2. finds your COMSOL installation and starts a server on port 2036
   自动定位 COMSOL 并在 2036 端口启动服务端
3. opens COMSOL Desktop so you can watch (GUI mode)
   GUI 模式下自动打开 COMSOL Desktop
4. registers nothing without your say-so
   未经指令不写入任何客户端配置

Then connect your AI client — see the next section.
接下来把 AI 客户端接上——见下一节。

---

## Connect an AI client / 接入 AI 客户端

Nothing is written automatically. You choose the client, you run the command.

**不会自动写入任何客户端配置。** 你选客户端，你执行命令。

```bash
# a) print a paste-ready example / 打印示例，自己粘贴
python -m src.cli config --client workbuddy

# b) register into exactly one client / 只写入你点名的这一个
python scripts/sync_mcp_port.py --ensure --only workbuddy
```

Supported clients / 支持的客户端:
`workbuddy` `claude-code` `claude-desktop` `gemini` `cursor`
`windsurf` `opencode` `codex` `deepseek`

Full details, config paths and format examples / 完整说明（含各客户端配置路径与三种格式示例）:
**[docs/CONNECTORS_CN.md](docs/CONNECTORS_CN.md)**

After registering, trust/enable `comsolpilot` in the client's connector page — once.
注册后在客户端的连接器页面信任/启用一次即可。

---

## Try it / 试一试

Tell your AI / 对 AI 说：

> Build a 10x10x1 mm dielectric slab (eps_r = 4.5), 1 V on the bottom, ground
> on top, and compare the numerical capacitance with the parallel-plate formula.
>
> 建一个 10x10x1 mm 的介质板（相对介电常数 4.5），底面 1V、顶面接地，把数值
> 电容和平板电容公式对比一下。

Expect about 3.98438 pF from both — the finite element answer matches the
analytic formula to roughly eight decimal places.
数值与理论值都会是约 3.98438 pF，吻合到小数点后八位。

---

## The signature / 关于模型里的彩蛋

Two one-shot marks are written into the **current model** when the session
connects — static, written once, zero runtime cost:

会话连接后会在**当前模型**里写入两样一次性的印记——静态、写完即止、零开销：

1. **Parameters `B00`-`B30`** in the model parameters — the UTF-8 binary of a
   short motto (one byte per parameter, e.g. `B00 = 11100100`).
   参数表里的 `B00`-`B30`：一句签名的 UTF-8 二进制电报，一个参数一个字节。
2. **Table `COMSOLPilot Screen`** in the results — a 15 x 58 grid of 0/9 where
   the 9s draw the motto as a bitmap. A table is just a low-res screen.
   结果表格里的 15x58 矩阵：9 的笔画拼出点阵字。表格本身就是一块低分辨率屏幕。

Delete them anytime; they come back on the next connect. Customize the motto
in `src/tools/telemetry.py` (`_MESSAGE` / `_SCREEN_TEXT`).
随时可删，下次连接会重新写入。想改内容：`src/tools/telemetry.py` 里的 `_MESSAGE`
和 `_SCREEN_TEXT`。

---

## Project layout / 目录结构

```
comsolpilot/
|-- src/                      MCP server, tools, telemetry 源码
|   +-- server.py             FastMCP server - 92 tools, 5 prompts 服务端
|   +-- mcp_targets.py        multi-client config registry 多客户端配置注册表
|   +-- cli.py                doctor / onboard / config / demo 命令行工具
|   +-- tools/                session, geometry, physics, mesh, study, results, telemetry
|-- scripts/                  launcher, port sync, server lifecycle 启动与运维脚本
|-- docs/                     guides (Chinese) 中文指南
|-- tests/                    pytest suite 测试
+-- workspace/                runtime artifacts (git-ignored) 运行时产物（不入库）
```

---

## Troubleshooting / 常见问题

| Problem 问题 | Fix 处理 |
|---|---|
| Client says "Not connected" / 客户端连不上 | Start the server **before** the connector, then re-trust it. The connector self-heals either way. 先启动服务端再信任连接器；连接器可自愈重连 |
| Garbled banner glyphs / 字符乱码 | The launcher auto-switches to Windows Terminal. Install it from the Store if missing. 启动器会自动切到 Windows Terminal；没有就装一个 |
| "Server is in use by another client" / 服务端被占用 | Transient GUI-sync contention — the tools retry internally. 属 GUI 同步的瞬时争用，工具内部已自动重试 |
| Model prompts "save changes?" / 关模型提示保存 | Expected: the signature tables/params belong to the model. Save freely. 正常现象：签名印记属于模型的一部分，保存即可 |
| Port 2036 busy / 端口被占 | Menu option 3 (or `setport`) picks and syncs a new one. 菜单选 3 或 `setport` 换端口，自动同步客户端 |

More guides / 更多指南: [docs/MCP_SETUP_CN.md](docs/MCP_SETUP_CN.md) ·
[docs/TOOL_QUICKREF_CN.md](docs/TOOL_QUICKREF_CN.md) ·
[docs/MODELING_CONSTRAINTS_CN.md](docs/MODELING_CONSTRAINTS_CN.md)

---

## License / 许可证

[MIT](LICENSE) — use it, fork it, ship it.
MIT 许可证——随便用，随便改，随便发布。

---

<div align="center">

**道阻且长，行则将至。**
*The road ahead is long — and walking it gets you there.*

</div>
