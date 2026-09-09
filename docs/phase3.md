# Phase 3：LangGraph 基础工作流

## 完成内容

- 新增 `app/workflows/trip_workflow.py`，以 `TripWorkflowState` 定义单次请求的约束、状态、计划和应用错误。
- 建立最小 `StateGraph`：`START → plan → END`，已知 `AppError` 则进入显式 `failure` 终态节点。图不使用 checkpointer，也不承诺重启恢复。
- `POST /api/trip/plan` 仍只负责请求校验与约束构建；随后按请求创建工作流，并将旧 `MultiAgentTripPlanner` 注入 `plan` 适配节点。
- 保留原 Planner 的请求互斥、历史清理和解析行为；本阶段没有把检索、缓存、数据库或重规划提前迁入图中。

## 当前链路

```text
TripRequest → TravelConstraints → TripPlanningWorkflow
  → plan（legacy Planner adapter） → TripPlan / AppError
```

每次 API 调用均创建新的编译图和 typed state；工作流对象不保存上次请求的约束、计划或错误。旧 Planner 仍是临时适配器，直到 Phase 4/5 将检索职责迁入 Service/Tool Runtime。

## 验证

在 `backend` 目录执行 `python -m pytest tests -q`：**57 passed**。测试使用替身 Planner，未访问 LLM、MCP 或网络；覆盖工作流成功状态、错误状态和 API 既有错误契约。

## 边界

- 当前图只负责一条 Planner 适配链，尚无持久 checkpoint、条件重规划或并行检索分支。
- 非 `AppError` 仍由既有 FastAPI 安全异常边界处理，避免改变既有 500 错误契约。
