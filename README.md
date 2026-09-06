### 我解决的问题

用户在飞书中发送一句自然语言请求，机器人完成从意图识别、任务拆解、工具调用，到结果回传的完整闭环。例如：

- “帮我搜索本周 AI 行业新闻并整理成中文摘要”
- “把这份 CSV 转成格式规范的 Excel”
- “新用户进群触发机器人消息告知它看公告”


### 项目亮点

1. 消息入口统一：支持飞书长连接和 Webhook，业务逻辑与传输层解耦。
2. 异步可靠执行：消息先入 MySQL 任务队列，再由 worker 执行耗时的模型、搜索和文件操作。
3. 结果可验证：Excel 文件生成后自动检查工作表、维度、公式错误和文件大小，再回传飞书。
4. 可观测和可追踪：每个阶段记录 `job_id`、耗时、状态和异常堆栈，便于定位问题。
5. 要实现对应的能力只需要插入对应的skill，互不影响做到功能解耦
### 效果图
效果图展示.md(请查看)


## 2. 系统架构

```text
飞书长连接 / Webhook
          │
          ▼
   MessageApplication
          │ 解析、幂等、快速确认
          ▼
    MySQL Task Queue
          │
          ▼
       Worker
          │
          ├─ TaskParser：消息 → StructuredTask
          ├─ Intent Router：direct / tool + Skill
          ├─ Planner / DAG：已实现底层拓扑批次执行器，自动多步骤路由待完善
          ├─ Skill：search / excel /
          ├─ Tool Executor：调用外部 API 或本地文件能力
          └─ Result Processor：校验、总结、回传文本和文件
```

## 3. 一次请求如何执行

以“生成 Excel”为例：

1. 飞书事件进入 API 或 Bot，立即回复“已收到，正在处理”。
2. `TaskParser` 提取文本、发送人、消息 ID 和附件。
3. 意图路由选择 `excel` Skill，并由模型提取结构化参数。
4. Excel Executor 使用 `openpyxl` 创建或转换工作簿。
5. 程序重新打开文件，检查工作表、数据范围、公式错误和文件存在性。
6. 产物上传飞书，回复文本摘要和文件附件。

当前已识别的工具请求会优先走单步快速路径。`app/core/orchestrator/dag.py` 已实现无依赖步骤并发、有依赖步骤按拓扑批次执行，但当前路由器还没有稳定地把用户的复合请求识别成多步骤 Workflow，因此不能对外宣称“多步骤任务会自动启用 DAG”。搜索任务的研究循环已接入快速路径。

## 4. 代码入口

| 模块 | 
| --- | --- |
| `app/api/feishu_webhook.py` | Webhook 接入与快速响应 |
| `app/services/feishu_ws.py` | 飞书长连接事件接收 |
| `app/services/message_application.py` | 统一消息用例、确认和最终回复 |
| `app/core/parser/task_parser.py` | 消息解析、附件识别、路由兜底 |
| `app/core/orchestrator/agent.py` | Agent 主调度与轻重路径选择 |
| `app/core/orchestrator/dag.py` | 依赖分析和并发批次 |
| `app/services/task_queue.py` | MySQL 持久化队列、重试和死信 |
| `app/skills/excel/executor.py` | Excel 创建、转换和结果校验 |
| `app/services/timing.py` | 结构化阶段耗时日志 |


## 5. 启动与验证

在外层 `飞书` 目录的终端中只使用一种启动命令：

```powershell
.\start-feishu.cmd
```

首次运行前，在 `feishu-ai-agent` 目录安装依赖并创建 `.env`：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

启动脚本优先使用 `.venv`，不存在时自动使用系统 `python`。健康检查：

```text
http://127.0.0.1:9000/health
```

测试：

```powershell
pytest
```


