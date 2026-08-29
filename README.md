# Feishu AI Agent

一个面向飞书消息入口的 AI Agent 骨架，包含消息解析、任务规划、Skill 注册与执行链路。

## 目录

```text
app/api/feishu_webhook.py          # 接收飞书消息
app/core/parser/task_parser.py     # 消息 -> 结构化任务
app/core/parser/schemas.py         # 数据结构
app/core/orchestrator/agent.py     # 总调度 Agent
app/core/orchestrator/planner.py   # 任务分析/规划
app/core/orchestrator/executor.py  # 调用 Skill
app/skills/registry.py             # Skill 注册中心
app/skills/base.py                 # Skill 统一接口
```

## 启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

飞书 webhook：

```text
POST /feishu/webhook
```

## 测试

```bash
pytest
```

## Environment

Create `.env` from `.env.example` and set:

```text
DASHSCOPE_API_KEY=...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TASK_PARSER_MODEL=qwen-plus
QWEN_AGENT_MODEL=qwen-plus
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
FEISHU_OWNER_OPEN_ID=...
```
