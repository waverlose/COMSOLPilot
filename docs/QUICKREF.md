# COMSOLPilot Quick Reference

## New User Flow / 新用户流程

1. Run setup / 运行安装配置:

```powershell
setup_windows.bat
```

2. Run diagnostics / 运行诊断:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose.py
```

3. For GUI mode, start COMSOL Server / GUI 模式先启动 COMSOL Server:

```powershell
start_comsol_server.bat
```

4. Configure the AI client with the generated guide / 按生成配置接入 AI 客户端:

```text
workspace/config/config_example.md
```

5. Ask the AI to check status first / 先让 AI 检查状态:

```text
Check COMSOLPilot status
```

## Runtime Paths / 运行路径

```text
workspace/models/          Generated .mph model files
workspace/exports/         Exported plots and result data
workspace/logs/            Runtime logs
workspace/config/          Generated client config examples
workspace/tmp/             Temporary files
workspace/cache/           Cache files
```

## Connection Defaults / 默认连接

```text
COMSOL_HOST=localhost
COMSOL_PORT=2036
COMSOL_MODE=gui
```

`run_mcp.bat` is for AI clients. Users normally run `setup_windows.bat`, then `start_comsol_server.bat` for GUI mode.

`run_mcp.bat` 给 AI 客户端调用。用户通常运行 `setup_windows.bat`，GUI 模式再运行 `start_comsol_server.bat`。

## Recommended Tool Order / 推荐工具顺序

For normal model creation, use the structured workflow:

正常建模优先使用结构化工作流：

```text
workflow_capabilities
workflow_validate_spec
workflow_execute_spec
```

Use low-level tools only for manual control or debugging:

低层工具用于手动控制或调试：

```text
comsol_status
comsol_connect
model_create
model_create_component
geometry_add_*
geometry_build
geometry_select_*_by_box
material_create_basic
physics_add
physics_boundary_named_selection
mesh_ensure
study_ensure
study_solve
results_create_standard_3d_plots
model_save_version
```

For advanced COMSOL geometry not covered by the structured workflow:

结构化工作流未覆盖的高级 COMSOL 几何：

```text
geometry_add_feature(properties={...}, selections={...})
model_execute_python(confirm="EXECUTE_COMSOL_PYTHON", script="...")
```

## Common Fixes / 常见处理

| Problem | Fix |
| --- | --- |
| COMSOL not visible | Run `start_comsol_server.bat`, then ask the AI to connect to `localhost:2036` |
| Port occupied | Run `stop_comsol_server.bat` |
| COMSOL not detected | Set `COMSOL_SERVER_EXE` in generated config |
| MCP startup JSON error | Keep all normal logs on stderr; use `run_mcp.bat` |
| Helical coil / Sweep / Extrude missing | Use `model_execute_python`; this is COMSOLPilot tool coverage, not an MCP protocol limit |
| Generated files in root | Move them to `workspace/` and update the script that created them |

## Verification / 验证

```powershell
.\.venv\Scripts\python.exe -m compileall src tests scripts
.\.venv\Scripts\python.exe -c "from src.server import register_all_tools, register_all_resources; register_all_tools(); register_all_resources(); print('registration_ok')"
```
