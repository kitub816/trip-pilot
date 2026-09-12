# Phase 13：Model Gateway

完成日期：2026-09-12。

`ModelGateway` 成为 Planner 调用 HelloAgents 的请求级边界：每次初始规划重置调用计数，格式修复和 Replan 共享同一预算；默认最多 4 次调用、单 prompt 最多 60,000 字符。网关保存本地字符估算的 prompt/completion token 数，明确这是估算值，不能当作 provider 账单用量。它把 HTTP 429 分类为安全的 `MODEL_RATE_LIMIT`，超时仍走既有安全错误；异常原文不进入 API。

修改：`backend/app/services/llm_service.py`、`backend/app/agents/trip_planner_agent.py`、`backend/app/config.py`、`backend/app/errors.py`、`backend/tests/test_phase13_model_gateway.py`。

验证：专项 `3 passed`；完整后端回归 `153 passed, 2 skipped, 10 warnings`；`git diff --check` 通过。

限制：HelloAgents 当前 Agent API 不暴露可靠 provider usage，故仅记录本地估算，未声明成本；调用依旧是同步的，未支持模型 fallback 或流式响应。下一阶段应把已有日志关联到图节点、工具、缓存和模型调用。
