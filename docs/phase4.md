# Phase 4：检索 Service 与 asyncio

## 完成内容

- `AmapService` 现已实现 `maps_text_search` 和 `maps_weather` 调用与类型化 JSON 解析，支持原始 JSON 或 Markdown JSON 代码块；无坐标或名称的 POI 会被丢弃，不会伪造候选。
- 新增 `TripRetrievalService`，将景点（默认及每种偏好）、酒店和天气任务通过 `asyncio.gather` 调度；候选按 POI ID/名称去重。
- 单一检索失败会转换为不含原始上游文本的 `RetrievalWarning`，其余 POI、酒店、天气结果继续传给 Planner。
- 由于 `hello-agents` 的共享 `MCPTool` 未声明并发安全，底层工具调用暂由锁串行化；任务编排已是并发的，真正的并发会话和 timeout/retry 收敛留给 Phase 5 Tool Runtime。
- 生产链路改为检索 Service → `plan_from_retrieval`；三个检索 Agent 不再在生产 Planner 初始化时创建。旧 `plan_trip` 仅保留给兼容调用。

## 验证

在 `backend` 目录执行 `python -m pytest tests -q`：**57 passed**。新增固定 MCP JSON 样例覆盖 POI/天气解析，且覆盖天气失败时保留已获取 POI 和去重。测试无外网调用。

## 边界

- 路线和地理编码仍明确返回 `FEATURE_NOT_READY`，属于 Phase 5/9。
- 目前的检索 warning 尚未呈现在 API 响应；会在 Observability 与前端阶段接入。
