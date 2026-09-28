# Phase 34：公交空方案的实测步行回退

完成日期：2026-09-28。

## 完成内容

真实规划的两轮 LLM 草稿都成功，但同一公交路段在高德返回成功响应且 `transits=[]`，被旧代码统一映射为 `ROUTE_UNAVAILABLE`。Validator 将路线不可用视为硬错误，因而触发一次无效的 LLM 重规划，第二轮仍以 `PLAN_VALIDATION_ERROR` 结束。

公共交通行程中的相邻短途允许步行。本阶段仅在高德明确返回成功、路线结构存在且公交候选列表为空时，调用已有的坐标步行工具取得真实距离和时间。供应商错误、限流、超时、非法响应和步行查询失败仍保持失败；步行结果超过用户交通时间上限时仍由确定性 Validator 拒绝。

## 修改文件

- `backend/app/services/amap_service.py`
- `backend/tests/test_phase20_coordinate_routes.py`
- `README.md`
- `docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`
- `docs/TripPilot使用手册.md`、`docs/研二Agent实习项目学习教程.md`
- `docs/phase34_learning.md`
- `E:\TP各版本文档\34\学习文档.md`

## 架构变化

没有放宽 Validator，也没有用估算值替代路线。Amap Service 负责供应商语义适配：公交无候选时查询真实步行路线；RouteOptimizer 继续使用类型化 `RouteInfo`，预算与硬约束仍由确定性代码处理。

## 验证

- 路线解析、公交可靠性、优化和 Validator 专项：40 passed。
- 后端完整离线回归：220 passed、2 skipped、1 条 HelloAgents 第三方警告。
- 真实北京探针：天安门到故宫在公交无候选时返回 walking，1064 米、851 秒。
- 本地后端重启后 `/api/trip/health` 返回 HTTP 200。

## 遗留问题

- 本阶段没有替用户再次发起完整 LLM 规划，不能声称完整行程已经成功。
- 公交方案存在时仍使用公交最短耗时；只有明确空列表才回退步行。
- Docker Desktop 到高德的 TLS 出口问题仍未解决。

## 下一阶段建议

用同一浏览器输入重跑完整案例，确认最终路线和 Validator 结果；若仍失败，按新一轮类型化 violation 处理，不降低硬约束。
