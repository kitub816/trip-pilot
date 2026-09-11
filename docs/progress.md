# TripPilot 进度

更新时间：2026-09-11。事实来源：当前代码、本文件、根目录 `docs-project_spec.md`。

## 当前阶段

Phase 0–9 已实现，Phase 10–18 待完成。用户已授权逐阶段继续到最终阶段；每阶段独立验证、提交并归档文档。

## 当前架构

`FastAPI 同步工作线程 → TravelConstraints → LangGraph(plan → deterministic route → deterministic budget) → TripRetrievalService → AmapService → 类型化 RetrievalCache（可选 Redis）→ ToolRuntime → 原生 MCP stdio 会话`。Planner LLM 生成候选日程与单价线索，RouteOptimizer 查询路线并重排每日景点，BudgetEngine 按人数和夜数覆盖预算汇总；配置数据库后，PlanStore 持久化最终计划。请求级图 state 不作 checkpoint，Planner 仍用进程内互斥和历史清理。

- 约束：日期、人数、CNY 预算上限、必去/避开、步行及单段交通上限已结构化；自由文本提取只有合并边界，尚无提取器。
- 工具：本地 Pydantic 参数白名单 + 发现的工具 schema；每次尝试独立会话；默认 20 秒单次/50 秒总截止时间、最多 2 次尝试、每进程 3 个并发槽。只重试明确超时或结构化限流。
- 检索：最多 3 个并发任务，单任务含排队 60 秒截止时间，覆盖偏好和必去，POI 按 ID 去重，每个搜索最多补查 6 个详情。无有效景点明确终止。
- 缓存：只保存已验证的 POI、天气、geocode、路线类型结果；键含协议版本、操作和规范化参数哈希。POI/geocode 24 小时、路线 30 分钟、天气 10 分钟；Redis 不可用或值损坏时回源。
- 持久化：可选 MySQL 保存请求、`planning/completed/failed` 状态、计划 JSON 和乐观锁版本；提供 GET/PUT，数据库关闭时旧 POST 保持兼容。
- 预算：门票、餐饮和交通按人数计算，酒店按两人一间及 `天数-1` 夜计算；0 与未知 null 分离，输出 unknown_items、完整性和预算上限三态。
- 路线：每天最多 6 点构建有向矩阵，日内最多 3 个并发调用，单段 60 秒、每日矩阵 90 秒截止；固定首点的最近邻排序可复现，显式输出不可达、分段超时、步行超限和矩阵截断。
- 地图：按本地缓存的 amap-mcp-server 0.1.11 源码解析搜索、详情、天气、地理编码和路线；生产固定该版本。搜索不含坐标，详情提供坐标；路线结果有距离和时间，无前端路网折线。
- 安全：API 错误不含原文；MCP 子进程 stderr 不外传，MCP transport 日志只保留安全事件；健康检查不访问外部依赖。
- 生命周期：会话及子进程由 async context 关闭；ASGI 停机清理 runtime、服务和 Planner/LLM 引用。

## 阶段记录

| Phase | 状态/文档 |
| --- | --- |
| 0 | [现状分析](current_architecture.md)，历史源码快照 |
| 1 | [配置、日志、异常](phase1.md)，基线提交 73d0e36 |
| 2 | [约束引擎](phase2.md)，提交 b0e5a04 |
| 3 | [最小 LangGraph](phase3.md)，提交 0f5ceb1 |
| 4 | [检索 Service](phase4.md)，提交 19a0d3b；本次复核发现原测试未覆盖真实返回格式，缺口已在 Phase 5 修补 |
| 5 | [Tool Runtime](phase5.md)，包括 Phase 4 缺口修补 |
| 6 | [Redis 类型化检索缓存](phase6.md)，提交 a48b78c |
| 7 | [MySQL 计划持久化](phase7.md)，提交 85d01e1 |
| 8 | [确定性 Budget Engine](phase8.md)，提交 53f469f |
| 9 | [确定性 Route Optimizer](phase9.md)，提交待本阶段提交后回填 |

## Phase 9 修改

新增 `RouteOptimizer` 和 LangGraph route 节点，复用 AmapService、Tool Runtime 与路线缓存构建有界有向矩阵；固定首点并按时间、距离及原始位置确定性排序。新增类型化日路线和路段状态，显式标记不可达、单段时间超限、每日步行超限及矩阵截断。创建和 PUT 更新均先重算路线再重算预算。

## Phase 8 修改

新增 `BudgetEngine` 和 LangGraph budget 节点；成本字段改为非负可空语义，新增每日交通成本、房间/夜数、未知费用及预算上限状态。Planner 不再负责汇总，创建和更新计划都会由服务端重算并覆盖 LLM/客户端总价。

## Phase 7 修改

新增 SQLAlchemy `PlanStore`、MySQL/PyMySQL 依赖和类型化存储响应；规划 API 持久化状态转换，并新增计划读取与乐观锁更新接口。SQLite 文件测试证明新 Store 实例可重读，真实 MySQL 8.4 容器验证建表、事务、版本冲突和重启连接读取。LangGraph checkpoint 与业务计划记录保持分离。

## Phase 6 修改

新增 `cache_service.py` 和 Redis 集成/回归测试；AmapService 的完整 POI 搜索、天气、geocode、路线在 Pydantic 边界接入可选缓存。缓存采用版本化哈希键、TTL envelope 和二次 Pydantic 校验；不缓存空值、失败或不完整 POI，Redis 断开时回源。

## Phase 5 修改

新增 `backend/app/services/tool_runtime.py`；更新 AmapService、RetrievalService、Planner 兼容入口、配置、错误、生命周期、日志及依赖；新增 runtime/stdio/检索集成测试和离线 MCP fixture；修订已迁移接口的旧测试。删除废弃检索 Agent Prompt 和已损坏的旧四 Agent 入口实现。

修正了上阶段正则过度转义、错误响应当空成功、无候选仍调用 LLM、真实 POI 搜索没有坐标、真实天气 forecasts 格式不匹配、路线和 geocode 未实现等问题。原归档保持历史原样，以 Phase 5 记录修正。

## 实际验证

`backend: python -m pytest tests -q`：**123 passed，2 skipped，10 warnings**。

真实 MySQL 8.4 一次性容器验证：`tests/test_phase7_persistence.py` **7 passed，10 warnings**；容器已删除。真实 Redis 阶段验证仍见 Phase 6 记录。
`git diff --check`：通过。

测试包括真实本地 MCP stdio 子进程正常关闭/超时退出（检查进程 returncode）、替身会话取消/配额释放/并发重叠/有界重试/总截止时间、服务 schema 不匹配、JSON 及结构化 MCP 错误、真实服务格式样例、慢天气保留景点，以及路线矩阵的可复现顺序、并发边界、不可达、约束和取消。没有访问真实高德、LLM 或 Unsplash，没有线上性能结论。

环境：Python 3.10.1、mcp 1.29.1、anyio 4.14.2、hello-agents 0.2.9；LangGraph 本机仍为 1.0.0a3，后续需要在干净环境固定稳定版本。前端最近一次 Phase 2 构建通过，本阶段未改前端。

## 遗留问题

- 高德 MCP 0.1.11 会把部分错误压成文字，无法可靠区分这些错误的限流/可重试性；运行时保守不重试这类错误。
- 截止时间触发后仍需执行 SDK 的进程清理，实际返回可多出清理时间。当前 HTTP 同步路由不会在客户端断开时自动取消；原生检索协程本身已支持取消。
- Planner LLM 仍是同步 HelloAgents 调用，共享实例仍拒绝重叠规划；预算汇总已移出 LLM，结构化候选选择和最终约束验证待后续阶段。
- ToolResult 提供工具名、抓取时间、尝试次数和耗时；候选级引用和跨节点指标尚未接入。
- Redis 已作为可选检索缓存接入；MySQL 已提供可选计划记录，前端尚未改为服务端读取；尚无 RAG/持久 checkpoint/部署与线上评测，不可宣称行程已通过硬约束验证。
- MySQL 当前使用 `create_all`，没有 Alembic、鉴权、所有权或中断工作流恢复；`planning` 只用于识别未完成请求。
- 预算单价尚无可靠证据；房间容量固定为 2，交通尚未按路线段生成，前端还未展示未知费用状态。
- 路线使用固定首点的最近邻启发式，不保证全局最优；混合交通暂映射公共交通，尚无逐段多模式比较、路线几何、固定中间点或时间窗。
- 路线只标记失败和超限，尚未触发重新选点；整个规划请求也没有统一总截止时间。
- 缓存没有 single-flight、主动失效、预热或命中率指标；未在真实负载上测量延迟与成本收益。
- 子进程级并发已由离线 MCP 测试验证；真实地图服务仍需联网验收。依赖弃用警告和前端大包警告尚存。

## 下一阶段

Phase 10：实现 Structured Planner，让 LLM 只能从候选 ID 中选择并按 schema 返回，拒绝非法 JSON、未知 POI ID 和越界日期。
