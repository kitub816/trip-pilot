# Phase 19：到访时间窗与确定性冲突校验

完成日期：2026-09-19。

Attraction 和私有 PlannerDraft 增加可选的 visit_start/visit_end（同一天当地时间）；必须成对提供。Planner Prompt 要求给出到访区间，服务端从草稿水合到 TripPlan。已有到访时刻的日行程在 RouteOptimizer 中保留景点顺序，避免重新排序使时刻失效。PlanValidator 用确定性代码检查倒置/跨日时段、游览时长，以及相邻景点之间是否留足实际 RouteLeg.duration。部分景点缺时刻时给 warning；完全没有时刻的历史计划保持兼容，不声称经过时段验证。PUT 仍经路线、预算与 Validator 复验。前端结果页显示并允许编辑时刻。

修改：backend/app/models/schemas.py、backend/app/models/planner.py、backend/app/models/validation.py、backend/app/agents/trip_planner_agent.py、backend/app/services/route_service.py、backend/app/services/validation_service.py、backend/tests/test_phase19_time_windows.py、frontend/src/types/index.ts、frontend/src/views/Result.vue、README.md、docs/progress.md、docs/refactor_plan.md、docs/phase19.md。

验证：后端全量离线回归 161 passed、2 skipped、10 warnings；前端生产构建通过，仍有大包警告。新增测试覆盖合法时间间隔、缺失端点、游览时长不足、跨日及交通间隔不足、固定时刻保序。没有真实景区开放时间或预约语料，因此只验证计划内部时间可行性，不能声称景区营业时段或预约冲突已被检查。
