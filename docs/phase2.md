# Phase 2：Constraint Engine

## 请求兼容与新增字段

`POST /api/trip/plan` 继续接受原前端字段。`travel_days` 现在可省略；服务端始终按首尾日期（含首尾两天）推导天数。旧客户端仍可发送该字段，但值必须与日期一致。

新增的结构化可选约束：

| 字段 | 含义 | 边界 |
| --- | --- | --- |
| travelers | 出行人数 | 1–20，默认 1 |
| budget_limit | 整次行程总预算上限 | 大于 0，最多两位小数 |
| currency | 预算币种 | 当前仅 CNY |
| must_visit | 必须安排的地点 | 最多 30 项 |
| avoid_places | 禁止安排的地点 | 最多 30 项，不能与 must_visit 重叠 |
| max_daily_walking_km | 每日步行距离上限 | 0–100 公里，不含 0 |
| max_single_transport_minutes | 单段交通时间上限 | 1–720 分钟 |

交通和住宿采用枚举，值与现有前端四个选项一致。城市不能为空；行程最多 30 天；反向日期和不一致天数返回统一 422 错误。地点及偏好必须是字符串数组，会去除首尾空白并按大小写不敏感方式去重。

## 确定性合并规则

`build_travel_constraints` 把 `TripRequest` 转为不可变的 `TravelConstraints`。可选的 `ExtractedConstraints` 是未来语义提取器的输入边界，规则固定为：

1. 用户显式结构化字段优先，包括显式空列表。
2. 提取结果只填补未提供字段。
3. 两者都缺失时使用确定性默认值。
4. 合并后再次校验必去/避开冲突和数值范围。

`free_text_input` 保留给 Planner；本阶段不会用字符串匹配猜预算或地点，也没有新增 LLM 调用。`requires_semantic_extraction` 只标识是否存在待语义理解文本，后续接入提取器时可据此跳过空文本调用。

## 当前请求链

```text
TripRequest（API 校验、日期推导）
  → build_travel_constraints（规范化、显式字段优先、冲突校验）
  → TravelConstraints（不可变）
  → 现有 MultiAgentTripPlanner
```

Planner Prompt 已接收人数、预算上限、必去/避开、步行及交通上限，但这些约束尚未由最终 Validator 强制验证。预算计算属于 Phase 8，LangGraph 工作流属于 Phase 3。

## 验证

在 `backend` 下运行 `python -m pytest tests -q`；在 `frontend` 下运行 `npm run build`。本阶段完成时后端 55 项通过，前端类型检查和生产构建通过。测试无外部网络调用。
