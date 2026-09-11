# Phase 9：确定性 Route Optimizer

完成日期：2026-09-11。

## 本阶段目标

把每日景点的路线查询、顺序优化和硬约束检查从 Planner LLM 输出中拆出，交给确定性 Python 服务。复用 Phase 5 已验证的 `AmapService.aplan_route`，不新增 Route Agent，也不让 LLM 计算距离和时间。

## 实现结果

### 1. 类型化路线结果

`RouteLeg` 记录起终点、米制距离、秒制时长、交通方式和 `available / unavailable / over_time_limit` 状态；`DayRoute` 汇总每日距离、时间、完整性、约束状态和类型化告警。`DayPlan.route` 为可选字段，保持旧计划数据兼容。

### 2. 有界有向路线矩阵

`RouteOptimizer` 每天最多处理前 6 个景点，最多产生 `6 × 5 = 30` 次有向路线查询。默认并发为 3，并进一步受全局 Tool Runtime 并发配置约束；单路段超时 60 秒，每日矩阵总超时 90 秒。每天顺序执行，日内矩阵并发，避免多个日期同时放大外部工具压力。

每次查询失败或超时只把对应边记为不可达，其他边仍可继续使用。请求取消会继续向上传播；矩阵总超时会取消尚未结束的任务并等待清理。

### 3. 可复现的每日排序

首个景点保持不变，之后按最近邻启发式选择下一站。排序键依次是：是否超过单段交通上限、时长、距离、原始位置、名称。相同输入和相同矩阵得到相同顺序，且优先选择满足单段时间上限的路线。

这不是全局最短路或 TSP 最优解。超过矩阵上限的景点保留原始尾部顺序，并标记 `MATRIX_TRUNCATED`。

### 4. 交通模式与硬约束

- 步行映射为 `walking`，自驾映射为 `driving`，公共交通映射为 `transit`。
- 当前高德接口不支持一次查询组合多种方式，因此“混合”暂以 `transit` 作为确定性回退。
- 不可达路段输出 `ROUTE_UNAVAILABLE`，不伪造距离或时间。
- 超过单段交通分钟数输出 `SEGMENT_TIME_EXCEEDED`。
- 步行路线总距离超过每日步行公里数时输出 `DAILY_WALKING_EXCEEDED`。
- `is_complete` 描述路线数据是否完整，`within_limits` 描述已知路线是否满足限制，两者分开表达。

### 5. 工作流和编辑链路

LangGraph 主链改为：

`START → plan → route → budget → END`

路线节点先重排景点并补充路线汇总，预算节点随后重新计算费用。计划 PUT 更新同样执行路线优化和预算重算，避免客户端编辑后保留过期的派生数据。

## 修改文件

- `backend/app/services/route_service.py`：路线矩阵、并发/超时、排序、路线汇总和告警。
- `backend/app/models/schemas.py`：新增 `RouteLeg`、`DayRoute`，扩展 `DayPlan`。
- `backend/app/workflows/trip_workflow.py`：加入 route 节点和 routing 状态。
- `backend/app/api/routes/trip.py`：PUT 更新后重新计算路线与预算。
- `backend/app/config.py`、`backend/.env.example`：路线规模、并发及超时配置。
- `backend/tests/test_phase9_routes.py`：12 项专项测试。

## 验证结果

- `python -m pytest tests/test_phase9_routes.py -q`：**12 passed**。
- `python -m pytest tests -q`：**123 passed，2 skipped，10 warnings**。
- `git diff --check`：通过。

测试使用固定 RouteProvider，没有访问真实高德网络。覆盖有向矩阵、确定性顺序、四种交通输入、矩阵规模、并发上限、不可达降级、单段时间、每日步行距离、调用取消、矩阵总超时和工作流节点顺序。

## 架构变化

路线从 Planner 生成内容变成 Route Service 的派生数据。LLM 仍选择景点和生成叙述，确定性代码负责查询真实路段、排序、合计与硬约束标记。现有 AmapService、Tool Runtime、Redis 路线缓存和 Pydantic `RouteInfo` 均得到复用。

## 遗留问题

- 最近邻只保证确定性和低复杂度，不保证全局最优；也未支持用户指定固定中间点或时间窗。
- “混合交通”尚未逐段比较多种方式。
- 没有路线几何数据，前端不能把景点直线连接解释为真实路网。
- 路线失败不会触发重新选点；应由后续 Validator + Replan 统一处理。
- 交通费用仍来自计划单价，没有依据路线里程、时长或票价生成。
- 每日矩阵有截止时间，但整个规划请求尚无统一总截止时间。

## 下一阶段建议

Phase 10 改造 Structured Planner：约束模型只能从候选 ID 中选择景点，按明确 schema 返回计划；拒绝非法 JSON、未知 ID 和越界日期，并保留有限的格式修复次数。路线和预算继续由确定性节点覆盖，不再信任模型生成的汇总值。
