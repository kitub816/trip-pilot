# Phase 35：按实测交通时间确定性顺延到访时刻

完成日期：2026-09-28。

## 完成内容

西安 3 天真实网页案例在有限重规划后仍返回 `PLAN_VALIDATION_ERROR`。同一请求首轮出现 `SEGMENT_TIME_EXCEEDED` 与 `VISIT_TIME_CONFLICT`；第二轮已消除交通时长超限，但仍保留 `VISIT_TIME_CONFLICT`。这证明 LLM 能重新选点，却不能稳定完成精确时间运算。

路线计算现在根据实测相邻路段时长确定性调整到访窗口：保留首个景点开始时间，按 `visit_duration` 计算结束时间；后续景点开始时间不得早于前一景点结束时间加向上取整到分钟的真实交通时间，再按游览时长计算结束时间。路线时长未知时不编造，跨越午夜时不强行回绕，继续交给 Validator 拒绝。

## 修改文件

- `backend/app/services/route_service.py`
- `backend/tests/test_phase35_schedule_alignment.py`
- `README.md`
- `docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`
- `docs/TripPilot使用手册.md`、`docs/研二Agent实习项目学习教程.md`
- `docs/phase35_learning.md`
- `E:\TP各版本文档\35\学习文档.md`

## 架构变化

LLM 仍负责选点、顺序和软性描述；RouteOptimizer 在拿到供应商路线后负责确定性时间运算；Validator 继续校验交通上限、游览时长、营业时间和证据。没有新增 Agent，也没有放宽任何硬约束。

## 验证

- 时间顺延、时间窗、路线和 Validator 专项：32 passed、1 条第三方 warning。
- 后端完整离线回归：222 passed、2 skipped、1 条 HelloAgents 第三方 warning。
- 本地后端重启后 `/api/trip/health` 返回 HTTP 200。

## 遗留问题

- 本阶段没有替用户再次发起真实 LLM 规划，不能声称西安完整案例已经成功。
- 若确定性顺延导致跨越午夜或违反有来源的营业时间，计划仍会失败。
- 缺少路线时不会估算交通时间；对应路线不可用仍按既有规则处理。

## 下一阶段建议

用户用相同西安输入复测网页案例；若仍失败，根据新的类型化 violation 修复具体业务规则，不降低硬约束。
