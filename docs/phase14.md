# Phase 14：安全的可观测性

完成日期：2026-09-15。

请求日志现在保留 `request_id`、HTTP 状态码和实际处理耗时；`AppError` 只记录稳定错误码。LangGraph 的 plan、route、budget、validate、replan 节点分别记录 `workflow.node.started` 和节点名。JSON formatter 采用允许字段清单，仍不输出请求体、Prompt、异常文本、MCP 协议内容或任意日志 extra。

修改：`backend/app/api/main.py`、`backend/app/logging_config.py`、`backend/app/workflows/trip_workflow.py`。

验证：`python -m pytest tests -q` 为 153 passed，2 skipped，10 warnings；`git diff --check` 通过。

限制：当前输出为结构化应用日志，不是 tracing backend；尚未按请求持久化模型估算用量、缓存命中或 tool elapsed，也没有指标聚合、告警或仪表盘。下一阶段应在固定离线数据集上测量这些已有事件。
