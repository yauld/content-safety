# Content Safety MVP

内容安全 MVP 项目。

第一版目标：

```text
业务系统 -> POST /moderate -> Workflow 初筛 -> Agent 深度判断 -> 人工审核恢复 -> 最终结果
```

## 目录

```text
backend/   FastAPI + LangGraph 后端
frontend/  Vue + Naive UI 简单审核台
data/      SQLite、checkpoint、JSONL 审计和评测样本
docs/      实施文档
```

## 后端

```bash
cd backend
uv sync --dev
uv run content-safety-api
```

API 文档：

```text
http://localhost:8002/docs
```

后端 Python 解释器：

```text
backend/.venv/bin/python
```

如果从项目根目录打开 VS Code，已在 `.vscode/settings.json` 中固定该解释器，并把 `backend/src` 加入 Python 分析路径。

## 前端

```bash
cd frontend
pnpm install
pnpm dev
```

默认访问：

```text
http://localhost:5173
```

## 模拟业务系统调用

可以用项目里的脚本模拟一个业务系统调用内容安全服务。运行前先启动后端：

```bash
cd backend
uv run content-safety-api
```

脚本会自动探测本地内容安全服务地址，不需要手动传 `--api-base`。目前只保留四种验证入口：

```bash
# 验证不当语言规则：期望命中 profanity_keyword
python3 examples/mock_business_client.py --profanity

# 验证敏感话题规则：期望命中 sensitive_topic
python3 examples/mock_business_client.py --sensitive-topics

# 验证广告/欺诈导流规则：期望命中 ad_or_fraud_phrase
python3 examples/mock_business_client.py --ad-phrases

# 运行全部默认用例
python3 examples/mock_business_client.py --all
```

脚本会模拟业务系统根据返回结果做决策：

```text
approved -> 允许发布
rejected -> 拒绝发布
needs_review/interrupted -> 进入业务待审核状态
```

如果用例设置了期望命中的规则，脚本输出里会额外显示：

```text
规则命中: profanity_keyword
期望规则: profanity_keyword -> PASS
```

## 导出 LangGraph 图图片

图导出脚本会直接复用后端代码里的 `build_graph(...)`，生成当前真实 Graph 结构的 PNG 图片。

第一次导出前，需要安装 Graphviz 和 pygraphviz：

```bash
brew install graphviz
cd backend
uv add --dev pygraphviz
```

从 `backend/` 目录导出默认图片：

```bash
cd /Users/peace/OpenClawWorkspaces/ArgusAgentWorkspace/project/content_safety/backend
uv run python scripts/export_graph.py
```

默认输出到：

```text
backend/docs/content-safety-graph.png
```

也可以指定输出路径：

```bash
uv run python scripts/export_graph.py docs/content-safety-graph.png
```

如果你在项目根目录 `content_safety/` 下执行，可以这样写：

```bash
uv run --project backend python backend/scripts/export_graph.py backend/docs/content-safety-graph.png
```
