# TripPilot 进度

更新时间：2026-09-19。事实来源：当前代码、本文件、根目录 `docs-project_spec.md`。

## 当前阶段

Phase 0–18 的阶段代码与记录已落地；关键规格缺口列于下方，不能视为线上验收完成。用户已授权逐阶段继续到最终阶段；每阶段独立验证、提交并归档文档。

## 当前架构

`FastAPI 同步工作线程 → TravelConstraints → LangGraph(structured plan → deterministic route → deterministic budget → deterministic validation → bounded replan) → TripRetrievalService → AmapService → 类型化 RetrievalCache（可选 Redis）→ ToolRuntime → 原生 MCP stdio 会话`。候选 POI 还会按稳定 ID 经本地来源证据检索进入 Planner 与 Validator；检索结果先生成请求内候选 catalog，Planner LLM 只返回候选 ID 草稿；服务端水合 TripPlan 后，路线、预算与 Validator 依次计算。只有类型化 error violations 才可触发一次有上限 Replan；配置数据库后，PlanStore 持久化最终计划。

- 约束：日期、人数、CNY 预算上限、必去/避开、步行及单段交通上限已结构化；自由文本提取只有合并边界，尚无提取器。
- 工具：本地 Pydantic 参数白名单 + 发现的工具 schema；每次尝试独立会话；默认 20 秒单次/50 秒总截止时间、最多 2 次尝试、每进程 3 个并发槽。只重试明确超时或结构化限流。
- 检索：最多 3 个并发任务，单任务含排队 60 秒截止时间，覆盖偏好和必去，POI 按 ID 去重，每个搜索最多补查 6 个详情。无有效景点明确终止。
- 缓存：只保存已验证的 POI、天气、geocode、路线类型结果；键含协议版本、操作和规范化参数哈希。POI/geocode 24 小时、路线 30 分钟、天气 10 分钟；Redis 不可用或值损坏时回源。
- 持久化：可选 MySQL 保存请求、`planning/completed/failed` 状态、计划 JSON 和乐观锁版本；提供 GET/PUT，数据库关闭时旧 POST 保持兼容。
- 预算：门票、餐饮和交通按人数计算，酒店按两人一间及 `天数-1` 夜计算；0 与未知 null 分离，输出 unknown_items、完整性和预算上限三态。
- 路线：每天最多 6 点构建有向矩阵，日内最多 3 个并发调用，单段 60 秒、每日矩阵 90 秒截止；固定首点的最近邻排序可复现，显式输出不可达、分段超时、步行超限和矩阵截断。
- Planner：私有 `PlannerDraft` 禁止额外字段，景点/酒店只引用 `A001/H001` 作用域 ID；城市、日期、天气及 POI 身份由服务端水合。非法格式、未知 ID 和日期错位最多修复一次，仍失败则明确终止。
- 模型：`ModelGateway` 在 Planner 外集中请求级调用上限、Prompt 上限、429/超时安全分类和本地 token 估算；初始规划、格式修复与 Replan 共用预算。
- 可观测性：JSON 日志只输出白名单字段；请求关联 ID、HTTP 状态/耗时、稳定错误码和 LangGraph 节点事件可关联，不记录请求正文、Prompt 或异常原文。
- 校验：Validator 检查日期、预算、must/avoid、重复和路线告警；error 触发有上限 Replan，warning 保留不确定性。PUT 重算路线/预算后在持久化前复验。
- RAG：`TravelEvidence` 要求 URL、抓取时间、适用日期及 verified/uncertain 状态；默认没有语料即为未知。Planner 可读取证据，Validator 只根据适用的 verified 闭园日期拒绝计划，不将缺失资料推断为开放。
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
| 9 | [确定性 Route Optimizer](phase9.md)，提交 3bbe3fc |
| 10 | [Structured Planner](phase10.md)，提交 98c9402 |
| 11 | [Validator + Replan](phase11.md)，提交 d49ae87 |
| 12 | [来源可追溯旅行 RAG](phase12.md)，提交 e4ea980 |
| 13 | [Model Gateway](phase13.md)，提交 f844ceb |
| 14 | [安全可观测性](phase14.md)，提交 bd2318b |
| 15 | [离线评测基线](phase15.md)，提交 e509985 |
| 16 | [前端约束与服务端编辑](phase16.md)，提交 46d217e |
| 17 | [Docker 与 CI](phase17.md)，提交 833007a |
| 18 | [README、Benchmark 与求职材料](phase18.md)，提交见 Git 历史 |

## Phase 11 修改

新增类型化 `PlanViolation` 和确定性 `PlanValidator`，把日期、预算、must/avoid、重复、路线不可达及交通/步行超限统一写入图 state。LangGraph 新增 validate、replan、failure 分支，默认只允许一次重规划并在再次违规时返回安全 422。计划 PUT 重算路线和预算后必须验证，失败不写入新版本。

## Phase 12 修改

新增文件式、来源可追溯的旅行证据服务与 Pydantic 模型。只有带 URL、抓取时间、适用期且标记为 verified 的闭园事实能触发 Validator 错误；无证据和 uncertain 事实显式保留为不确定。当前仓库没有真实官方语料，默认空 corpus 不会制造事实。

## Phase 13 修改

新增请求级 Model Gateway，限制单次规划的模型调用和 Prompt 尺寸，格式修复与重规划共享预算；记录本地 token 估算并将模型 429/超时归入安全错误。HelloAgents 未给出可审计 provider usage，故不产生虚构成本数据。

## Phase 14 修改

JSON 日志补充请求耗时、状态码、稳定错误码和工作流节点名；日志 formatter 仍只保留允许字段，避免将用户输入、Prompt、异常原文或 MCP 内容写出。

## Phase 10 修改

新增私有 Planner 输出 schema，把不可信 LLM 草稿与公开 TripPlan 分离。检索候选映射为稳定的请求内 ID，模型只能选择 ID；服务端用原 POI 水合名称、地址、坐标和来源 ID，并用约束与检索结果覆盖城市、日期和天气。严格校验天数、日期、索引、三餐及额外字段；默认只允许一次格式修复。

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

`backend: python -m pytest tests -q`：**154 passed，2 skipped，10 warnings**。

真实 MySQL 8.4 一次性容器验证：`tests/test_phase7_persistence.py` **7 passed，10 warnings**；容器已删除。真实 Redis 阶段验证仍见 Phase 6 记录。
`git diff --check`：通过。

测试包括真实本地 MCP stdio 子进程正常关闭/超时退出（检查进程 returncode）、工具取消/配额/重试/截止时间、路线矩阵边界、Planner 候选与有限修复，以及 Validator 的约束违规、图中有界重规划与 PUT 写入前复验。没有访问真实高德、LLM 或 Unsplash，没有线上性能结论。

环境：Python 3.10.1、mcp 1.29.1、anyio 4.14.2、hello-agents 0.2.9；LangGraph 本机仍为 1.0.0a3，后续需要在干净环境固定稳定版本。前端 Phase 16 生产构建通过；Phase 17 前后端镜像构建与 Compose 冒烟通过。

## 遗留问题

- 高德 MCP 0.1.11 会把部分错误压成文字，无法可靠区分这些错误的限流/可重试性；运行时保守不重试这类错误。
- 截止时间触发后仍需执行 SDK 的进程清理，实际返回可多出清理时间。当前 HTTP 同步路由不会在客户端断开时自动取消；原生检索协程本身已支持取消。
- Planner LLM 仍是同步 HelloAgents 调用，共享实例拒绝重叠规划；已有调用/Prompt 上限和 token 估算，但 SDK 没有可靠 provider usage，尚无真实成本、fallback 或流式策略。
- ToolResult 提供工具名、抓取时间、尝试次数和耗时；候选级引用和跨节点指标尚未接入。
- Redis 已作为可选检索缓存接入；MySQL 已提供可选计划记录，前端已接入服务端 GET/PUT。缺少真实官方证据语料、持久 checkpoint 和线上评测；不可宣称已完成真实供应商端到端验收。
- MySQL 当前使用 `create_all`，没有 Alembic、鉴权、所有权或中断工作流恢复；`planning` 只用于识别未完成请求。
- 预算单价尚无可靠证据；房间容量固定为 2，交通成本仍缺少可靠供应商报价；前端已展示未知费用状态。
- 路线使用固定首点的最近邻启发式，不保证全局最优；混合交通暂映射公共交通，尚无逐段多模式比较、路线几何、固定中间点或时间窗。
- 路线只标记失败和超限，尚未触发重新选点；整个规划请求也没有统一总截止时间。
- Planner 候选 Prompt 尚无独立数量上限；价格、时长、餐饮和描述仍缺少证据，尚未测试真实模型的 schema 遵循率。
- 已有带来源/适用期的本地证据接口，但没有提交真实官方 POI 语料；预约、时段和无障碍尚无用户硬约束，证据 warning/引用也未持久化或展示给前端。must/avoid 仍基于名称包含匹配。
- 缓存没有 single-flight、主动失效、预热或命中率指标；未在真实负载上测量延迟与成本收益。
- 子进程级并发已由离线 MCP 测试验证；真实地图服务仍需联网验收。依赖弃用警告和前端大包警告尚存。

## 下一阶段

后续：补真实官方证据、自由文本提取、时间窗约束、持久 checkpoint、真实服务评测和 CI 远端执行。

## Phase 16 修改

Home 增加结构化硬约束字段并移除模拟阶段进度；Result 用服务端 plan_id/version GET/PUT，编辑由后端重算并校验；图片请求去重且地图独立加载。前端生产构建通过，浏览器端到端验证待补。

## Phase 17 修改

新增后端/前端镜像、Nginx 同源代理、MySQL/Redis Compose、环境模板及 CI。Compose 语法、前后端镜像构建与四服务启动通过；首页和代理 API 均返回 HTTP 200。CI 远端运行尚未验证。

## Phase 18 修改

README 已按现有代码重写，新增约束层可复现 benchmark、原始结果和求职项目说明。固定样例 3/3，100 次本地约束测量 P50 0.138 ms、P95 0.174 ms；不是全链路规划指标。
