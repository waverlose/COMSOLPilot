# COMSOLPilot 使用说明

> COMSOLPilot = COMSOL Server + MCP 连接器 + 一键启动脚本。
> AI 通过它直接在 COMSOL 里建模、求解、读结果；你在 COMSOL Desktop 里同步观看。

---

## 一、一键启动

双击 `start_comsol_server.bat` 即可。首次运行会自动完成：

1. 检测不到 `.venv` 时：自动寻找 Python → 创建虚拟环境 → 安装依赖（一次性 3~5 分钟）；
2. 自动发现 COMSOL 安装路径（显式参数 → 环境变量 → mph 库 → C/D/E 盘扫描，成功后缓存）；
3. 无参数启动时自动切换到 Windows Terminal（老式控制台的字体渲染不出点阵界面）。

菜单：

```
[1] GUI 模式        服务端 + COMSOL Desktop（同步观察求解过程）
[2] 无头模式        只起服务端
[3] 端口设置        当前端口显示在菜单上，改完自动同步到所有已注册客户端
[0] 退出
```

命令行直达（无菜单、不暂停）：

```
start_comsol_server.bat gui | headless | status | stop | setport 2040
```

环境变量覆盖：`COMSOL_PORT`、`COMSOL_SERVER_EXE`、`COMSOL_DESKTOP_EXE`。

---

## 二、客户端注册（MCP 接入）

**原则：启动脚本绝不自动写入任何客户端配置。** 注册哪个客户端、什么时候注册，由你决定。

### 注册方式（二选一）

```bash
# a) 打印示例，自己复制粘贴到对应配置文件
python -m src.cli config --client workbuddy

# b) 让脚本写入你点名的这一个客户端
python scripts/sync_mcp_port.py --ensure --only workbuddy
```

客户端名字：`workbuddy` `claude-code` `claude-desktop` `gemini` `cursor` `windsurf` `opencode` `codex` `deepseek`

### 客户端配置文件位置

| 客户端 | 配置文件 | 格式 |
|---|---|---|
| WorkBuddy | `~/.workbuddy/mcp.json` | JSON mcpServers |
| Claude Code | `~/.claude.json` | JSON mcpServers |
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` | JSON mcpServers |
| Gemini CLI | `~/.gemini/settings.json` | JSON mcpServers |
| Cursor | `~/.cursor/mcp.json` | JSON mcpServers |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | JSON mcpServers |
| OpenCode | `~/.config/opencode/opencode.json` | 专有 schema（脚本已适配） |
| Codex | `~/.codex/config.toml` | TOML [mcp_servers.*] |
| DeepSeek | （实验性支持） | JSON mcpServers |

注册后到该客户端的连接器/插件页面把 `comsolpilot` 设为**信任/启用**一次，之后无需再动。

---

## 三、端口管理

| 文件 | 作用 |
|---|---|
| `workspace/runtime.json` | 最近一次启动的真实端口（自动生成） |
| `workspace/settings.json` | 菜单里设置的偏好端口 |

- 端口优先级：环境变量 `COMSOL_PORT` > `settings.json` > 默认 2036；
- 服务端启动后，脚本把**已注册客户端**的 `COMSOL_PORT` 同步为当前端口（只改已有条目，从不新建）；
- 换端口后需重启服务端，并在客户端里重新信任/重启一次连接器。

---

## 四、存在感特性（写进模型里的一次性印记）

 AI 接入后会在**当前模型**里留下两样一次性的东西，写完即止，无任何周期性刷新（不会卡）：

1. **二进制电报**：参数表里出现 `B00` ~ `B30`，值为 UTF-8 二进制串，内容是一句签名；
2. **点阵屏**：结果表格里出现 `COMSOLPilot Screen` 表，15 行 × 58 列 0/9 矩阵，9 组成的笔画就是"道阻且长"四个字的点阵字。

想换屏幕文字：改 `src/tools/telemetry.py` 里的生成脚本重跑即可。删除这些印记不影响任何功能。

---

## 五、常见问题

| 现象 | 原因与处理 |
|---|---|
| 客户端连不上 / 报 Not connected | 服务端必须**先于**连接器启动。先跑 bat，再到客户端重新信任/重启连接器。修复版连接器支持自愈，顺序错了也能直接重连 |
| 双击 bat 闪退或字符乱 | bat 会自动切到 Windows Terminal；确认系统里装有 Windows Terminal（Store 版即可） |
| 换了端口但客户端没跟上 | 确认跑过 `setport`（它会同步所有已注册客户端）；再重新信任一次连接器 |
| 表格里出现 4 位小数 | COMSOL 表格显示格式固定，不可配置。需要整数显示时用参数（Parameters）承载，参数值原样显示 |
| 模型关闭时提示"是否保存" | 正常现象：签名表/参数属于模型的一部分，保存即可，随 `.mph` 一起留存 |

### 新用户踩坑清单（前人踩过的 12 个坑）

以下是早期用户真实踩过的坑。标 **[已内置]** 的由脚本自动防御，标 **[需知晓]** 的请记在心里。

**安装阶段**

1. **[需知晓]** `git clone` 报证书吊销 `CRYPT_E_REVOCATION_OFFLINE`：公司网络/代理拉不到吊销列表。修法：`git -c http.schannelCheckRevoke=false clone ...`
2. **[已内置]** pip 自我更新被打断、目录残留 `~ip`：某些命令 shim 会打断 pip 改名。启动脚本已移除 pip 自升级步骤。
3. **[已内置]** pip 缓存写入被 shim 拦截报错：所有 pip 调用已加 `--no-cache-dir`。
4. **[需知晓]** Git Bash 里 `/d/xxx` 形式路径被创建到 `C:\d\xxx`：MSYS 路径转换偶发失效。路径一律写 `D:/xxx` 正斜杠盘符形式。

**配置阶段**

5. **[已内置]** 连接器注册成功但一个工具都没有（空壳）：多数客户端忽略 `cwd`，进程在错误目录启动、`ModuleNotFoundError: No module named 'src'` 秒退。生成的条目已全部带 `PYTHONPATH`。
6. **[已内置]** 服务端启动即 `KeyError: 'APPDATA'`：mph 在 import 阶段硬读 Windows 环境变量。生成的条目已带 `APPDATA / LOCALAPPDATA / USERPROFILE / PROCESSOR_ARCHITECTURE`。
7. **[已内置]** 换端口时条目被重复添加：脚本现按"名称或内容含 comsol"识别条目，改名（如改成 `comsol`）也能识别更新。
8. **[已内置]** 中文输出在 stdio 通道乱码：Windows 默认 GBK。生成的条目已带 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8`。

**启动阶段**

9. **[已内置]** 双击 bat 闪退：路径探测失败不抛窗、失败分支均有暂停与提示；探测本身有四层兜底 + 缓存。
10. **[需知晓]** 服务端起来后过一会儿自己消失：服务端必须由**用户双击 bat** 这类常驻入口拉起，不要从脚本工具调用的进程树里启动（调用结束会被连带清理）。

**会话阶段（最容易浪费时间）**

11. **[需知晓]** 改完配置、点了信任，**当前对话**还是看不到 `comsol_*` 工具：会话的工具清单在创建那一刻就定死了，改配置/信任/重启应用都不会让旧会话重算。
12. **[需知晓]** 验证配置是否生效：**开一个新对话**。在旧会话里反复重试是纯浪费时间。
