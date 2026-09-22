# TripPilot 智能旅行助手

TripPilot 基于 Datawhale Hello-Agents 第 13 章旅行助手源码渐进重构。当前实现是一个可离线测试的工程化原型：FastAPI 接收结构化约束，LangGraph 编排检索、规划、路线、预算、验证和有上限重规划；高德检索及步行/驾车路线由确定性 Service 调用 MCP；公交路线因固定版 MCP 的 stdio 缺陷由有界 HTTP Service 调用高德，HelloAgents SimpleAgent 只负责从候选中生成计划草稿。Vue 3 前端展示结果；Redis 与 MySQL 可选，Docker Compose 提供完整本地服务组合。

## 当前请求链路

```text
Vue Home → POST /api/trip/plan → TripRequest / TravelConstraints
  → LangGraph plan：异步并发检索 POI、酒店和天气 → 候选 POI ID
  → 本地来源证据检索 → PlannerDraft（LLM 只选候选 ID）
  → 服务端水合 TripPlan → RouteOptimizer → BudgetEngine
  → PlanValidator → 首次硬约束违规时最多一次 Replan
  → 可选 MySQL PlanStore → Vue Result
```

路线、预算、日期和硬约束由 Python 代码计算。路线优先使用候选景点坐标，构建有界有向矩阵后按固定首点最近邻排序；地图上的点位不等于真实道路折线。开放/闭园判断只使用来源 URL、抓取时间和适用期齐全且标记为 verified 的证据。仓库未内置官方景区语料，默认没有这类事实时返回“不确定”。

## 本地运行

要求 Python 3.10、Node.js 22、`uvx`，以及你自己的高德 Web 服务 Key 和 LLM Key/模型。前端地图需要高德 JS Key。

```powershell
cd backend
Copy-Item .env.example .env
# 填写 AMAP_API_KEY、LLM_API_KEY、LLM_MODEL_ID
python -m pip install -r requirements-dev.txt
python run.py
```

另开终端：

```powershell
cd frontend
Copy-Item .env.example .env
# 填写 VITE_AMAP_WEB_JS_KEY；跨端开发可设置 VITE_API_BASE_URL=http://localhost:8000
npm ci
npm run dev
```

开发前端在 `http://localhost:5173`；API 文档在 `http://localhost:8000/docs`。后端启动时会检查地图和模型配置。不要提交 `.env`。

## Docker Compose

仓库根目录复制 `.env.example` 为 `.env`，填入高德、LLM 与 MySQL 密码，再运行：

```powershell
docker compose build
docker compose up -d
```

默认前端端口为 `http://localhost:8080`，Nginx 同源代理 `/api`。Compose 包含 backend、frontend、Redis 和 MySQL。镜像内安装 `uv`，运行时可以用 `uvx` 启动固定版本 `amap-mcp-server==0.1.11`。本机已实际构建前后端镜像，并用测试占位凭据验证四服务启动、首页与 `/api/trip/health` 返回 200；占位凭据无法验证真实旅行规划。

## API 与状态

- `POST /api/trip/plan`：生成计划。支持日期、交通/住宿、人数、CNY 预算、必去/避开地点、每日步行及单段交通上限。
- `GET /api/trip/plans/{plan_id}`：读取可选 MySQL 中的计划。
- `PUT /api/trip/plans/{plan_id}`：携带 `expected_version` 更新；后端重算路线和预算，验证通过后才写新版本。
- `GET /health`：进程存活；`GET /api/trip/health`：配置检查，不探测外部服务。

未配置数据库时，POST 仍可返回计划，但不会产生 plan_id；前端此时不提供服务端编辑。MySQL 保存的是业务计划记录，不是 LangGraph checkpoint，尚不支持中断后恢复图执行。

## 验证与结果边界

```powershell
cd backend
python -m pytest tests -q
python -m evaluation.benchmark
cd ..\frontend
npm run build
```

最近一次后端完整离线回归为 **192 passed、2 skipped**；前端生产构建通过。固定约束评测集为 **3/3**，数据和运行器分别在 `backend/evaluation/constraint_cases.json`、`backend/evaluation/benchmark.py`。一次本机测量的约束解析 P50/P95 见 [原始结果](docs/benchmark_results.json)；它不包含地图、LLM、路线或网络耗时，也不代表线上规划性能。三条固定真实高德/LLM 案例初测中两条通过、一条失败，详见 [逐例结果](docs/live_e2e_results.json)；该小样本不是线上成功率。未取得可审计的 provider token、成本或缓存命中率，因此不提供这些数字。

## 已知限制

- 自由文本当前没有独立的结构化约束提取器；硬约束以表单字段为准。
- 默认 RAG 语料为空；没有官方资料时不声称景点开放、无需预约或无障碍。
- 景点可带计划到访开始/结束时间；确定性校验游览时长和相邻交通间隔。旧计划可无时刻，且尚无真实景区营业时段、预约/无障碍硬约束证据。
- 规划调用仍是同步 HelloAgents；HTTP 客户端取消不保证取消后端计算。
- LangGraph 没有持久 checkpoint；MySQL 不能恢复中断的节点执行。
- 前端缺少浏览器端到端测试，构建仍提示大包；Docker 构建中 `npm ci` 报告的依赖告警需要逐项审计。GitHub Actions 工作流已提交，但尚未在远端验证。

阶段过程和实测证据见 [项目进度](docs/progress.md)、[重构计划](docs/refactor_plan.md) 与 [Phase 0 架构分析](docs/current_architecture.md)。

Phase 21 已修复北京公交限流重试和交通时长反馈，原失败案例单独复测通过；属于单例结果，不改变历史三例初测记录，也不代表线上成功率。详见 [阶段记录](docs/phase21.md)。

2026-09-22 更新：已增加自由文本约束提取预览（用户确认后填入空白字段）、7 项浏览器 API 契约回归、PDF 下载验证；依赖审计当前为 0 项。浏览器测试使用固定 API 响应，远端 CI 未验证。
