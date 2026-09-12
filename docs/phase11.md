# Phase 11：Validator + Replan

完成日期：2026-09-12。

## 本阶段目标

在 Route Optimizer 与 Budget Engine 之后增加确定性 Validator。把能由当前类型化计划和约束证明的硬约束转为结构化 violations，并让 LangGraph 在首次违规时进行一次有上限的 Replan；再次违规或无法重规划时明确失败，不返回看似成功的无效计划。

## 实现结果

### 1. 类型化 validation 结果

新增 `PlanViolation` 与 `PlanValidationResult`。每条 finding 包含受限的 code、`error / warning` 严重度、可选 day_index 与 subject；只把 `error` 视为阻断条件。

当前支持：

- `PLAN_DAY_COUNT_MISMATCH`、`PLAN_DATE_MISMATCH`
- `BUDGET_MISSING`、`BUDGET_EXCEEDED`、`BUDGET_INCOMPLETE`
- `MUST_VISIT_MISSING`、`AVOID_PLACE_INCLUDED`、`DUPLICATE_ATTRACTION`
- `ROUTE_MISSING`、`ROUTE_UNAVAILABLE`、`SEGMENT_TIME_EXCEEDED`、`DAILY_WALKING_EXCEEDED`、`ROUTE_MATRIX_TRUNCATED`

预算未知和路线矩阵截断是 warning：它们说明证据不完整或优化范围受限，但当前代码不能证明一定违反预算或路线限制。其余已知违规是 error。

### 2. 确定性 Validator

`PlanValidator` 复用 `TravelConstraints`、BudgetEngine 的预算结果和 RouteOptimizer 的 `DayRoute` 告警：

- 日期数量、索引和连续日期必须匹配请求；
- 有预算上限时，已知总额超过上限即失败；
- must visit 用大小写无关的包含匹配检查，avoid place 在任一景点匹配即失败；
- 以 POI ID 优先、名称回退方式检测跨天重复景点；
- 读取路线结果标记不可达、单段交通超限和每日步行超限；多景点日缺少 route 也失败。

`validate_or_raise` 用安全的 `PLAN_VALIDATION_ERROR`（HTTP 422）终止 API 更新，不把原始模型输出或用户内容暴露到错误响应。

### 3. LangGraph 分支和 Replan 上限

工作流从：

`plan → route → budget → END`

变为：

```text
plan → route → budget → validate ──有效──→ END
                              │
                              ├─ 首次 error → replan → route
                              │
                              └─ 已达上限/无法重规划 → failure → END
```

`MAX_REPLAN_ATTEMPTS` 默认 1，允许 0–2。Replan 复用同一批 Retrieval 候选和天气，只把类型化 violations JSON 追加到 Structured Planner 查询中；模型仍只能选择 `A001/H001` 候选，之后再次经过 route、budget 与 validate。不会无限重新调用 LLM。

route 或 budget 节点自身返回失败状态时，现在也会直接进入 `failure`，不会继续流向后续节点。

### 4. 计划更新复验

PUT `/api/trip/plans/{plan_id}` 的顺序现在是：

`客户端 TripPlan → RouteOptimizer → BudgetEngine → PlanValidator → PlanStore.replace`

校验失败时不会调用 `replace`，旧版本保持不变。编辑接口不会暗中触发 LLM Replan，避免把用户的显式编辑变成不可预期的模型改写。

## 修改文件

- `backend/app/models/validation.py`：violation 与结果模型。
- `backend/app/services/validation_service.py`：确定性约束检查。
- `backend/app/workflows/trip_workflow.py`：validate/replan/failure 图分支和 state。
- `backend/app/agents/trip_planner_agent.py`：把类型化 violations 传给重规划查询。
- `backend/app/api/routes/trip.py`：PUT 重算后复验。
- `backend/app/errors.py`、`backend/app/config.py`、`backend/.env.example`：安全错误与 Replan 上限。
- `backend/tests/test_phase11_validator.py`：11 项专项测试；同步更新旧工作流/API/持久化夹具的依赖注入。

## 验证结果

- `python -m pytest tests/test_phase11_validator.py -q`：**11 passed**。
- `python -m pytest tests -q`：**147 passed，2 skipped，10 warnings**。
- `git diff --check`：通过。

专项测试覆盖无违规、预算超限与未知项、must/avoid/重复、日期数量与序列、路线告警、缺失路线、安全异常、实际 Planner 修正规则、一次成功 Replan、达到上限终止，以及 PUT 在写入前复验。未调用真实 LLM、高德或 Unsplash。

## 架构变化

验证从散落在 Prompt、Route Optimizer 和 Budget Engine 中的局部信号，提升为工作流中的明确决策节点。LLM 只接收已结构化的 error findings 并提出新草稿；所有硬约束仍由 Python 再次计算和确认。

## 遗留问题

- DayPlan 尚无访问开始/结束时段，候选也没有可靠开放时间、预约或节假日数据，不能校验时间冲突和开放时间；这些属于 Phase 12 RAG 的输入条件。
- must/avoid 使用名称包含匹配，名称歧义可能造成误判；未来应优先使用用户选择或检索候选的稳定 POI ID。
- 预算未知与矩阵截断目前只警告，不会触发 Replan；前端尚未展示 warnings 或 violations。
- Replan 复用候选但尚未把当前路线摘要、预算明细和修改差异作为更精细的重规划上下文。
- Planner 同步调用、候选 Prompt 数量、LLM token/成本与全请求 deadline 仍未被统一 Model Gateway 管理。
- Violation 目前仅保存在请求级 LangGraph state；没有持久化到 MySQL，也没有节点级指标或 tracing。

## 下一阶段建议

Phase 12 接入旅行 RAG：围绕候选 POI ID 收集官方开放时间、预约、规则和无障碍证据，记录来源、抓取时间和适用日期。Validator 只在有真实证据时检查开放约束；缺证据应表达不确定，不应假定景点开放。
