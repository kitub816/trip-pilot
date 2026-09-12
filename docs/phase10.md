# Phase 10：Structured Planner

完成日期：2026-09-11。

## 本阶段目标

收紧 Planner LLM 的输入输出边界：模型只能从检索 Service 提供的候选 ID 中选择景点和酒店，输出先经过独立 Pydantic schema、日期序列与引用校验，再由服务端水合成公开 `TripPlan`。解析失败只允许一次格式修复，不恢复虚构 fallback。

## 实现结果

### 1. 私有 LLM 输出模型

新增 `models/planner.py`，定义 `PlannerDraft`、`PlannerDay`、`PlannerAttractionSelection`、`PlannerHotelSelection` 和 `PlannerMeal`。全部模型使用 `extra="forbid"`，限制字符串、数组、费用和游览时间边界；每天必须有 1–3 个景点，并恰好包含一次早餐、午餐和晚餐。

私有草稿不允许输出 `city`、起止日期、天气、路线或预算，也不允许景点/酒店名称、地址和坐标。它们不是 LLM 可决定的字段。

### 2. 稳定候选 ID 与可信水合

检索结果按稳定顺序映射为 `A001...` 和 `H001...`，Prompt 只要求引用这些请求内 ID。解析成功后，服务端用 catalog 找回原始 `POIInfo`：

- 景点名称、类型、地址、坐标和高德 POI ID 来自检索结果；
- 酒店名称、类型、地址和坐标来自检索结果；
- 城市、起止日期和日期序列来自 `TravelConstraints`；
- 天气来自 Retrieval Service，并只保留请求日期范围内的数据；
- LLM 只提供选择、描述、游览时长和可空单价线索。

未知景点或酒店 ID 会返回 `PLAN_PARSE_ERROR`，不会把模型自造实体放进正式计划。

### 3. 严格日期和格式校验

草稿天数必须等于请求天数。第 N 个元素必须同时满足 `day_index == N` 和 `date == start_date + N天`。少一天、越界日期或错位索引均被拒绝。

解析只接受单个 JSON 对象；兼容整个响应由一层 Markdown JSON 围栏包裹，但不再从任意说明文字中截取首尾大括号。默认响应上限 50,000 字符，避免无界解析。

### 4. 有界格式修复

默认 `PLANNER_REPAIR_ATTEMPTS=1`。第一次响应无效时，同一 Planner Agent 收到固定修复指令；第二次仍无效便返回 `PLAN_PARSE_ERROR`。配置允许 0–2 次，默认只多消耗一次 LLM 调用。请求结束后继续清空 Agent history，进程内互斥语义不变。

修复只重新生成符合 schema 的草稿，不绕过候选、日期或字段校验。

### 5. Prompt 职责调整

Prompt 不再要求模型填写“真实准确”的经纬度、复制天气或汇总预算。它明确规定候选引用、请求日期序列、每日景点数量、三餐和无酒店候选时的 null。route 与 budget 继续由后续确定性 LangGraph 节点生成。

## 修改文件

- `backend/app/models/planner.py`：私有 Planner Pydantic schema。
- `backend/app/agents/trip_planner_agent.py`：候选 catalog、严格解析、可信水合和有限修复。
- `backend/app/config.py`、`backend/.env.example`：修复次数和响应长度上限。
- `backend/tests/test_phase10_planner.py`：13 项专项测试。
- `backend/tests/test_phase1.py`：将旧 LLM 测试夹具更新为新候选 ID 草稿，不改变原生命周期断言。

## 架构变化

当前核心链路为：

`Retrieval POI/Weather → 请求内 Candidate Catalog → PlannerDraft → Pydantic/引用/日期校验 → TripPlan 水合 → RouteOptimizer → BudgetEngine`

`PlannerDraft` 是不可信 LLM 边界，`TripPlan` 是经过服务端事实水合后的领域对象。LangGraph 节点顺序仍为 `plan → route → budget`。

## 验证结果

- Phase 10 与 Planner/约束相关测试：**65 passed**。
- `python -m pytest tests -q`：**136 passed，2 skipped，10 warnings**。
- `git diff --check`：通过。

专项测试覆盖稳定作用域 ID、可信字段水合、未知景点/酒店 ID、天数/日期/索引、额外字段注入、三餐约束、超长响应、说明文字包裹、一次修复成功、修复上限和 Prompt 限制。没有调用真实 LLM、高德或 Unsplash。

## 遗留问题

- Planner 仍通过同步 HelloAgents `SimpleAgent` 调用，共享实例用进程内互斥拒绝并发规划。
- 结构化输出由 Prompt + JSON + Pydantic 实现，尚未通过统一 Model Gateway 使用 provider 原生 JSON Schema。
- 单价、游览时长、描述、餐饮和建议仍是 LLM 线索，没有 RAG 证据或确定性真实性校验。
- 候选总数尚未设置独立 Prompt 上限；复杂偏好可能增加上下文长度。
- 重复景点、must/avoid、路线失败、预算超限和时间冲突尚未汇总为 Validator violations，也不会触发 Replan。
- 修复调用没有独立 token/费用总预算和全请求截止时间；Phase 13 Model Gateway 仍需统一处理。
- 当前没有使用真实 LLM 验证 schema 遵循率，因此不能声明计划生成成功率改善。

## 下一阶段建议

Phase 11 实现确定性 Validator + 有上限 Replan。把预算、必去/避开、重复、日期、路线不可达、单段交通和每日步行等结果统一为类型化 violations；LangGraph 依据 violations 分支，达到最大轮数或无解时明确终止。
