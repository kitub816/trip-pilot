# Phase 33：限制 LLM SDK 隐式重试

完成日期：2026-09-28。

## 完成内容

真实浏览器规划在 85%“有限重规划”阶段长时间停留。日志证明检索、首次草稿、路线和确定性校验均已完成；校验发现 `SEGMENT_TIME_EXCEEDED` 与 `VISIT_TIME_CONFLICT` 后进入一次重规划。当前配置的单次 LLM 超时为 180 秒，而 OpenAI SDK 默认再重试两次，使一次工作流模型调用最坏可能等待约 540 秒，并逼近前端 600 秒总等待上限。

项目已有有界格式修复、模型调用预算和一次 LangGraph 重规划，因此在 HelloAgents 客户端创建后将底层 OpenAI 客户端 `max_retries` 设为 0。单次模型调用仍保留配置的超时；供应商失败由现有安全错误边界返回，不在传输层重复长 POST。

## 修改文件

- `backend/app/services/llm_service.py`
- `backend/tests/test_phase1.py`
- `README.md`
- `docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`
- `docs/TripPilot使用手册.md`
- `docs/phase33_learning.md`
- `E:\TP各版本文档\33\学习文档.md`

## 架构变化

LangGraph 仍决定是否重规划，`ModelGateway` 仍限制调用次数；SDK 只执行一次传输尝试。这样把业务级重规划和传输级重试分开，避免隐式重试放大时延及重复计费风险。

## 验证

- 模型配置、资源清理、超时分类和网关专项测试：5 passed。
- 后端完整离线回归：219 passed、2 skipped、1 条 HelloAgents 第三方警告。
- 重启本地后端后 `/api/trip/health` 返回 HTTP 200。
- 只读 `/models` 连通性探针在系统代理和直连模式均返回 HTTP 200；未执行额外的内容生成调用。

## 遗留问题

- 本阶段没有再次执行完整真实规划，不能声称重规划已由供应商端到端成功。
- HTTP 客户端断开仍不保证取消供应商侧已经收到的生成请求。
- 本地开发模式未配置 `DATABASE_URL` 时，计划查询与恢复仍返回 `PERSISTENCE_UNAVAILABLE`。
- 当前通过 HelloAgents 的私有 `_client` 属性约束固定依赖版本；升级 HelloAgents 时必须重新验证。

## 下一阶段建议

使用一条会触发重规划的固定真实案例，记录安全结果与总耗时；随后再决定是否需要工作流级取消或异步任务队列。
