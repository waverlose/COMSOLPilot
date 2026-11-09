# 按需启动与对话式配置

日常使用只需打开 AI 客户端并提出建模需求。无需先打开 bat，也无需在 COMSOL 启动后重连 MCP。
首次安装仍需准备依赖并注册连接器；已有用户升级后重启 MCP 服务一次即可。

## 启动流程

1. 客户端启动 MCP，立即完成连接。
2. 查看工具、查文档、校验方案时，不启动 COMSOL。
3. 首次建模自动启动独立工作进程，在自己的主线程初始化 JVM。
4. 已有 COMSOL 服务端会复用；后续工具在同一工作进程中执行。

默认读取 `config.toml` 中的模式、版本、主机和端口。GUI 模式按 `open_desktop` 设置打开 Desktop；
`mode="headless"` 使用无界面 JVM。初始化不会阻塞 MCP 握手，启动期间仍可查询状态。

## AI 如何处理启动状态

```text
tools_call("workflow_validate_spec", {"spec": {...}})
tools_call("workflow_execute_spec", {"spec": {...}, "solve": true})
# 首次请求可能返回 code="comsol_starting", executed=false
tools_call("comsol_status")
# 等到 state="ready" 后，重新调用原建模请求。
```

| state | 含义 | 下一步 |
|---|---|---|
| idle | 尚未启动 | 直接建模，自动启动 |
| starting | 正在准备环境或启动 COMSOL | 查看 stage、message、elapsed_seconds |
| ready | 已就绪 | 执行建模工具 |
| busy | 操作执行中 | 查询状态并等待完成 |
| failed | 启动或连接失败 | 查看 error，修正后调用 comsol_start_server |

- `code="comsol_starting"`：`executed=false`，请求没有执行或排队。等待 ready 后重试。
- `code="worker_busy"` 且 `executed=false`：该请求未执行，当前操作完成后可以重试。
- `code="operation_in_progress"`：操作已提交。不要重放；按 `request_id` 查询匹配的
  `last_operation.result`，读取最终结果。
- `outcome_unknown=true`：工作进程在操作期间断开，结果不明确。先检查模型，避免重复建模。

首次启动是正常状态，无需让用户手动运行 bat 或重连连接器。

## 对话式控制

| 工具 | 用途 |
|---|---|
| comsol_environment | 检查安装、依赖、端口与原生桥接路径 |
| comsol_set_preferences | 保存模式、版本、端口等配置 |
| comsol_start_server | 提前启动，或在失败后重建工作进程重试 |
| comsol_connect | 通过工作进程连接指定的现有服务端 |
| comsol_status | 查看启动进度、当前操作和最终结果 |
| comsol_stop_server | 停止工作进程与 COMSOL；下次建模自动启动 |
| comsol_disconnect | 断开会话并清除模型，保留原有清理语义 |
| comsol_open_desktop | 打开 Desktop 观察服务端模型 |
| comsol_configure_client | 按用户指定注册或刷新客户端 |

切换版本、端口前，先保存模型并停止现有会话，再启动新会话。客户端配置仍由用户明确指定；
`comsol_configure_client` 默认预览，`dry_run=false` 才写入。

## 提前启动与按需启动

默认 `[connector] autostart=false`，首次建模才启动。设为 `true` 后，
客户端加载 MCP 时在后台提前准备 COMSOL，仍不会让握手等待初始化。
旧版 `prewarm`、`prewarm_wait` 保留兼容；新版 MCP 不在自身进程内预热 JVM。

## 中文目录与日志

Windows 下自动将 JPype 原生库缓存到英文临时目录。项目与虚拟环境保持原位。
缓存按原生库内容区分；升级依赖后使用新的缓存，不覆盖正在加载的原生库。
检查 `comsol_environment` 的 `runtime.native_bridge` 和 `runtime.native_bridge_ready`。
临时目录不可写时，修正权限后调用 `comsol_start_server` 重试。

工作进程日志：`workspace/logs/worker.log`。实际工具调用日志仍在
`workspace/logs/tool_calls.jsonl`。

退出 MCP 只回收它拥有的工作进程，不主动清除共享服务端中的模型。
GUI 模式的独立服务端可以在下次连接时复用；headless JVM 随工作进程退出。

## bat 的用途

`start_comsol_server.bat` 保留用于首次环境准备、手动启停、升级和排障。
它不再是日常建模的必经入口。
