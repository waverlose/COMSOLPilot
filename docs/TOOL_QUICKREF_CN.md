# COMSOLPilot 工具速查

> 合并自原 `comsolpilot`（简化开源版）的 `QUICKREF.txt`，并补齐本项目（`D:\comsol-mcp-server`）
> 的实际工具集与新增能力。

---

## 新用户流程

```powershell
setup_windows.bat            # 建 .venv 并打印客户端配置
start_comsol_server.bat      # 启动 COMSOL 服务端（默认 2036）
```

然后在 AI 客户端里确认连接器已「信任」，先让 AI 执行：

```
comsol_status
```

---

## 运行路径

```text
workspace\models\        生成的 .mph
workspace\exports\       导出的图与数据
workspace\reports\       生成的报告（results_generate_report）
workspace\logs\          运行日志；tool_calls.jsonl 记录每次工具调用
workspace\config\        生成的客户端配置示例
```

---

## 推荐工具顺序

**首选：结构化工作流**（一次调用完成建模仿真，并带进度通知）

```text
workflow_capabilities      # 查看可用的物理场 / 边界条件别名 / spec 结构
workflow_validate_spec     # 先校验 spec，不要直接开跑
workflow_execute_spec      # 执行：建模型→几何→材料→物理→网格→求解→输出
```

**低层工具**（精细控制或排错时）

```text
comsol_status
comsol_connect             # 可零参数调用
model_create
model_create_component
geometry_add_*
geometry_build
geometry_select_*_by_box   # 注意框余量，见 MODELING_CONSTRAINTS_CN.md
material_create_basic
physics_add
physics_boundary_named_selection
mesh_ensure
mesh_configure_global_size # 全局尺寸
mesh_add_local_size        # 局部加密
study_ensure
study_solve                # 长任务可用 study_solve_async + study_get_progress
results_create_standard_3d_plots
results_generate_report    # 导出 html/docx 报告
model_save_version
model_clear_all            # 清理会话、释放 JVM 内存
```

---

## 一个可直接跑的 spec（稳态导热，实测通过）

```json
{
  "model": {"name": "SteadyConduction", "dimension": 3, "component": "comp1", "geometry": "geom1"},
  "geometry": [
    {"type": "block", "tag": "blk1", "position": [0, 0, 0], "size": [0.1, 0.1, 0.1]}
  ],
  "materials": [
    {"tag": "mat1", "label": "Aluminum", "domains": "all",
     "properties": {"thermalconductivity": "205[W/(m*K)]",
                    "density": "2700[kg/m^3]",
                    "heatcapacity": "900[J/(kg*K)]"}}
  ],
  "physics": [
    {"type": "ht", "boundary_conditions": [
      {"tag": "temp_bottom", "type": "Temperature",
       "where": {"box": {"xmin": -1e-6, "xmax": 0.100001,
                         "ymin": -1e-6, "ymax": 0.100001,
                         "zmin": -1e-6, "zmax": 1e-6}},
       "properties": {"T0": "373.15[K]"}},
      {"tag": "temp_top", "type": "Temperature",
       "where": {"box": {"xmin": -1e-6, "xmax": 0.100001,
                         "ymin": -1e-6, "ymax": 0.100001,
                         "zmin": 0.099999, "zmax": 0.100001}},
       "properties": {"T0": "293.15[K]"}}
    ]}
  ],
  "mesh": {"tag": "mesh1", "size": 4, "run": true},
  "study": {"tag": "std1", "type": "Stationary"},
  "outputs": [
    {"name": "Tmax", "type": "max", "expression": "T", "unit": "K"},
    {"name": "Tmin", "type": "min", "expression": "T", "unit": "K"}
  ]
}
```

预期结果：`solved: true`、`Tmax = 373.15 K`、`Tmin = 293.15 K`、`solve_error: null`。
**如果 `solve_error` 非空，不要引用 outputs 里的数值。**

---

## 可复用模板（MCP Prompts）

客户端支持 Prompts 时会显示为斜杠命令 / 模板选择：

| 模板 | 用途 |
|---|---|
| `steady_heat_conduction` | 稳态导热，含解析校验值 |
| `structural_statics` | 结构静力学（含网格与奇异性提醒） |
| `parametric_sweep` | 参数扫描（含异步求解用法） |
| `debug_nonconvergence` | 不收敛排查清单 |
| `model_from_description` | 把自然语言描述转成校验过的 spec |

---

## 让 AI 的步骤显示在 COMSOL 里

每个工具调用都会自动写一行到 COMSOL Desktop 的进度/消息窗口：

```text
AI > workflow_execute_spec spec={...}
AI > geometry_build component_name=comp1
AI < geometry_build done (312 ms)
```

AI 还可以主动播报：

```
comsol_say(message="开始构建 0.1 m 铝立方体几何")
```

于是你**盯着 COMSOL 就能看到 AI 正在做什么**，不用来回看对话记录。
只读类的探查工具（`comsol_status`、各 `*_list`、`*_inspect`）不写日志，避免刷屏。

## 调用日志

每次工具调用都会追加一行到 `workspace\logs\tool_calls.jsonl`：

```json
{"ts":"2026-09-11T12:11:21+0800","tool":"geometry_build","status":"ok","duration_ms":312.4,"arguments":"component_name=comp1"}
```

排查"AI 到底跑了什么"时看这个文件。

---

## 常见处理

| 问题 | 处理 |
|---|---|
| COMSOL 看不到 | 跑 `start_comsol_server.bat`，再让 AI 连 `localhost:2036` |
| 端口被占 | 启动脚本会自动换端口并提示；同步设置 `COMSOL_PORT` |
| 求解不收敛 | 看 `solve_error`；优先查边界条件选择集是否为空 |
| 结果数值可疑 | 检查是否超出施加的边界值；本项目会自动标记 |
| 找不到 COMSOL | 设置 `COMSOL_SERVER_EXE` 或给 `-ServerExe` |
| 自定义脚本被拒 | `model_execute_python(confirm="EXECUTE_COMSOL_PYTHON")` |
| 生成的模型残留占内存 | `model_clear_all` |

---

## 自检

```powershell
.\.venv\Scripts\python.exe -m compileall src tests scripts
.\.venv\Scripts\python.exe scripts\diagnose.py
.\.venv\Scripts\python.exe -m pytest tests -q
```
