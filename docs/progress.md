# TripPilot 进度

更新时间：2026-09-10。事实来源：当前代码、本文件、根目录 `docs-project_spec.md`。

## 当前阶段

Phase 0–5 已实现，Phase 6–18 待完成。用户已授权逐阶段继续到最终阶段；每阶段独立验证、提交并归档文档。

## 当前架构

`FastAPI 同步工作线程 → TravelConstraints → LangGraph → TripRetrievalService → AmapService → ToolRuntime → 原生 MCP stdio 会话`，随后一个 Planner LLM 生成计划。请求级图 state 不持久化，Planner 仍用进程内互斥和历史清理。

- 约束：日期、人数、CNY 预算上限、必去/避开、步行及单段交通上限已结构化；自由文本提取只有合并边界，尚无提取器。
- 工具：本地 Pydantic 参数白名单 + 发现的工具 schema；每次尝试独立会话；默认 20 秒单次/50 秒总截止时间、最多 2 次尝试、每进程 3 个并发槽。只重试明确超时或结构化限流。
- 检索：最多 3 个并发任务，单任务含排队 60 秒截止时间，覆盖偏好和必去，POI 按 ID 去重，每个搜索最多补查 6 个详情。无有效景点明确终止。
- 地图：按本地缓存的 amap-mcp-server 0.1.11 源码解析搜索、详情、天气、地理编码和路线；生产固定该版本。搜索不含坐标，详情提供坐标；路线结果有距离和时间，无前端路网折线。
- 安全：API 错误不含原文；MCP 子进程 stderr 不外传，MCP transport 日志只保留安全事件；健康检查不访问外部依赖。
- 生命周期：会话及子进程由 async context 关闭；ASGI 停机清理 runtime、服务和 Planner/LLM 引用。

## 阶段记录

| Phase | 状态/文档 |
| --- | --- |
| 0 | [现状分析](current_architecture.md)，历史源码快照 |
| 1 | [配置、日志、异常](phase1.md)，基线提交 73d0e36 |
| 2 | [约束引擎](phase2.md)，提交 b0e5a04 |
| 3 | [最小 LangGraph](phase3.md)，提交 0f5ceb1 |
| 4 | [检索 Service](phase4.md)，提交 19a0d3b；本次复核发现原测试未覆盖真实返回格式，缺口已在 Phase 5 修补 |
| 5 | [Tool Runtime](phase5.md)，包括 Phase 4 缺口修补 |

## Phase 5 修改

新增 `backend/app/services/tool_runtime.py`；更新 AmapService、RetrievalService、Planner 兼容入口、配置、错误、生命周期、日志及依赖；新增 runtime/stdio/检索集成测试和离线 MCP fixture；修订已迁移接口的旧测试。删除废弃检索 Agent Prompt 和已损坏的旧四 Agent 入口实现。

修正了上阶段正则过度转义、错误响应当空成功、无候选仍调用 LLM、真实 POI 搜索没有坐标、真实天气 forecasts 格式不匹配、路线和 geocode 未实现等问题。原归档保持历史原样，以 Phase 5 记录修正。

## 实际验证

`backend: python -m pytest tests -q`：**84 passed，10 warnings**。
`git diff --check`：通过。

测试包括真实本地 MCP stdio 子进程正常关闭/超时退出（检查进程 returncode）、替身会话取消/配额释放/并发重叠/有界重试/总截止时间、服务 schema 不匹配、JSON 及结构化 MCP 错误、真实服务格式样例、慢天气保留景点。没有访问真实高德、LLM 或 Unsplash，没有线上性能结论。

环境：Python 3.10.1、mcp 1.29.1、anyio 4.14.2、hello-agents 0.2.9；LangGraph 本机仍为 1.0.0a3，后续需要在干净环境固定稳定版本。前端最近一次 Phase 2 构建通过，本阶段未改前端。

## 遗留问题

- 高德 MCP 0.1.11 会把部分错误压成文字，无法可靠区分这些错误的限流/可重试性；运行时保守不重试这类错误。
- 截止时间触发后仍需执行 SDK 的进程清理，实际返回可多出清理时间。当前 HTTP 同步路由不会在客户端断开时自动取消；原生检索协程本身已支持取消。
- Planner LLM 仍是同步 HelloAgents 调用，共享实例仍拒绝重叠规划；LLM 总预算、结构化输出、预算及约束最终验证待后续阶段。
- ToolResult 提供工具名、抓取时间、尝试次数和耗时；候选级引用和跨节点指标尚未接入。
- 尚无 Redis/MySQL/RAG/持久 checkpoint/部署与线上评测；不可宣称行程已通过硬约束验证。
- 子进程级并发已由离线 MCP 测试验证；真实地图服务仍需联网验收。依赖弃用警告和前端大包警告尚存。

## 下一阶段

Phase 6：在类型化检索结果边界接入 Redis 缓存，规范化版本键、分类 TTL、损坏数据拒绝和 Redis 断开时回源；不缓存失败结果为正常空列表。
