# TripPilot 项目学习教程：面向研二 Agent 实习

适用读者：准备 AI Application Engineer、Agent 应用开发或 LLM 工程实习的研二学生。

学习目标：读完本文并完成练习后，你应能独立讲清 TripPilot 的业务目标、请求链路、架构取舍、核心源码、测试体系、真实能力边界，并能现场定位问题或扩展一个约束。

事实基线：Phase 0–29 已实现；后端完整离线回归 212 passed、2 skipped；前端生产构建与 10 项 Playwright 测试通过；GitHub Actions backend/frontend 作业通过。历史 P50/P95 只测本地约束层，不是全链路性能。

## 1. 项目定位

TripPilot 不是“让多个 Agent 互相聊天”的演示，而是约束驱动、可验证、可恢复的旅行决策系统：

- LLM 负责语义理解、候选组合、计划生成和软约束。
- LangGraph 负责状态、节点、条件分支和有限 Replan。
- Service 负责检索、路线、预算、缓存、证据和持久化。
- Pydantic 负责输入、输出和模块边界。
- Validator 负责预算、日期、时间、距离等硬约束。
- MySQL 保存业务状态，SQLite checkpoint 保存执行状态。
- Redis 只缓存经过类型校验的检索事实。

面试定位可以说：

> TripPilot 是基于 FastAPI、LangGraph、MCP 和 RAG 的约束驱动旅行规划 Agent。我把 LLM 限制在候选选择与计划生成，将预算、路线、时间窗和硬约束交给确定性 Python，并补充缓存、持久恢复、评测、可观测性和前端闭环。

## 2. 端到端架构

~~~text
Vue Home
  │ 结构化表单 / 自由文本提取预览 / 用户确认
  ▼
POST /api/trip/plan
  │ TripRequest → TravelConstraints
  ▼
LangGraph
  ├─ plan
  │   ├─ asyncio 并发检索 POI、酒店和天气
  │   ├─ RAG 读取带来源的证据
  │   ├─ LLM 生成只引用候选 ID 的 PlannerDraft
  │   └─ 服务端水合 TripPlan
  ├─ route：确定性路线矩阵和稳定排序
  ├─ budget：确定性费用汇总
  ├─ validate：日期、预算、地点、路线、时间窗、证据
  ├─ replan：仅在 error violation 时有限重规划
  └─ failure / END
  │
  ├─ MySQL：状态、版本、所有权摘要、数据库租约
  ├─ SQLite：LangGraph checkpoint
  └─ Redis：类型化地图检索缓存
  ▼
Vue Result：行程、预算、天气、来源、告警、编辑、地图、导出
~~~

核心源码地图：

| 层 | 文件 | 重点 |
| --- | --- | --- |
| API | backend/app/api/routes/trip.py | 创建、读取、恢复、更新 |
| 模型 | backend/app/models/schemas.py | TripRequest、TripPlan |
| 约束 | backend/app/services/constraint_service.py | 显式字段优先 |
| 工作流 | backend/app/workflows/trip_workflow.py | State、节点、分支 |
| 检索 | backend/app/services/retrieval_service.py | 并发和部分失败 |
| 工具 | backend/app/services/tool_runtime.py | MCP、超时、重试、清理 |
| Planner | backend/app/agents/trip_planner_agent.py | 候选 ID 与水合 |
| 路线 | backend/app/services/route_service.py | 有界矩阵与稳定排序 |
| 预算 | backend/app/services/budget_service.py | 已知/未知费用 |
| 校验 | backend/app/services/validation_service.py | error/warning |
| RAG | backend/app/services/rag_service.py | 来源、适用期、可信状态 |
| 状态 | backend/app/services/persistence_service.py | 乐观锁与租约 |
| checkpoint | backend/app/services/checkpoint_service.py | 序列化与恢复 |
| 前端 | frontend/src/views、frontend/src/services/api.ts | 用户闭环 |
| 测试 | backend/tests、frontend/e2e | 风险验证 |

## 3. 输入与约束

TripRequest 限制城市、日期、人数、预算、必去/避开地点、步行上限和单段交通上限。日期和冲突在进入 LLM 前校验：

~~~python
calculated_days = (self.end_date - self.start_date).days + 1
if calculated_days < 1:
    raise ValueError("end_date must not be earlier than start_date")
if calculated_days > 30:
    raise ValueError("trip duration must not exceed 30 days")
if self.travel_days is not None and self.travel_days != calculated_days:
    raise ValueError("travel_days must match start_date and end_date")
~~~

内部 TravelConstraints 是冻结模型。显式表单字段优先于语义提取：

~~~python
def _prefer_explicit(explicit, extracted, default=None):
    if explicit is not None:
        return explicit
    if extracted is not None:
        return extracted
    return default
~~~

自由文本先调用 /api/trip/extract 形成预览，用户确认后才填补空白字段。这是 human-in-the-loop，模型不能偷偷覆盖明确预算或人数。

需要掌握：

1. API 输入和内部约束为何分开。
2. 语义提取为何不能覆盖显式字段。
3. must_visit 与 avoid_places 冲突为何在 LLM 前拒绝。

练习：增加“每天最晚结束时间”时，先改 Pydantic 与 Validator，再改 Prompt。

## 4. LangGraph 只做编排

TripWorkflowState 保存一次请求的图状态：

~~~python
class TripWorkflowState(TypedDict):
    constraints: TravelConstraints
    status: Literal[
        "planning", "routing", "budgeting",
        "validating", "replanning", "completed", "failed",
    ]
    plan: TripPlan | None
    error: AppError | None
    retrieval: TripRetrievalResult | None
    evidence: tuple[TravelEvidence, ...]
    violations: tuple[PlanViolation, ...]
    replan_attempts: int
~~~

~~~text
START → plan → route → budget → validate
                               ├─ completed → END
                               ├─ replan → route
                               └─ failed → failure → END
~~~

设计理由：

- plan 允许 LLM 组合候选。
- route、budget、validate 可独立测试和重跑。
- 只有 error 触发 Replan，warning 留给用户。
- max_replan_attempts 默认 1，避免无限循环。
- 每个请求有独立 state，不共享全局聊天历史。
- checkpoint 恢复已提交节点；正在执行的节点仍可能重试，所以是 at-least-once。

为什么不做多 Agent：天气、POI、路线和预算没有独立人格需求，它们是工具或确定性服务。拆成 Agent 会增加 Prompt、状态同步、不可预测性和成本。

## 5. 并发检索与 MCP Runtime

TripRetrievalService 将景点、酒店和天气组成任务，并发上限为 3：

~~~python
quota = asyncio.Semaphore(3)

async def run(job):
    with anyio.fail_after(self._timeout):
        async with quota:
            return await job()

results = await asyncio.gather(
    *(run(job) for _, job in jobs),
    return_exceptions=True,
)
~~~

- timeout 包含本地排队。
- return_exceptions=True 允许天气或酒店失败时保留其他结果。
- 景点为空会抛 NoCandidates，绝不虚构成功。

ToolRuntime 负责工具 schema、Pydantic 参数白名单、独立 MCP 会话、单次超时、总截止时间、有限重试、并发配额、取消传播和子进程清理。

高德 MCP 固定为 amap-mcp-server 0.1.11。POI 搜索需补详情才能拿坐标。步行和驾车走 MCP；公交因该版本 stdout 协议缺陷使用有界高德 HTTP Service。面试时不要声称所有路线都走 MCP。

## 6. 不信任 LLM 输出

Planner 不直接输出公开 TripPlan，而是 extra=forbid 的 PlannerDraft。模型只能引用当前请求的候选 ID：

~~~text
检索候选 → A001/A002/H001 → LLM 选择 ID
         → 服务端水合名称、地址、坐标和 POI ID
~~~

未知 ID、日期错位、额外字段会失败；格式默认最多修复一次。初始规划、修复和 Replan 共用 ModelGateway 调用预算。

Structured Output 只保证形状，不保证事实。候选引用保证身份，服务端水合保证来源，Validator 保证业务规则。

## 7. 路线、预算与 Validator

RouteOptimizer 每天最多处理 6 点，构建有向矩阵，以固定首点最近邻排序，并按时间、距离、原始位置稳定决策。它输出路线不可达、单段超时、每日步行超限和矩阵截断。它不是精确 TSP；前端折线也不是真实道路 geometry。

BudgetEngine：

- 门票、餐饮、交通按人数。
- 酒店按两人一间向上取整。
- 住宿夜数为天数减一。
- 0 是明确免费，null 是未知。
- 未知单价进入 unknown_items，total 只是已知合计。

PlanValidator 检查日期、预算、must/avoid、重复、路线、到访时刻、交通间隔与证据。

- error：违反硬约束，可触发有限 Replan。
- warning：信息不足或需用户确认，计划可展示但不能假装确定。

这比增加一个 Critic Agent 更可复现、可解释。

## 8. RAG 的正确用法

TravelEvidence 包含 poi_id、topic、content、source_url、captured_at、适用日期、verified/uncertain 和结构化 facts。

Validator 只用日期适用且 verified 的事实做硬判断。没查到闭园不能推导“肯定开放”。

当前语料只覆盖北京故宫主 POI 的有限日期与规则。实际票面余量、节假日例外、无障碍和更多景区尚未覆盖。

面试表述：

> 我把 RAG 输出从不可审计文本改为带 URL、抓取时间、适用期和可信状态的 TravelEvidence。只有适用的 verified 事实进入硬校验，缺失证据降级为 warning。

## 9. 持久化与恢复

MySQL PlanStore 保存业务状态、请求、结果、error_code、version、owner_token_hash、数据库租约和 workflow_version。SQLite 保存 LangGraph 节点执行状态。两者以相同 plan_id/thread_id 关联。

浏览器生成 32 随机字节 owner token，服务端只保存 SHA-256 摘要。这是个人应用 capability，不是账号体系。

多实例通过数据库条件 UPDATE 争用租约，LeaseGuard 定时续租；崩溃后可在 TTL 到期接管。租约防并发推进，不保证外部调用 exactly-once。

Alembic 0001_plan_ownership 支持新表与旧表升级。workflow_version 不兼容返回 409。cleanup_state 只删除过期 completed/failed 及 checkpoint，支持 dry-run。

## 10. API 与前端闭环

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | /api/trip/plan | 创建计划 |
| POST | /api/trip/extract | 提取预览 |
| GET | /api/trip/plans/{plan_id} | 查询状态 |
| POST | /api/trip/plans/{plan_id}/resume | 恢复 |
| PUT | /api/trip/plans/{plan_id} | 乐观锁更新 |
| GET | /api/trip/health | 配置检查 |

浏览器在请求前保存恢复 ID 和 owner token。网络错误、超时或 5xx 保留 pending ID；刷新可检查并恢复。PUT 携带 expected_version，后端重算路线、预算并复验，版本冲突不会静默覆盖。

结果页支持行程、天气、预算、来源、warning、地图、时刻编辑、PNG 与 PDF。

## 11. 测试地图

| 风险 | 代表测试 |
| --- | --- |
| 输入约束 | test_phase2_constraints.py |
| 图分支 | test_phase3_workflow.py |
| 并发/部分失败 | test_phase4_retrieval.py |
| MCP 超时/清理 | test_phase5_runtime.py、test_phase5_stdio.py |
| Redis | test_phase6_cache.py、test_phase6_redis.py |
| 持久化/乐观锁 | test_phase7_persistence.py |
| 预算 | test_phase8_budget.py |
| 路线 | test_phase9_routes.py |
| 候选 ID | test_phase10_planner.py |
| Validator/Replan | test_phase11_validator.py |
| RAG | test_phase12_rag.py、test_phase25_palace.py |
| 模型网关 | test_phase13_model_gateway.py |
| 时间窗 | test_phase19_time_windows.py |
| 供应商适配 | test_phase20_coordinate_routes.py、test_phase21_live_reliability.py |
| 文本提取 | test_phase24_extraction.py |
| checkpoint | test_phase26_checkpoint.py |
| 网页恢复 | test_phase28_web_recovery.py |
| 迁移/所有权/租约 | test_phase29_state_security.py |
| 浏览器 | frontend/e2e/trip.spec.ts |

CI 使用 Python 3.10 和 Node 22，运行后端全量测试、前端构建和 Playwright。

## 12. 14 天掌握计划

- 第 1–2 天：跑测试，读 README、progress、spec，手画请求链路。
- 第 3–4 天：读 schemas、constraint，构造无效请求，理解 null 和 0。
- 第 5–6 天：读 workflow、planner，画条件边，解释候选 ID 与 Replan。
- 第 7–8 天：读 retrieval、runtime、amap，理解超时、重试和部分失败。
- 第 9–10 天：读 route、budget、validator、rag，追踪一个 violation。
- 第 11–12 天：读 trip API、PlanStore、checkpoint、migration，画恢复过程。
- 第 13 天：读 Vue、api.ts、Compose、Nginx、CI，跑 Playwright。
- 第 14 天：做 8 分钟项目介绍、两个失败案例和一个架构取舍。

每阶段验收：离开文档口述，并定位到真实源码和测试。

## 13. 简历写法

项目名：

**TripPilot｜约束驱动、可验证、可恢复的旅行规划 Agent**

建议四条：

- 基于 FastAPI、LangGraph 和 Pydantic 构建 plan → route → budget → validate → bounded replan；LLM 只生成候选 ID 草稿，地点身份由服务端水合。
- 设计 MCP Tool Runtime，支持 schema/参数校验、单次与总超时、有界重试、并发配额、部分失败和子进程清理；Redis 仅缓存类型化地图事实。
- 用确定性 Python 实现路线矩阵、稳定排序、预算、时间窗和硬约束 Validator；仅带来源、抓取时间、适用期和可信状态的 RAG 证据参与硬判断。
- 用 MySQL、Alembic、乐观锁、capability token、数据库租约和 SQLite checkpoint 实现网页恢复；建立 212 passed、2 skipped 后端回归、10 项 Playwright、Docker Compose 与 GitHub Actions。

数字必须随 docs/progress.md 更新。不得把约束层 P50/P95 写成全链路性能，不得编造 token、成本、命中率或线上成功率。

## 14. 8 分钟面试结构

1. 问题：普通旅行 Agent 会幻觉事实、算错预算且不可复现。
2. 架构：Vue → FastAPI → Constraints → Graph → Retrieval/RAG → Draft → Route/Budget/Validator。
3. 可信输出：候选 ID、extra=forbid、服务端水合。
4. 可靠工具：MCP timeout、retry、partial failure、Redis。
5. 硬约束：路线、预算、时间窗、证据与有限 Replan。
6. 恢复：业务表、checkpoint、owner token、数据库租约、at-least-once。
7. 验证：212 passed、2 skipped、10 项浏览器、容器迁移、远端 CI。
8. 反思：官方语料、真实供应商评测、账号和网络 checkpoint。

## 15. 高频问答

**为什么 LangGraph？**
流程需要显式状态、条件分支、有限 Replan 和 checkpoint。

**为什么还要 Validator？**
结构化输出只保证形状，不保证预算、路线、日期和证据满足规则。

**如何防地点幻觉？**
模型只返回请求内候选 ID，未知 ID 被拒绝，服务端水合真实 POI。

**Redis 挂了怎么办？**
连接失败、超时或缓存损坏会回源。

**checkpoint 保证 exactly-once 吗？**
不保证。执行中崩溃可能重试；租约只避免并发推进。

**为什么不是生产级多用户系统？**
owner token 没有账号找回、撤销和设备同步；SQLite 是单节点 checkpoint。

## 16. 推荐演示

稳定离线演示顺序：

1. Phase 10：未知候选 ID 被拒绝。
2. Phase 11：硬约束触发有限 Replan。
3. Phase 28：中断恢复且 Planner 不重复。
4. Phase 29：owner token、数据库租约和清理。
5. Playwright：创建、错误、编辑、导出和恢复。

真实配置演示要准备供应商失败预案，展示安全 error_code 和 request_id，不把一次成功当线上指标。

## 17. 能力边界

已具备 FastAPI、Vue、LangGraph、MCP、Redis、MySQL、Alembic、RAG、Docker、CI，类型边界、确定性硬约束、并发检索、网页恢复和小样本真实记录。

仍缺更多官方语料、真实票务预约、真实供应商浏览器 E2E、大样本评测、可审计 token/成本、统一取消，以及公网账号与网络 checkpoint store。

真正掌握项目的标准，是能从一个用户约束追踪到最终 violation，解释每个不确定性为何没有被伪装成事实，并用测试证明结论。
