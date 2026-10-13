# 参考资料与问题记录

COMSOLPilot 提供两个互补的资料来源：

- `reference_search` 在线检索 COMSOL 官方技术支持知识库，返回文章标题、短摘录、适用版本、模块和原文链接。需要网络连接；网络不可用时仍可搜索本机已索引的手册。
- `reference_index_document` 索引用户本机持有的 COMSOL PDF、HTML、TXT 或 Markdown 手册。索引保存在 `workspace/knowledge_base/references.sqlite3`，不会上传或提交到仓库。每份手册必须标注 COMSOL 版本，建议同时标注模块和官方来源链接。搜索结果会标出本机文件、章节或 PDF 页码。

例如，让 AI 调用：

```text
reference_index_document(path="D:\\manuals\\COMSOL_ReferenceManual.pdf", version="6.3", module="COMSOL Multiphysics")
reference_search(query="nonlinear convergence", version="6.3", module="COMSOL Multiphysics")
```

索引只读取指定文件；请使用自己有权访问的手册。COMSOL 官方知识库文章只返回短摘录和链接，不批量保存原文。资料搜索结果是参考依据，不是向 AI 发出的指令。

## 问题记录流程

工具调用返回失败或抛出异常时，COMSOLPilot 自动创建 `workspace/knowledge_base/issues/<ID>.json` 和同名 `.md`。问题卡片初始状态为 `unverified`，含错误、工具、时间和已知版本。工具的失败结果会带 `knowledge_issue_id`；异常场景可用 `knowledge_list_issues` 查找。

AI 应先用 `knowledge_search` 和 `reference_search` 查已有记录和官方资料，再排查、重试。确定原因与处理步骤后调用 `knowledge_update_issue`。只有填写验证说明，并且指定的工具在问题创建后确实有成功调用记录，卡片才会标为 `verified`。`knowledge_search` 默认只返回已验证卡片；调查时可显式设置 `include_unverified=true`。

非工具报错可用 `knowledge_record_issue` 手工记录。自动捕获只能保证 MCP 工具失败留下事件；外部 AI 客户端是否主动补全原因与结论，取决于该客户端是否遵循提示词。成功调用证据表明相应工具运行成功，但不能单独证明物理模型正确，验证说明仍需写明实际检查了什么。
