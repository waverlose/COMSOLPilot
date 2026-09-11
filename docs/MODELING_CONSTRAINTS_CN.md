# COMSOLPilot 建模约束参考

> 来源：原 `comsolpilot`（简化开源版）的 `SKILL.md`，已按本机 **COMSOL 6.2（中文界面）**
> 的实测结果逐条校正。带 ✅ 的条目是实测验证过的，带 ⚠️ 的是踩过坑的。

---

## 1. 每个任务的开场

```
comsol_status          # 连接由连接器启动时预热，通常已 connected
workflow_capabilities  # 确认可用的物理场与边界条件别名
```

`comsol_connect` 现在可以零参数调用，端口取自 `COMSOL_PORT`（默认 2036）。

---

## 2. 推荐：结构化工作流

```
workflow_capabilities
workflow_validate_spec
workflow_execute_spec
```

低层工具只在需要精细控制或排错时使用。

---

## 3. 关键约束

### ⚠️ 边界条件类型必须用别名，不要猜 feature id

COMSOL 的真实 feature id 不是直觉写法：

| 你想设的 | 直觉写法 | 真实 feature id |
|---|---|---|
| 固定温度 | `Temperature` | **`TemperatureBoundary`** ✅ 实测 |
| 热流 | `HeatFlux` | `HeatFluxBoundary` |
| 对流换热 | `ConvectiveHeatFlux` | `HeatFluxBoundary` + `HeatFluxType=ConvectiveHeatFlux` |

`workflow_execute_spec` 的 `type` 字段接受**别名**（`Temperature` / `HeatFlux` /
`ConvectiveHeatFlux` / `Fixed` / `Roller` / `Ground` / `ElectricPotential`），
服务端会映射成真实 feature id。
直接 `physics.create()` 时必须自己写真实 feature id，写错会报
`Unknown feature ID X#Temperature`。

### ⚠️ 框选边界：`condition='inside'` 有 ~1e-8 的绝对容差

**这是实测出来的，非常容易踩。** 用坐标框选面时，如果框恰好贴在面上
（例如 `zmin=-1e-9, zmax=1e-9`），COMSOL 会判定"不在内部"，返回**空集**：

| 外扩量 | 选中结果（0.1 m 立方体，选 z=0 底面） |
|---|---|
| 1e-9 | `[]` ← 空 |
| 1e-8 及以上 | `[3]` ✅ |

本项目已修复：`_box_selection` 会按 `(0, 1e-8, 1e-6, 1e-4, 1e-3)` 自动外扩重试，
外扩量用 `min(margin, 0.01×span)` 封顶以免误吞相邻面；**全部落空会直接报错**。
所以：

- 框给的余量**尽量大一点**（例如目标面在 z=0，就写 `zmin=-1e-6, zmax=1e-6`）。
- 已经知道面编号时，优先 `"where": {"boundaries": [3]}`，完全确定。
- 不要用 `condition='intersects'` 兜底：它按包围盒相交判断，会多选相邻面。

### ⚠️ 中文版 COMSOL 的块体面编号不固定

实测：0.1 m 立方体（`blk1`，`base=corner`，位置 [0,0,0]）的**底面是 3、顶面是 4**，
不是直觉的 1 和 2。所以**不要硬编码面编号**，用坐标框选或先探测。

### 材料属性值必须用列表包装

```python
# 正确
material.propertyGroup('def').set('thermalconductivity', ['205[W/(m*K)]'])
# 错误 —— 可能被解析为 0，导致矩阵奇异
material.propertyGroup('def').set('thermalconductivity', '205[W/(m*K)]')
```

### 局部网格加密必须建在网格序列下

不要在根节点加全局 Size；把 Size 节点建在网格序列里（`mesh.feature().create(tag, "Size")`），
否则加密不生效。

### 后处理（COMSOL 6.x）

- 点评估类型是 `EvalPoint`，不是 `PointEvaluation`。
- 导出图片**不要**用 `size='manual'`（本机允许值是
  `current` / `manualweb` / `manualprint` / `presentation`）。
- `MaxMinVolume` / `MaxMinSurface` 和 `dataset().create(tag,"Boundary")` 在本机都报
  `Operation cannot be created in this context`，**不要用**；要极值就用
  `model.evaluate()` + numpy（本项目 `workflow_execute_spec` 的 outputs 就是这么做的）。

### 连接

- 默认固定端口 2036。服务端用 `start_comsol_server.bat` 启动。
- ⚠️ 2036 可能被其它进程当**临时源端口**占用（Windows 常见）。此时 COMSOL 会静默
  退到下一个端口。本项目已修复：启动脚本会先检查端口**能否 bind**，不能则自动选下一个
  空闲端口并明确告知；等待期间也会从 COMSOL 自己的日志里解析真实端口。
  **换端口后记得同步设置 `COMSOL_PORT`。**
- mph 是单进程限制：连接异常时先 `Get-Process python | Stop-Process -Force` 再重试。
- ⚠️ JVM 握手**只能在 MCP 服务启动时完成**（本项目在 `mcp.run()` 之前预热）。
  如果连接器启动时 COMSOL 还没起来，`comsol_connect` 会明确报错并让你重启连接器，
  而不会静默挂死。

---

## 4. 错误 → 处理

| 现象 | 原因 | 处理 |
|---|---|---|
| `Unknown feature ID X#Temperature` | 用了直觉 feature id | 用别名，或写 `TemperatureBoundary` |
| 边界条件 `selection=[]` / 求解不收敛 | 框选没选中任何面 | 加大框余量，或改用显式 `boundaries` |
| 解场极值超出边界给定值 | 非收敛解 / 选择集有问题 | 本项目会在 `solve_error` 里报出来；别直接引用数值 |
| 矩阵奇异 / 解为 NaN | 材料属性没包装成列表 | 所有属性值用 `[...]` |
| `Operation cannot be created in this context` | 用了个不受支持的 API 类型 | 换 `model.evaluate()` 路线 |
| 网格加密不生效 | Size 建在根节点 | 建在网格序列下 |
| 连接被拒绝 | 端口不对 / 进程锁 | 确认端口，杀残留 python 重试 |
| 自定义脚本被拒 | 需要显式确认 | `model_execute_python(confirm="EXECUTE_COMSOL_PYTHON")` |

---

## 5. 铁律：求解后必须校验

求解"成功"不等于结果可信。**本项目已经内置两道防线**：

1. 求解前 `preflight`：任何边界条件的选择集为空 → 立刻报错。
2. 求解后校验：解场极值若超出施加的边界值 → 自动降一级网格重解，仍越界则写进
   `solve_error` 并标记不可信。

作为使用者：**`solve_error` 非空时不要引用 outputs 里的数值**，
把它当作"这次没算出来"如实汇报，而不是把数字端上去。
