# TripPilot 项目交接（2026-09-19）

## 先读这些文件

工作目录：`E:\travel-agents-1\helloagents-trip-planner`。先读根目录 `AGENTS.md`、`docs-project_spec.md`（**不是** `docs/project_spec.md`）、`README.md`、`docs/progress.md`、`docs/refactor_plan.md`，再读本交接。实际代码和 `docs/progress.md` 优先于旧聊天记录；若文档冲突，以代码、测试和 Git 为准。

## 当前状态与交付

Datawhale Hello-Agents 第 13 章旅行助手已经渐进重构为 TripPilot 工程化原型。Phase 0–18 的阶段代码、阶段文档、提交和阶段学习资料已完成。2026-09-19 交接前 `main` 工作区干净，最近提交 `5187096 docs: finish Phase 18 with honest benchmark and project guide`。本交接文档属于阶段完成后的补充，不代表原始规格全部验收。

每个阶段的记录在 `docs/phase1.md` 至 `docs/phase18.md`；Phase 0 在 `docs/current_architecture.md`。归档位于 `E:\TP各版本文档\1` 至 `18`，各目录有 `学习文档.md`（含实际实现代码），总路线为 `E:\TP各版本文档\学习路线.md`。Phase 18 资料还包括 `docs/benchmark.md`、`docs/benchmark_results.json` 和 `docs/resume_project.md`。

## 真实请求链路和代码入口

- 前端：`frontend/src/views/Home.vue` 采集结构化约束，`frontend/src/services/api.ts` 发起请求；`frontend/src/views/Result.vue` 展示计划并用 plan_id/version 读取、编辑。
- API：`backend/app/api/main.py` 注册路由和生命周期；`backend/app/api/routes/trip.py` 接收 `POST /api/trip/plan`，构建 TravelConstraints，可选 PlanStore 状态记录，调用请求级 TripPlanningWorkflow。GET/PUT 计划也在该文件；PUT 重算并复验。
- 图：`backend/app/workflows/trip_workflow.py` 使用 LangGraph 编排 plan、route、budget、validate、replan、failure；硬违规默认最多重规划一次。图状态请求隔离，**没有持久 checkpoint**。
- 规划：`backend/app/agents/trip_planner_agent.py` 调用 HelloAgents SimpleAgent；`backend/app/models/planner.py` 限制 PlannerDraft 只引用请求内候选 ID，服务端再水合真实候选。`backend/app/services/llm_service.py` 提供 ModelGateway 的调用/Prompt 上限和安全错误分类。
- 检索和工具：`backend/app/services/retrieval_service.py` 并发检索，`amap_service.py` 解析高德 MCP 返回，`tool_runtime.py` 管理原生 MCP stdio 会话、参数校验、超时、重试和并发配额。`cache_service.py` 可选 Redis 类型化缓存。
- 确定性业务：`constraint_service.py`、`route_service.py`、`budget_service.py`、`validation_service.py`；`rag_service.py` 只读取带 URL/适用期的本地证据，默认没有官方语料。`persistence_service.py` 可选 MySQL 业务计划记录和乐观锁。
- 数据类型：`backend/app/models/schemas.py`、`planner.py`、`validation.py`、`knowledge.py`。部署入口见 `compose.yaml`、前后端 Dockerfile、`frontend/nginx.conf` 和 `.github/workflows/verify.yml`。

核心设计原则：LLM 决定候选和软性规划；天气、POI、酒店、地图、路线、预算及硬约束由 Service/Tool 和确定性代码承担，不为了 Multi-Agent 而增加 Agent。异步并发只用于独立 I/O，并有限时和部分失败语义。

## 已验证的事实

- 本地后端全量离线回归：`cd backend; python -m pytest tests -q`，最近结果 **154 passed、2 skipped、10 warnings**。
- 前端：`cd frontend; npm run build` 通过；构建有大包警告。缺少浏览器端到端验证。
- Phase 17 曾实际构建前后端 Docker 镜像，Compose 启动 backend/frontend/Redis/MySQL；以测试占位凭据验证首页和 `/api/trip/health` HTTP 200。**没有**用真实高德或 LLM 凭据验证完整旅行规划；GitHub Actions 尚未在远端运行。
- Phase 18：`cd backend; python -m evaluation.benchmark` 固定约束集 3/3。`docs/benchmark_results.json` 保存一次 Windows/Python 3.10.1 测量，10 次预热、100 次测量，P50 0.138 ms、P95 0.174 ms。它只测 JSON 读取、Pydantic/Constraint Service，不是 HTTP、MCP、LLM 或全链路性能；复测值会变化。
- 历史 Phase 7 曾用真实 MySQL 8.4 容器验证事务、版本冲突和重连；Phase 6 曾用真实 Redis 容器验证缓存。相关细节见各阶段文档。

## 未完成和不能声称完成的内容

原始 `docs-project_spec.md` 的“可恢复、可验证、可观测”是目标定位，当前只部分达到。自由文本约束提取器未实现；本地 RAG 证据接口已有，但没有真实官方语料，预约/开放时间/时段冲突/无障碍不能全面验证；LangGraph 无持久 checkpoint；MySQL 无 Alembic、鉴权和计划所有权；同步 HelloAgents 调用无法可靠响应 HTTP 客户端取消。真实高德/LLM 端到端成功率、token/成本、缓存命中率和全链路延迟未测。前端缺浏览器 E2E；依赖漏洞、大包和弃用警告需要审计。不能把 Phase 0–18 完成等同于生产上线验收。

## 新对话建议的第一步

不要重做 Phase 0–18。先读取上述事实来源，运行 `git status --short --branch`，确认当前提交和未提交改动，再让用户指定下一目标。若用户仅说“继续”，优先从 `docs/progress.md` 的遗留问题中提出有证据的最小下一阶段，并按 `AGENTS.md` 做一个阶段、验证、更新进度、汇报后停止；只有用户再次明确授权连续推进才跨阶段。新阶段应先选可离线验证的缺口，例如时间窗数据模型/校验或浏览器 E2E，不要在没有官方语料/供应商凭据时编造真实评测。

## 环境注意

本机 PowerShell 的普通命令执行偶尔报 `helper_unknown_error: setup refresh had errors`，这是工具执行环境初始化故障，不代表项目代码失败。此前获授权后使用提升执行权限的命令可继续；先尝试正常工具，失败时说明并按当前权限规则处理。不要把执行工具报错写成测试失败。
## 2026-09-20 更新

Phase 19 到访时间窗已落地；Phase 20 完成真实高德/LLM 固定案例初测和坐标路线、Planner null 字段修复。三例初测中上海步行与杭州自驾成功，北京公共交通失败；公交 MCP stdout 缺陷已绕开，但北京复测仍返回 422。后端回归 171 passed、2 skipped；结果和边界见 [phase20.md](phase20.md)、[live_e2e_results.json](live_e2e_results.json) 与 [progress.md](progress.md)。上文 2026-09-19 交接数字保留历史原样。

## 2026-09-22：Phase 21 完成

北京公交真实单例复测通过（运行于 2026-09-20），后端回归 178 passed、2 skipped。已补公交业务限流重试、保序相邻路线查询、带交通秒数的重规划反馈与 Redis 总超时归一化。历史 Phase 20 失败结果保留。详见 [phase21.md](phase21.md)。下一建议是浏览器 E2E；当前阶段完成后停止。

## Phase 22–24 更新

用户已明确授权连续优化。已完成浏览器契约回归、依赖修复和按需导出、自由文本约束提取预览。当前后端 192 passed、2 skipped，浏览器 7 passed，build 通过。下一步官方证据与营业/预约校验；主规划的自动语义提取、全栈浏览器真实联调、持久 checkpoint 与远端 CI 不应声称完成。详见 phase22.md 至 phase24.md。

## Phase 25 更新

故宫官方证据、营业时段与免预约约束、引用和 warning 持久化展示已完成。202 passed、2 skipped；8 项浏览器回归，build 通过。具体边界见 [phase25.md](phase25.md)，下一项持久 checkpoint。

## Phase 26 更新

本地 SQLite checkpoint/恢复 CLI 已验证，稳定依赖在 backend/.venv，205 passed、2 skipped。HTTP 自动恢复仍未实现。详见 [phase26.md](phase26.md)。

## 2026-09-22 当前验证

阶段 22–27 已补浏览器回归、前端依赖审计、提取预览、故宫有限官方证据、SQLite 本地 checkpoint 与长请求等待修复。项目 .venv 后端 205 passed、2 skipped、1 warning；浏览器 9 passed；build 通过。远端 CI 无 remote，等待用户目标仓库与推送授权；不能声称原始规格全部完成。

## 2026-09-23：Phase 28 更新

GitHub 远端 CI 已在 codex/verify-trip-pilot 分支验证 backend/frontend 作业成功。Phase 28 已把 SQLite LangGraph checkpoint 接入同步 HTTP 与首页恢复：浏览器请求前保存随机 plan ID，MySQL 业务记录与 checkpoint 以同一 ID 关联，新增 POST /api/trip/plans/{plan_id}/resume，并用进程内互斥避免同一图线程重复推进。后端 207 passed、2 skipped、1 warning；浏览器 10 passed；前端与两镜像构建通过；占位配置 Compose 首页/API 200 且 checkpoint 卷可写。恢复 ID 尚未绑定用户，互斥不覆盖多实例，真实供应商全链路没有在本阶段重测。详见 [phase28.md](phase28.md)。
## 2026-09-23：Phase 29 更新

Alembic 已取代 create_all，并兼容旧 trip_plans 表原地升级。浏览器计划 API 使用只存摘要的 256 bit capability token；Compose 默认强制所有权。进程内互斥已升级为数据库租约，记录含 workflow_version；新增终态业务记录与 SQLite checkpoint 同步清理 CLI。后端 212 passed、2 skipped、1 warning；浏览器 10 passed；前端和镜像构建通过。隔离 MySQL 8.4 迁移到 0001_plan_ownership，容器所有权验证 403/403/200，未调用真实供应商。详见 [phase29.md](phase29.md)。当前个人应用状态基础已补齐；公网账号系统、网络 checkpoint store、更多官方语料、真实预约和大样本真实全链路仍未完成。
