# 内容安全 MVP 实施指南

本文记录内容安全项目第一阶段的实施原则和步骤。

MVP 阶段不要一上来做“大而全内容安全平台”，而是按主链路优先来做：先把一条内容从输入到最终审核结果跑通，再逐步补后台、评测、审计和策略管理。

## 一、技术栈定型

技术栈优先沿用现有项目里已经在使用的组合，而不是为内容安全项目重新发明一套。

版本依据主要来自：

- `ai-engineering-lab/pyproject.toml` 和 `uv.lock`：Python、FastAPI、LangChain、LangGraph、checkpoint、OpenAI/Ollama 相关版本；
- `ascc/apps/api/pyproject.toml`：API 服务、SQLAlchemy、Alembic、Postgres 访问方式；
- `ascc/apps/web/package.json`：轻量前端项目的 Vue、Vite、Naive UI 组合；
- `ascc/infra/docker/docker-compose.yml`：PostgreSQL 16、Redis 7 的基础设施版本。

### 1. 后端技术栈

MVP 后端使用 Python + FastAPI。

| 类型 | 选型 | 版本 | 说明 |
|---|---|---:|---|
| Python | Python | `3.13` | 现有 Python 项目统一使用 `requires-python >=3.13` |
| 包管理 | uv | 项目默认 | 延续现有 Python 项目管理方式 |
| Web 框架 | FastAPI | `0.137.0` | `ai-engineering-lab/uv.lock` 已解析版本 |
| ASGI Server | Uvicorn | `0.48.0` | 使用 `uvicorn[standard]` |
| 数据模型 | Pydantic | `2.13.4` | 请求、响应、Agent 结构化输出都用它 |
| 配置管理 | pydantic-settings | `2.14.1` | 管理数据库、模型、服务配置 |
| ORM | SQLAlchemy | `2.0.50` | 后续审计日志和人工审核记录入库 |
| 数据库驱动 | psycopg | `3.3.4` | 使用 `psycopg[binary,pool]` |
| 数据库迁移 | Alembic | `>=1.16.0` | 沿用 `ascc-api` 的迁移工具 |
| 测试 | pytest | `>=8.3.0` | 先覆盖 Workflow 和 API 主链路 |
| 代码检查 | Ruff | `>=0.11.0` | 延续 `ascc-api` 的开发依赖 |

后端第一版不要拆成多个服务。先做一个 FastAPI 应用，内部包含 API、Workflow、Agent、人工审核恢复和审计日志。

### 2. AI / Agent 技术栈

AI 层使用 LangGraph 作为主编排框架，LangChain 作为模型和工具抽象层。

| 类型 | 选型 | 版本 | 说明 |
|---|---|---:|---|
| Graph 编排 | LangGraph | `1.2.0` | 内容安全主链路用 `StateGraph` |
| LangChain | langchain | `1.3.0` | 模型、消息、工具基础抽象 |
| Ollama 接入 | langchain-ollama | `1.1.0` | 本地模型优先 |
| OpenAI 接入 | langchain-openai | `1.2.1` | 后续可切云端模型 |
| OpenAI SDK | openai | `2.36.0` | 与现有 AI 项目一致 |
| SQLite checkpoint | langgraph-checkpoint-sqlite | `3.1.0` | MVP 本地可恢复执行 |
| Postgres checkpoint | langgraph-checkpoint-postgres | `3.1.0` | 生产化后替换 SQLite |
| 本地模型 | Ollama + `qwen3-coder:30b` | 本地模型名 | 与 LangGraph 内容安全方案保持一致 |

MVP 阶段的 Agent 能力边界：

```text
Workflow 初筛
  -> Agent 工具循环
  -> ToolNode 执行工具
  -> 低置信度 interrupt 人工审核
  -> Command(resume=...) 恢复
```

第一版先支持 Ollama 本地模型。后续需要更强效果时，再通过配置切换到 OpenAI 兼容接口或其他云模型。

### 3. 数据库与存储

MVP 可以分两步走。

第一步，本地开发：

| 用途 | 选型 | 版本 | 说明 |
|---|---|---:|---|
| API 业务库 | SQLite | Python 标准库 | 最小化部署复杂度 |
| checkpoint | SQLite checkpoint | `3.1.0` | 支持 interrupt 后恢复 |
| 审计日志 | JSONL 文件 | 无 | 先保证可复盘 |

第二步，联调和准生产：

| 用途 | 选型 | 版本 | 说明 |
|---|---|---:|---|
| 主数据库 | PostgreSQL | `16` | `ascc` 已使用 `postgres:16` |
| checkpoint | PostgresSaver | `3.1.0` | 与业务数据同库或独立库均可 |
| 缓存/队列 | Redis | `7` | MVP 暂不强依赖，后续异步审核再启用 |

第一版不建议一开始就引入 Redis、消息队列和复杂任务系统。同步审核和人工恢复链路先跑通，异步化放到第二阶段。

### 4. 前端技术栈

MVP 前端只做内部人工审核页面，不做完整运营平台。

前端采用 `ascc/apps/web` 这种轻量组合：

| 类型 | 选型 | 版本 | 说明 |
|---|---|---:|---|
| Node.js | Node | `>=20.19.0` | 与现有前端工程约束一致 |
| 包管理 | pnpm | `10.12.1` | `ascc/package.json` 已固定 |
| 框架 | Vue | `^3.5.0` | 轻量审核台足够 |
| 构建工具 | Vite | `^6.3.0` | 沿用 `ascc/apps/web` |
| TypeScript | TypeScript | `^5.8.0` | 类型约束 API 调用 |
| UI 组件 | Naive UI | `^2.41.0` | 与现有前端偏好一致 |
| 状态管理 | Pinia | `^3.0.0` | 只保存审核列表和当前详情 |
| 路由 | Vue Router | `^4.5.0` | 审核列表、审核详情两页即可 |
| 服务端状态 | TanStack Vue Query | `^5.80.0` | 管理接口请求、刷新、缓存 |
| API 类型生成 | openapi-typescript | `^7.6.0` | 从 FastAPI OpenAPI 生成前端类型 |
| E2E 测试 | Playwright | `^1.60.0` | 只测人工审核主路径 |

第一版前端只需要两个页面：

```text
/reviews
  待人工审核列表

/reviews/:thread_id
  内容详情、规则命中、Agent 证据、人工决策表单
```

如果第一阶段时间紧，前端甚至可以先不做，先用 Swagger UI 或一个简单脚本调用 `POST /moderate/{thread_id}/resume`。但一旦需要给安全部门内部同事试用，就用上面这套 Vue + Naive UI 轻量审核台。

### 5. 第一版最终选型清单

第一版固定为：

```text
后端：Python 3.13 + uv + FastAPI 0.137.0 + Pydantic 2.13.4
AI：LangGraph 1.2.0 + LangChain 1.3.0 + langchain-ollama 1.1.0
模型：Ollama / qwen3-coder:30b
数据库：开发期 SQLite，准生产 PostgreSQL 16
checkpoint：开发期 SQLite checkpoint，准生产 Postgres checkpoint
前端：Vue 3.5 + Vite 6.3 + Naive UI 2.41 + pnpm 10.12.1
审计：MVP 先 JSONL，后续落 PostgreSQL
```

这套组合的原则是：和现有项目保持一致，先把内容安全主链路做出来，避免第一阶段被平台化工程拖慢。

## 二、MVP 阶段的目标

第一阶段只解决一个核心问题：

```text
业务系统提交一段内容
  -> 内容安全服务审核
  -> 返回 approved / rejected / needs_review
```

也就是说，先证明这条链路可用：

```text
POST /moderate
  -> Workflow 规则初筛
  -> 必要时进入 Agent 深度判断
  -> 必要时进入人工审核
  -> 返回最终审核结果
```

MVP 成功的标志不是功能很多，而是这条链路稳定、可解释、可复盘。

## 三、第一版只保留两个核心接口

对业务系统暴露的核心能力：

```http
POST /moderate
```

业务方提交内容，你们返回审核结果。

示例请求：

```json
{
  "request_id": "biz_001",
  "scene": "comment",
  "user_id": "u_123",
  "content": "用户发布的一段评论内容"
}
```

示例响应：

```json
{
  "request_id": "biz_001",
  "moderation_id": "mod_001",
  "thread_id": "thread_001",
  "status": "completed",
  "decision": "approved",
  "reason": "未发现明显违规内容",
  "risk_level": "low",
  "evidence": []
}
```

内部人工审核恢复接口：

```http
POST /moderate/{thread_id}/resume
```

这个接口给安全部门内部审核后台或运营工具使用，不建议第一版直接开放给普通业务系统。

示例请求：

```json
{
  "decision": "approved",
  "reason": "人工判断为新闻讨论语境，可以通过"
}
```

## 四、第一阶段项目目录建议

建议先保持目录简单：

```text
content_safety/
  app/
    __init__.py
    main.py              # FastAPI 入口
    schemas.py           # API 请求和响应模型
    graph.py             # LangGraph 组装
    state.py             # ModerationState
    workflow.py          # Workflow 规则初筛
    agent.py             # LLM 节点、Agent 决策解析
    tools.py             # Agent 可调用工具
    review.py            # interrupt / resume 人工审核逻辑
    audit.py             # 最小审计日志
  data/
    eval_cases.jsonl     # MVP 评测样本
    audit.jsonl          # 本地审计日志，后续可迁移数据库
  docs/
    mvp-implementation-guide.md
  tests/
    test_workflow.py
    test_moderate_api.py
```

第一版不要急着拆太细。先让开发者能快速找到：

- API 在哪里；
- Graph 在哪里；
- 规则在哪里；
- Agent 工具在哪里；
- 人工审核在哪里；
- 审计记录在哪里。

## 五、实施步骤

### 第 1 步：先定义 API 契约

先定好 `POST /moderate` 的请求和响应字段。

最小请求字段：

```text
request_id
scene
content
user_id
```

最小响应字段：

```text
request_id
moderation_id
thread_id
status
decision
reason
risk_level
evidence
```

其中：

- `status=completed` 表示已经有最终结果；
- `status=interrupted` 表示需要人工审核；
- `decision=approved` 表示通过；
- `decision=rejected` 表示拒绝；
- `decision=needs_review` 表示需要人工审核。

验收标准：

```text
业务方能用 HTTP 请求提交内容，并收到结构稳定的 JSON 响应。
```

### 第 2 步：实现 Workflow 规则初筛

Workflow 层只处理确定性规则。

第一版规则可以包括：

- 明确违规关键词；
- 垃圾链接数量；
- 重复字符刷屏；
- 广告或欺诈话术；
- 敏感类别关键词。

Workflow 层的职责是快速判断：

```text
明显正常 -> approved
明显违规 -> rejected
边界内容 -> needs_review
```

注意：敏感关键词不要全部直接拒绝。比如新闻、教育、研究、反诈、求助语境都可能需要进一步判断。

验收标准：

```text
明显垃圾内容可以被拒绝。
明显正常内容可以被通过。
敏感边界内容会进入 Agent 或人工审核，而不是被粗暴拒绝。
```

### 第 3 步：实现 Agent 工具循环

Agent 不要只做一次 `llm.invoke()`。

MVP 阶段至少准备三个工具：

```text
lookup_policy(category)
scan_spam_signals(content)
collect_context(content)
```

它们分别负责：

- 查询审核政策；
- 扫描垃圾内容信号；
- 提取上下文线索。

Agent 图里要形成工具循环：

```text
agent_assistant -> tools -> agent_assistant
```

这样模型可以先分析，再调用工具，再根据工具结果继续判断。

验收标准：

```text
Agent 能调用工具。
工具结果会进入消息上下文。
Agent 最终输出结构化审核结论。
```

### 第 4 步：实现人工审核暂停和恢复

低置信度、高风险、解析失败或政策不确定的内容，不要强行自动决策。

这类内容进入人工审核：

```text
interrupt()
```

恢复时使用：

```text
Command(resume=...)
```

第一版只需要一个内部接口：

```http
POST /moderate/{thread_id}/resume
```

验收标准：

```text
图可以在人工审核节点暂停。
使用同一个 thread_id 可以从暂停点恢复。
恢复后能生成 final_decision 和 final_reason。
```

### 第 5 步：加最小审计日志

内容安全系统必须能解释“为什么这么判”。

MVP 阶段可以先写 JSONL 文件，后续再迁移到数据库。

每次审核至少记录：

```text
request_id
moderation_id
thread_id
scene
content
workflow_decision
rule_hits
agent_decision
confidence
evidence
human_decision
final_decision
final_reason
created_at
```

验收标准：

```text
任意一次审核，都可以通过 moderation_id 查到规则、Agent、人工和最终结论。
```

### 第 6 步：准备 MVP 评测集

不要等平台做完才评测。

第一版就应该准备 `data/eval_cases.jsonl`。

样例：

```jsonl
{"content": "这是一条正常评论", "expected": "approved", "category": "normal"}
{"content": "AAAAAAAAAAAA 点击领取 http://a http://b http://c http://d", "expected": "rejected", "category": "spam"}
{"content": "这篇文章讨论暴力事件的新闻报道方式", "expected": "approved", "category": "contextual"}
{"content": "包含敏感但语义不明确的内容", "expected": "needs_review", "category": "borderline"}
```

验收标准：

```text
每次改规则、工具或提示词后，可以跑一遍评测集，看误判和漏判是否变多。
```

## 六、第一版暂时不做什么

MVP 阶段先不做这些：

- 多租户策略中心；
- 复杂权限系统；
- 完整审核后台；
- 大规模批处理；
- 复杂统计报表；
- 自动策略学习；
- 多模型路由；
- 多语言全量覆盖；
- 实时风控画像。

这些都重要，但不是第一阶段的主线。

第一阶段最重要的是：

```text
业务方能调用
系统能判断
高风险能转人工
结果能恢复
过程能审计
效果能评测
```

## 七、推荐里程碑

### 里程碑 1：接口跑通

交付内容：

- `POST /moderate`
- 基础请求/响应模型
- 固定 mock 结果或最小 Workflow

验收：

```text
业务方可以提交内容并拿到规范 JSON。
```

### 里程碑 2：规则初筛跑通

交付内容：

- Workflow 规则模块；
- 规则命中记录；
- 明确通过、明确拒绝、转 Agent 三种路径。

验收：

```text
正常、垃圾、敏感边界三类样本能走到不同路径。
```

### 里程碑 3：Agent 工具循环跑通

交付内容：

- LLM 节点；
- 工具列表；
- ToolNode；
- Agent JSON 结果解析。

验收：

```text
边界内容会触发 Agent，Agent 能调用工具并输出结构化结论。
```

### 里程碑 4：人工审核跑通

交付内容：

- `interrupt()`；
- `POST /moderate/{thread_id}/resume`；
- checkpoint；
- 人工结论进入最终结果。

验收：

```text
needs_review 内容可以暂停，并在人工提交结论后恢复完成。
```

### 里程碑 5：审计和评测跑通

交付内容：

- JSONL 审计日志；
- MVP 评测集；
- 简单评测脚本。

验收：

```text
每次审核可复盘。
每次改动可评测。
```

## 八、最终 MVP 形态

第一版完成后，系统应该具备这些能力：

```text
一个 FastAPI 服务
一个 LangGraph 混合审核图
一个 Workflow 规则初筛层
一个带工具循环的 Agent 层
一个人工审核恢复接口
一个最小审计日志
一个小型评测集
```

这时它已经不是一篇方案文档，而是一个可以被业务系统调用、可以被安全部门持续迭代的内容安全能力。
