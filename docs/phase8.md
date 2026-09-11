# Phase 8：确定性 Budget Engine

完成日期：2026-09-11。

## 目标与范围

本阶段把费用汇总从 Planner LLM 移到确定性 Python 服务。LLM 仍可提供景点、餐饮、酒店和每日交通单价；无法确认时输出 null。Budget Engine 按结构化人数、房间数和住宿夜数计算，并覆盖模型自报的预算汇总。

## 计算规则

- 门票：每人单价 × travelers，按实际日程中的景点逐项累加。
- 餐饮：每人单价 × travelers，按实际日程中的餐饮逐项累加。
- 交通：新增 `DayPlan.transportation_cost`，含义为当日每人费用，再乘 travelers。
- 酒店：每间每晚单价 × `ceil(travelers / 2)`；住宿夜数固定为 `max(travel_days - 1, 0)`，最后一天即使模型重复给出酒店也不收费。
- 0 表示明确免费，null 表示未知。未知项不计入已知小计，并写入带 category、day_index、item_name 的 `unknown_items`。
- `within_limit` 是三态：未指定上限为 null；已知小计已经超限为 false；费用完整且未超限为 true；仍有未知费用且已知小计未超限为 null。

所有金额当前以整数 CNY 表示。`Budget.total` 必须由四类已知小计相加得到。

## 架构变化

工作流由 `START → plan → END` 扩展为：

```text
START → plan ─成功→ budget → END
             └失败→ failure → END
```

`plan` 节点返回 `budgeting`，独立的 `BudgetEngine.apply()` 使用 `model_copy` 生成带确定性预算的新 TripPlan。规划 API 持久化的是 budget 节点之后的结果。计划 PUT 更新也会使用原始 TripRequest 重新构建 TravelConstraints 并重算预算，客户端无法提交自定义总价覆盖服务端结果。

Planner Prompt 删除预算汇总要求，增加每日交通单价，并要求无法确认的单价使用 null。这样减少 LLM 不擅长且无法验证的算术工作。

## 模型变化

- Attraction.ticket_price、Meal.estimated_cost、Hotel.estimated_cost 从默认 0 改为非负可空值。
- DayPlan 增加非负可空 `transportation_cost`。
- Budget 增加 currency、travelers、rooms、accommodation_nights、is_complete、within_limit 和 unknown_items；原五个总计字段保持兼容。
- 所有单价拒绝负数。

## 验证

`backend: python -m pytest tests -q`：**111 passed，2 skipped，10 warnings**。

新增测试覆盖三人两间房、三天两晚、末日酒店不计费、每人费用乘人数、0 与 null 的区别、四类未知项、预算上限三态、单日零住宿夜、负数拒绝、输入 TripPlan 不被原地修改，以及 LangGraph 覆盖 LLM 自报总价。

没有使用真实 LLM，也没有声称当前单价来源准确。预算算术正确不等于费用信息完整。

## 已知边界

- 当前默认每间房容纳 2 人，没有儿童、单人房、加床、税费、服务费或多币种规则。
- 交通只有每日总单价，尚未由 Phase 9 路线段推导。
- LLM 提供的单价缺少证据来源；Phase 12 RAG 之前只能通过 `unknown_items/is_complete` 表达不确定性。
- 前端旧预算卡仍只显示已知小计，没有展示 unknown_items 和 within_limit；安排在 Phase 16 修正。
- Phase 11 Validator 尚未根据 within_limit 对工作流进行 replan 或无解终止。
