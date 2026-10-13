# 让 AI 自己启动与配置 COMSOL

本文说明升级后的**对话式启动流程**：不再需要先手动运行
`start_comsol_server.bat`，也不需要手动同步端口 / 版本 / 客户端配置——
把脚本做过的事都变成 MCP 工具，AI 在对话里就能完成。

---

## 一、为什么

升级前，用户必须按顺序做这些事：

1. 运行 `start_comsol_server.bat` 起 COMSOL 服务端；
2. 让 MCP 连接器在服务端**已经监听**之后再启动（否则预热失败）；
3. 改端口 / 换版本要进启动器菜单改 `config.toml`。

现在这些步骤全部变成 AI 可调用的工具，配置写进 `config.toml`，
由连接器下次启动时生效。

---

## 二、新增工具（环境与配置）

| 工具 | 作用 | 取代的旧东西 |
|---|---|---|
| `comsol_environment` | 报告 Python / 依赖 / COMSOL 安装 / 端口状态 / 已检测客户端 | `cli doctor` |
| `comsol_list_versions` | 列出本机 COMSOL 版本与对应 server/desktop 路径 | `config.toml` 的 `version` |
| `comsol_set_preferences` | 保存端口 / 版本 / 模式 / 登录模式 / 表格标签 | `config.toml`（AI 直接改它） |
| `comsol_configure_client` | 把连接器条目写入 / 刷新 MCP 客户端配置 | `sync_mcp_port.py` |
| `comsol_start_server` | 启动 COMSOL **服务端进程**（可选打开 Desktop），供连接器下次启动时接入 | `start_comsol_server.bat` |
| `comsol_stop_server` | 关闭 COMSOL 服务端并释放会话 | `start_comsol_server.bat stop`（菜单 [3]） |
| `comsol_open_desktop` | 打开 COMSOL Desktop 以观察正在运行的服务端 | 手动开 Desktop |

> **重要限制（务必了解）——"起服务端"和"AI 接入"是两件事**：
>
> - **起服务端**（拉起 `comsolmphserver.exe`）是普通的外部进程操作，**对话里完全能做**，
>   没有限制，`comsol_start_server` 就是干这个的。
> - **AI 接入服务端**（JVM + `ModelUtil.connect`）只能在 MCP 连接器**启动时**（事件循环
>   开始之前）建立；在对话中途（工具调用里）去做会**死锁**。这是 COMSOL/JPype 的底层
>   限制，实测确认。
>
> 两者不冲突，所以流程是：**服务端随时可起（对话里即可），连接器下次启动时自动接入**。
> 服务端一旦起来了就会一直运行（已做到连接器退出后仍存活），因此往后每次连接器启动
> 都会立刻接入，不需要再重连——直到你让它停。

---

## 三、典型对话

```text
你：看一下 COMSOL 环境
AI：comsol_environment()          # 报告版本、端口、依赖、客户端

你：用 6.2，端口 2040，GUI 模式
AI：comsol_set_preferences(port=2040, version="6.2", mode="gui")
    # 偏好写入 settings.json，连接器下次启动时生效

你：把连接器注册进 Claude Code
AI：comsol_configure_client(clients=["claude-code"], ensure=True, dry_run=True)
    comsol_configure_client(clients=["claude-code"], ensure=True, dry_run=False)

你：预先把服务端拉起来（可选）
AI：comsol_start_server(mode="gui", open_desktop=True)
    # 安全：只启动 comsolmphserver.exe 进程；返回 restart_required，
    # 提示重启连接器接入

你：停掉 COMSOL
AI：comsol_stop_server()
```

**日常其实只需一句**：打开 AI 客户端即可——连接器启动时自动拉起 COMSOL 并连上
（见下一节）。上面的 `comsol_start_server` 只在你想"先把服务端准备好"时才用。

`comsol_configure_client` 默认 **dry_run**，只报告将要修改的内容；
`ensure=True` 才会在缺失时新建条目，已有条目只会被刷新端口与环境变量。

---

## 四、启动顺序：先起服务端，再开客户端（推荐）

**顺序不能反。** COMSOL 的 Java 桥（JVM + 连接）只能在 MCP 连接器**启动时**、事件循环
开始之前建立。连接器已经在跑之后再去连，会**死锁**——实测：连接器已启动、COMSOL 已在
运行，工具里调 `comsol_connect` 卡死超过 100 秒。

所以推荐流程是：

```bat
start_comsol_server.bat          :: 起服务端 + COMSOL Desktop（只需一次）
```

然后打开（或重开）AI 客户端 —— 连接器启动时**自动接上**，对话里什么都不用做。

**关键点：COMSOL 服务端会一直运行**，连接器退出也不受影响（已做到）。所以这是
**一次性**动作：之后每次打开客户端都自动接入。

停止：

```bat
start_comsol_server.bat stop
```

或让 AI 调 `comsol_stop_server`。

### 如果连接器已经在跑、而 COMSOL 还没起

两条路，任选：

1. **重连连接器**：Claude Code 里 `/mcp` → 选 `comsolpilot` → Reconnect；（新开一个对话
   也一样）。重连时若 COMSOL 已在运行，就会自动接上。
2. 先跑 `start_comsol_server.bat`，再重开客户端。

工具 `comsol_start_server` 也能把服务端拉起来（只是启动进程，安全），但**救不了当前这个
已经在跑的连接器**——返回里会明确给出 `restart_required` 和下一步。

### 想反过来：打开客户端就自动起 COMSOL

在 `config.toml` 里把

```toml
[connector]
autostart = true
```

改成 true 即可（或 `comsol_set_preferences(autostart=True)`）。代价是"打开客户端"就等于
"启动 COMSOL"。

---

## 五、环境要求（重要）

**项目目录与其 `.venv` 必须位于纯 ASCII 路径下。**

路径含中文（例如 `C:\Users\你\Desktop\我的项目\...`）时，JPype 的原生桥接库
无法加载，报错形如：

```text
java.lang.UnsatisfiedLinkError: Can't load library: C:\Users\...\comsolmcp
```

自检方法：调用 `comsol_environment()`，看 `runtime.venv_on_non_ascii_path`
是否为 `false`。若为 `true`，把项目移动到例如 `D:\comsolpilot` 这类纯英文路径，
重建 `.venv` 即可。

---

## 六、与旧脚本的关系

`start_comsol_server.bat`、`scripts/sync_mcp_port.py`、`scripts/set_port.py`
以及 `scripts/start_comsol_server.ps1` **都保留**，功能与新工具一致，仍可继续使用。
如果你更习惯双击脚本，行为不变；如果你希望全程对话驱动，可以完全不用它们。

---

## 七、升级

代码就是检出目录里的源码（连接器按 `python -m src.server` 直接跑它），所以升级
等于一次 `git pull`：

```bat
start_comsol_server.bat upgrade
```

菜单 `[7]` 是同一件事。它只做快进：

- 本地改动若会被这次升级覆盖，**在动手之前**就拦下来并列出文件名，绝不合并、绝不丢弃；
- 本地改动若不冲突（例如你改过 `config.toml`），照常升级，改动保留；
- 落后远端较多时先列出新提交再升，升完告诉你升级前后各是哪个提交；
- 依赖文件有变动时自动补装；
- 不是 git 检出（解压安装的）会直接说明，并提示改用 `git clone` 安装。

升完**重开 AI 客户端**才生效——正在跑的那个服务端/连接器进程用的还是旧代码。
