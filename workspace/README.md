# Workspace

This directory is reserved for runtime artifacts generated or consumed by COMSOL MCP Server.

本目录用于存放 COMSOL MCP Server 运行时生成或读取的文件。

```text
workspace/
├── models/             # Generated .mph model versions
├── exports/            # Exported plots, tables, and data
├── logs/               # Runtime logs
├── tmp/                # Temporary files
└── cache/              # Tool and test caches
```

Runtime artifacts in these subdirectories are ignored by Git. Source files, configuration examples, and documentation belong outside `workspace/`.
