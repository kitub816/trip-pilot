# Phase 21：北京公交失败链路修复

完成日期：2026-09-22；真实复测执行于 2026-09-20。

## 做了什么与原因

诊断复现发现公交接口返回结构化 TOOL_RATE_LIMIT，且模型为实际需要 4105 秒的路段只留下 1800 秒。旧重规划仅收到冲突码和终点，缺少可执行的交通时长反馈。

- 公交 HTTP 200 响应中的业务限流也进入有界重试：等待 1 秒，最多重试一次；持续失败仍拒绝返回虚构路线。
- 已有到访时刻的保序行程只查询相邻有向路段，三个景点从六次查询降为两次；未排时刻的行程保留矩阵优化。
- 时间冲突反馈新增起点、所需交通秒数和现有间隔秒数，经已有类型化重规划通道送给模型。
- 工作流记录校验码，真实评测汇总工具失败码和各轮校验发现，不保存密钥或原始模型响应。
- 全量回归暴露 Redis 内部超时和 asyncio 总超时的异常类型竞争，现将总超时统一为 RedisTimeoutError，保持缓存回源行为；覆盖 get/set 取消清理。

## 修改文件与架构

修改 backend/app/models/validation.py、services/amap_service.py、services/route_service.py、services/validation_service.py、services/cache_service.py、workflows/trip_workflow.py（均位于 backend/app 下）；修改 backend/evaluation/live_smoke.py，新增 backend/tests/test_phase21_live_reliability.py；同步 README、progress、handoff、refactor_plan、resume_project 和真实结果记录。

主架构不变：LangGraph 编排，Service 确定性查询和校验，LLM 根据事实反馈重规划。没有放宽硬约束来让案例通过。

## 验证

2026-09-22 后端全量离线回归：178 passed、2 skipped、9 warnings。最初全量回归为 175 passed、1 failed、2 skipped，失败是 Redis 超时异常类型不一致，修复后通过。前端未修改，本阶段未重新构建。

2026-09-20 北京公共交通真实复测 HTTP 200，132.63 秒，1 天 3 景点、3 个到访时段，路线完整，最终硬约束通过；26 次工具完成、0 次最终工具失败。见 [脱敏结果](phase21_live_result.json)。validation_findings 汇总所有校验轮次：两条 VISIT_TIME_CONFLICT 属于重规划前草稿，不是最终计划仍有冲突。BUDGET_INCOMPLETE 仍是费用缺失警告。

仅这一条复测通过，不代表所有公交案例稳定成功。历史三例初测的 2/3 保留原样，不能拼接为一次 3/3。耗时不是 P50/P95；供应商 token 与成本仍为 null。

## 遗留问题与下一建议

官方 RAG 语料、营业/预约事实约束、自由文本提取、持久 checkpoint、浏览器 E2E、远端 CI 尚未完成。重规划仍依赖模型遵循反馈，交通时长会变化，当前重试也不保证规避持续限流。没有新增全局供应商速率调度。依赖弃用警告仍存在。

下一阶段建议补浏览器 E2E，验证创建、展示、编辑与失败提示。本阶段完成后停止。
