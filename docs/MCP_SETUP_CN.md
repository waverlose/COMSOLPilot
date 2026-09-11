# COMSOLPilot Windows 快速配置

新用户默认只使用一个入口：

```powershell
cd D:\comsolpilot
setup_windows.bat
```

脚本会在项目文件夹内创建：

```text
D:\comsolpilot\.venv
```

并生成一份适合复制修改的配置说明：

```text
D:\comsolpilot\workspace\config\config_example.md
```

同时生成结构化备份：

```text
D:\comsolpilot\workspace\config\config_example.json
```

## 默认配置

```text
COMSOL_HOST=localhost
COMSOL_PORT=2036
COMSOL_MODE=gui
```

默认使用 `gui`，不用 `auto`。`auto` 在找不到 `2036` 服务时可能启动后台会话，新用户不容易判断 COMSOL 运行在哪里。

## 只生成某个客户端配置

```bat
setup_windows.bat -Client opencode
setup_windows.bat -Client codex
setup_windows.bat -Client agy
```

## 配置写到哪里

脚本只打印建议配置，不自动修改用户已有配置文件。把输出复制到对应路径：

```text
opencode: C:\Users\<用户>\.config\opencode\opencode.json
Codex:    C:\Users\<用户>\.codex\config.toml
AGY 桌面: C:\Users\<用户>\.gemini\antigravity\mcp_config.json
AGY CLI:  C:\Users\<用户>\.gemini\config\mcp_config.json
```

三家配置说明也会统一保存到根目录：

```text
D:\comsolpilot\workspace\config\config_example.md
```

## run_mcp.bat 是什么

`run_mcp.bat` 不是给用户手动安装用的脚本。它是客户端配置里的 MCP 启动命令。

用户运行：

```text
setup_windows.bat
start_comsol_server.bat
```

opencode、Codex、AGY 后续自动调用：

```text
run_mcp.bat
```

## 启动或停止 COMSOL Server

默认配置下，MCP 使用固定端口 `2036`。让 AI 工作前，用户先启动 COMSOL Server：

```bat
start_comsol_server.bat
```

停止：

```bat
stop_comsol_server.bat
```

底层 PowerShell 脚本仍然可用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_comsol_server.ps1 -Port 2036
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_comsol_server.ps1 -Port 2036
```

如果 COMSOL 安装在非常规路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_comsol_server.ps1 -Port 2036 -ServerExe "E:\Comsol Multiphysics 6.2\COMSOL62\Multiphysics\bin\win64\comsolmphserver.exe"
```
