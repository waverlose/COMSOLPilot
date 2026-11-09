# 工具分层（两级工具面）

COMSOLPilot 现在有一百多个工具。如果全部平铺到一级，客户端每次对话都要加载整张
工具表，既占上下文又难扫。现在默认把工具面折叠成**两层**。

---

## 一、结构

**一级（始终可见，只有 3 个）**

| 工具 | 作用 |
|---|---|
| `tools_catalog` | 列出/搜索全部工具（按领域分组，或按关键字检索） |
| `tools_describe` | 查看某个工具的完整输入 schema |
| `tools_call` | 按名字调用任意工具 |

**二级（其余全部工具，按名字经 `tools_call` 调用）**

几何、材料、物理场、网格、求解、结果、参数扫描、工作流、环境与配置……
一个都没少，schema、文档串、可观测性日志全部与平铺时一致。

---

## 二、典型用法

```text
tools_catalog()                                   # 看全部（分组）
tools_catalog(query="thermal conduction")         # 按英文关键字找
tools_catalog(query="热流")                        # 中文关键字也能找
tools_catalog(query="圆柱")                        # 查找圆柱几何工具
tools_catalog(category="几何")                     # 按中文分组筛选
tools_catalog(category="物理场", query="热传导")    # 分类与关键字组合
tools_catalog(category="geometry")                # 保留英文筛选方式
tools_describe("geometry_add_block")              # 看参数
tools_call("geometry_add_block", {"size": [0.1, 0.1, 0.1], "position": [0, 0, 0]})
```

端到端建模示例：

```text
tools_call("workflow_capabilities")
tools_call("workflow_validate_spec", {"spec": {...}})
tools_call("workflow_execute_spec", {"spec": {...}, "solve": true})
```

搜索支持常用中文术语（如“长方体”“圆柱”“热传导”“热流”“边界条件”）及中英文混合关键字。
多个关键字用空格分隔，必须全部匹配；中文分类使用目录返回的分组名，如“几何”“物理场”“研究与求解”。

参数写错时，网关会在执行前检查，并返回可用于修正的结构化信息：

- 工具名错误：返回 `did_you_mean` 候选工具名。
- 参数名错误或缺少必填项：同时返回 `unknown_parameters`、`missing_parameters`、
  `valid_parameters` 和拼写建议 `parameter_suggestions`。
- 参数类型错误：返回 `code="invalid_arguments"` 和 `validation_errors`，
  指明参数路径、错误原因和错误类型。例如 `size.1` 表示 `size` 数组的第二项。

参数类型检查与 FastMCP 直接调用使用相同的验证模型：可解析的数字字符串会转为数字，
JSON 数组或对象字符串会按目标参数类型解析。无法通过检查时不会执行目标工具；按 `hint`
查看 `tools_describe` 后修正参数即可。

---

## 三、切换与微调

| 环境变量 | 作用 |
|---|---|
| `COMSOLPILOT_TOOL_TIER=gateway` | 默认：两级 |
| `COMSOLPILOT_TOOL_TIER=flat` | 回到旧的平铺（全部一级可见） |
| `COMSOLPILOT_TOP_LEVEL_TOOLS=comsol_status,model_list` | 在两级模式下，额外把若干工具固定在一级 |

把它们写进 MCP 客户端配置的 `env` 即可。

---

## 四、兼容性

- **可观测性不变**：`tools_call` 内部调用的是同一批已包装函数，COMSOL 消息日志与
  `workspace/logs/tool_calls.jsonl` 记录的仍是**被调用的那个工具名**，不是
  `tools_call`。
- **提示词模板**已在开头说明两级访问方式，`/steady_heat_conduction` 等模板开箱即用。
- 命令行 `python -m src.cli tools` 仍列出全部工具（含被折叠的）。
