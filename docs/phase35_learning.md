# TripPilot Phase 35 学习文档：让代码做时间运算，让 LLM 做规划选择

## 1. 从两轮 violation 看职责边界

西安案例首轮同时出现 `SEGMENT_TIME_EXCEEDED` 和 `VISIT_TIME_CONFLICT`，有限重规划后交通超限消失，但时间冲突仍存在。说明模型可以根据反馈更换景点或顺序，却不擅长稳定计算“前一景点结束时间 + 真实交通秒数”。

时间加减属于确定性业务，应该由 Python 处理。LLM 输出的时刻可以作为偏好草稿，但不能直接当作已满足路线约束的事实。

## 2. 顺延规则

路线阶段已经拥有：

- 按天排序后的景点；
- 每个景点的 `visit_duration`；
- 每条相邻路线的真实 `duration`。

因此代码可以计算：

~~~python
travel_minutes = (travel_seconds + 59) // 60
earliest = previous_end + timedelta(minutes=travel_minutes)
start = max(model_start, earliest)
end = start + timedelta(minutes=visit_duration)
~~~

交通秒数向上取整，避免 901 秒被当成 15 分钟而少留时间。后续景点只向后移动，不提前于模型建议时刻。

## 3. 哪些情况不能自动修

路线不可用时 `duration=None`，代码不会猜测；顺延跨越午夜时也不把第二天时间回绕成当天凌晨。营业时段仍必须由带来源的证据校验。自动顺延只修复算术冲突，不替代路线事实或营业规则。

## 4. 测试设计

正例设置第一站 09:00–11:00、第二站模型建议 11:05、真实交通 901 秒。向上取整后第二站应为 11:16–12:16。反例使用不可用路线，证明代码不会生成虚假的交通时长。

专项测试 32 passed；完整后端回归 222 passed、2 skipped。

## 5. 面试讲法

“我比较了同一真实请求两轮 Validator 日志：重规划消除了交通超限，却连续留下到访时间冲突。于是把责任从 Prompt 移到 RouteOptimizer：模型决定景点，代码用真实路线时长向上取整并顺延时刻，Validator 再检查营业时间和硬约束。这样减少无效 LLM 重试，也让时间结果可测试、可复现。”
