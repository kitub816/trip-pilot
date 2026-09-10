# Phase 5：统一 Tool Runtime

## 实现与架构

生产 MCP 调用已从 HelloAgents MCPTool 同步桥接迁移到原生 MCP ClientSession/stdio；每次尝试独占会话和子进程。AmapService 保留原工具映射和同步 API 兼容入口，检索服务直接 await 异步接口。

Tool Runtime 提供本地 Pydantic 参数白名单、服务端 schema 二次校验、MCP isError/结构化内容解析、单次及总截止时间、最多三次的可配置尝试次数、进程级并发配额和 ToolProvenance。实际默认最多两次，只重试明确超时或结构化限流；普通工具文本错误、格式错误和 schema 不匹配不重试。取消向外传播，会话退出后释放配额。

## Phase 4 复核与修正

阅读本机缓存 amap-mcp-server 0.1.11 的 server.py 后发现：搜索返回不含坐标，天气 forecasts 是逐日列表。旧样例未体现这两点。现每个搜索最多用 maps_search_detail 补齐六个 POI，并解析正确的天气格式；地理编码使用 return 列表，路线解析 route.paths/transits。

另修正 JSON fence 转义、错误当空成功、无候选调用 LLM、旧 plan_trip 引用不再创建的 Agent 等问题。删除已无生产用途的三个检索 Agent Prompt。原 Phase 4 归档不覆盖。

## 验证

2026-09-10 执行 `python -m pytest tests -q`：**84 passed，10 warnings**；`git diff --check` 通过。新增离线 MCP stdio 服务以验证正常结束和超时后子进程 returncode 已设置；验证独立会话重叠、取消后清理、配额回收、超时/限流有界重试及真实返回格式。未访问真实外部服务。

## 配置及边界

`TOOL_TIMEOUT=20`、`TOOL_TOTAL_TIMEOUT=50`、`TOOL_MAX_ATTEMPTS=2`、`TOOL_CONCURRENCY=3`。MCP 包固定 1.29.1，高德启动包固定 0.1.11。检索单任务含排队最多 60 秒，最多三个并发任务。

SDK 清理时间可能超出业务截止时间；同步 HTTP 路由尚不自动响应客户端断开取消。高德包装器将某些结构化错误转成文本，这类错误不会凭文字猜测并重试。ToolResult provenance 尚未作为候选引用呈现。LLM、Redis、持久化及最终 Validator 不属于本阶段。
