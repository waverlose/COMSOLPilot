<div align="center">

# COMSOLPilot

**Drive COMSOL Multiphysics with AI — through MCP.**
**用 MCP 让 AI 直接驱动 COMSOL 多物理场仿真。**

One MCP server + one-click launcher. 121 tools in two tiers. From geometry to
results — watch every step live in COMSOL Desktop.

一个 MCP 服务端 + 一键启动脚本，121 个工具，分两级。
从几何建模到结果后处理，每一步都在 COMSOL Desktop 里实时可见。

**New: the AI starts and configures COMSOL for you.** 启动与配置可以直接在对话里完成
——见 [docs/AI_SETUP_CN.md](docs/AI_SETUP_CN.md)。

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

Documentation search and verified troubleshooting notes are described in
[docs/REFERENCE_KNOWLEDGE_CN.md](docs/REFERENCE_KNOWLEDGE_CN.md).

| Feature 特性 | Description 说明 |
|---|---|
| 121 tools / 121 个工具 | geometry (blocks, cylinders, boolean ops), materials, physics (es/ec/ht/spf/solid), mesh, studies, results, plots, parametric sweeps 几何、材料、物理场、网格、求解、结果、绘图、参数扫描 |
| Two-tier surface / 两级工具面 | only `tools_catalog`, `tools_describe`, `tools_call` are visible; the other 117 are reached by name, so the tool list stays small 一级只暴露 3 个工具，其余按名字经 `tools_call` 调用，工具表保持精简 |
| GUI sync / 桌面同步 | AI works on the same server as your Desktop — watch live AI 与 Desktop 共用服务端，操作实时可见 |
| AI-driven setup / 对话式启动 | nothing auto-starts: ask the assistant to start COMSOL (`comsol_start_server`), pick version/port and register clients 不自动启动：由 AI 按需启动 COMSOL、选版本端口、注册客户端 |
| One-click launcher / 一键启动 | one-time env bootstrap, then a menu that only asks GUI or headless - everything else lives in `config.toml` 首次运行自动配环境；之后菜单只问 GUI/无头，其余全在 `config.toml` |
| Multi-client / 多客户端 | register into 9 MCP clients on demand — nothing is written without your explicit command 按需注册进 9 种 MCP 客户端，未经指令绝不写入任何配置 |
| Self-healing / 自愈 | connector detects a dead/restarted server and reconnects on its own 连接器自动识别服务端重启并重连 |

---

## Requirements / 环境要求

- Windows 10 1903+ (Windows Terminal recommended / 建议安装 Windows Terminal)
- COMSOL Multiphysics 6.x, any license that runs the server / 任何能启动服务端的许可证
- Python 3.10+ (only needed once, by the first-run bootstrap / 仅首次引导需要)
- An MCP-capable AI client / 任一支持 MCP 的 AI 客户端

---

## Quick Start / 快速开始

**One-time environment setup** (creates `.venv`, installs dependencies):
一次性准备环境（创建 `.venv` 并安装依赖）：

```bat
git clone https://github.com/waverlose/COMSOLPilot.git
cd comsolpilot
start_comsol_server.bat
```

`start_comsol_server.bat` on its first run builds `.venv` and installs the
dependencies (3-5 min, once). Equivalent manual command:
脚本首次运行会创建虚拟环境并装依赖（仅一次，3~5 分钟）；等价的手动命令：

```bat
python -m venv .venv && .venv\Scripts\python -m pip install -r requirements-windows.txt
```

> **Keep the project on an ASCII-only path.** JPype cannot load its native
> bridge from a path containing non-ASCII characters (e.g. Chinese), and COMSOL
> then fails to start with `Can't load library`. `comsol_environment` reports
> this as `venv_on_non_ascii_path`.
>
> **项目必须放在纯英文路径下**（例如 `D:\comsolpilot`），否则 JPype 原生库加载
> 失败、COMSOL 无法启动。

**Then start COMSOL once** and open your AI client. The server must come up
before the connector starts — and because it keeps running, that is a one-time
step.

**先起 COMSOL，再开客户端**（服务端必须先于连接器启动；它会一直运行，所以只需做一次）：

```bat
start_comsol_server.bat          :: 起服务端 + COMSOL Desktop（只需一次）
```

From then on every time you open your AI client the connector attaches by
itself. Stop it with `start_comsol_server.bat stop`, or ask the assistant to run
`comsol_stop_server`.

之后每次打开 AI 客户端都会自动接上。要停就 `start_comsol_server.bat stop`，或让 AI 调
`comsol_stop_server`。版本、端口、模式都在 `config.toml` 里改。
详见 **[docs/AI_SETUP_CN.md](docs/AI_SETUP_CN.md)**。

Prefer the menu? `start_comsol_server.bat` with no arguments asks GUI or headless. / 想用菜单就直接双击，它只问 GUI 还是无头。

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

## Configuration / 配置

One file configures this installation: **`config.toml`** at the project root.
The launcher script and the MCP connector both read it, so a change is made
once instead of in every client's config.

一个文件管全部：项目根目录的 **`config.toml`**。启动脚本和 MCP 连接器都读它。

```toml
[comsol]
port = 2036          # 服务端端口
mode = "gui"         # gui（Desktop 可围观）| headless
version = ""         # 固定版本，如 "6.2"；留空 = 最新
login_mode = "auto"  # auto | never | info | force
open_desktop = true

[connector]
autostart = false    # 连接器启动时是否自己拉起 COMSOL（默认否）
entry_name = "comsolpilot"   # 注册进客户端时的条目名

[ui]
spinner = "claude"   # 启动/停止时的动画：claude | plain | auto | off

```

Priority / 优先级: environment variable > `config.toml` > `workspace/settings.json` (runtime state).
The assistant can change these too, with `comsol_set_preferences` (it rewrites
`config.toml`, keeping your comments).

---

## Tool surface: two tiers / 工具分层

The server advertises just three tools, so the tool list stays small. Everything
else is reached by name through `tools_call` — with the same schemas, docs and
logging as before.

一级只暴露 3 个工具，其余全部按名字经 `tools_call` 调用，schema／文档／日志完全一致。

```text
tools_catalog()                                  # list everything, grouped
tools_catalog(query="thermal conduction")         # or search by keyword
tools_describe("geometry_add_block")              # inspect the input schema
tools_call("geometry_add_block", {"size": [0.1, 0.1, 0.1]})
```

Prefer the flat surface? Set `COMSOLPILOT_TOOL_TIER=flat`. Pin favourites to the
top level with `COMSOLPILOT_TOP_LEVEL_TOOLS=comsol_status,model_list`.
Details / 详见 **[docs/TOOL_TIERS_CN.md](docs/TOOL_TIERS_CN.md)**。

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

---

## Project layout / 目录结构

```
comsolpilot/
|-- src/                      MCP server, tools, telemetry 源码
|   +-- server.py             FastMCP server - 121 tools in 2 tiers, 5 prompts 服务端
|   +-- mcp_targets.py        multi-client config registry 多客户端配置注册表
|   +-- cli.py                doctor / onboard / config / demo 命令行工具
|   +-- tools/                session, admin (setup/config), gateway + catalog (tool surface), geometry, physics, mesh, study, results, telemetry
|-- scripts/                  server lifecycle, config reader, client sync 服务端生命周期、配置读取、客户端同步
|-- docs/                     guides (Chinese) 中文指南
|-- tests/                    pytest suite 测试
+-- workspace/                runtime artifacts (git-ignored) 运行时产物（不入库）
```

---

## Troubleshooting / 常见问题

| Problem 问题 | Fix 处理 |
|---|---|
| Client says "Not connected" / 客户端连不上 | Start the server **before** the connector, then re-trust it. The connector self-heals either way. 先启动服务端再信任连接器；连接器可自愈重连 |
| COMSOL will not start, `Can't load library` / COMSOL 起不来 | The project path contains non-ASCII characters. Move it to an ASCII path (e.g. `D:\comsolpilot`) and rebuild `.venv`. 项目路径含中文，移到纯英文路径并重建 `.venv`；用 `comsol_environment` 的 `venv_on_non_ascii_path` 自检 |
| AI should start / reconfigure COMSOL / 想让 AI 自己启动或改配置 | Ask it: `comsol_environment` → `comsol_set_preferences` → `comsol_start_server`. See [docs/AI_SETUP_CN.md](docs/AI_SETUP_CN.md). 直接让 AI 调用这几个工具即可 |
| "Server is in use by another client" / 服务端被占用 | Transient GUI-sync contention — the tools retry internally. 属 GUI 同步的瞬时争用，工具内部已自动重试 |
| Model prompts "save changes?" / 关模型提示保存 | Expected: the AI adds tables and parameters to the model. Save freely. 正常现象：AI 会在模型里添加表格和参数，保存即可 |
| Port 2036 busy / 端口被占 | Change `port` in `config.toml`, or set the `COMSOL_PORT` environment variable. 改 `config.toml` 里的 `port`，或设 `COMSOL_PORT` 环境变量 |
| git clone certificate error / clone 报证书吊销 | Corporate proxy blocks CRL fetch: `git -c http.schannelCheckRevoke=false clone ...`. 公司网络下拉不到吊销列表，临时关闭吊销检查 |
| Solve fails, "singular matrix" / 求解失败 | Look at `solve_error`. Most often a boundary condition's `where` matched nothing - check the selection or switch to a symbolic face. 先看 `solve_error`；多数是边界条件没选到面，检查 `where` 或改用符号化选面 |
| Result looks wrong / 结果数值可疑 | A field that overshoots the boundary values you imposed is not trustworthy - the solver flags it in `solve_error`. 超出所施加边界值的场不可信，求解器会在 `solve_error` 里标记 |
| Geometry feature missing (Sweep, Extrude, coil) / 缺少扫掠、拉伸等特征 | Not covered by a dedicated tool - use `model_execute_python` for raw COMSOL Java API. 用 `model_execute_python` 走原生 API |
| COMSOL not found / 找不到 COMSOL | Set `COMSOL_SERVER_EXE`, or let `comsol_environment` report what it can see. 设 `COMSOL_SERVER_EXE`，或先用 `comsol_environment` 看它发现了什么 |
| Model piling up in memory / 模型占内存 | `model_clear_all` unloads every model from the session. 用 `model_clear_all` 清空 |
| Tools missing in this chat / 本会话看不到新工具 | A conversation's tool list is frozen when created. Open a NEW conversation. 会话的工具清单在创建时定死，改完配置请开新对话验证 |

More guides / 更多指南:
[AI 启动与配置](docs/AI_SETUP_CN.md) ·
[两级工具面](docs/TOOL_TIERS_CN.md) ·
[客户端接入](docs/CONNECTORS_CN.md) ·
[建模约束](docs/MODELING_CONSTRAINTS_CN.md) ·
[手册检索与问题库](docs/REFERENCE_KNOWLEDGE_CN.md)

---

## License / 许可证

[MIT](LICENSE) — use it, fork it, ship it.
MIT 许可证——随便用，随便改，随便发布。

---

<div align="center">

**道阻且长，行则将至。**
*The road ahead is long — and walking it gets you there.*

</div>
