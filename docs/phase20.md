# Phase 20：真实端到端初测与供应商适配修复

完成日期：2026-09-20。目标是把固定案例从 FastAPI 请求实际运行到高德/LLM/路线/预算/Validator，并如实记录成功与失败。本阶段完成初测，不代表真实服务全面验收。

## 实现与架构

- 高德详情提供坐标，RouteOptimizer 改为优先调用坐标路线，避免把不精确地址再次地理编码。步行/驾车仍使用固定版本 MCP 坐标工具；原有地址路线接口保留兼容。
- 固定版本 `amap-mcp-server==0.1.11` 的公交坐标工具向 stdio stdout 打印供应商原始响应，破坏 MCP 协议。公交坐标路线改用 AmapService 内有界异步 HTTP 调用同一高德 API，保留类型解析、超时、一次安全重试、失败拒绝与缓存。未修改第三方包。
- MCP 子进程原本只传 Key，现也可传调用者设置的 `NO_PROXY`，使高德域名能够绕过故障代理。未更改系统代理。
- 真实模型两次返回 `hotel.price_range=null`，而 PlannerDraft 原要求字符串。现在未知酒店价格范围、评分、距离允许 null，服务端水合为空字符串；Prompt 与类型一致。解析失败只记录字段位置和错误类型，不记录模型原文。
- 新增单例与三例真实运行器；失败返回非零退出码，输出脱敏状态、工具计数和计划结构摘要。

修改：`backend/app/agents/trip_planner_agent.py`、`backend/app/models/planner.py`、`backend/app/services/amap_service.py`、`backend/app/services/cache_service.py`、`backend/app/services/route_service.py`、`backend/app/services/tool_runtime.py`、`backend/evaluation/live_smoke.py`、`backend/evaluation/live_suite.py`、相关测试、README、进度与评测记录。

## 验证与结果边界

后端全量离线回归 **171 passed、2 skipped、9 warnings**；`git diff --check` 通过。前端代码未改，本阶段未重新构建。真实高德步行坐标 API 探针返回 1 条路线；公交 API 与新 Service 探针均成功。固定真实案例初测：上海步行和杭州自驾成功，均有 1 天、3 个景点、3 个到访时段、路线完整；北京公交返回 422。公交适配修复后北京单独复测仍返回 422，记录到 3 次工具失败。原始脱敏数据见 [live_e2e_results.json](live_e2e_results.json)。

这个 2/3 只描述本次三例运行，不能推断线上成功率。各例耗时也不是 P50/P95。供应商 token/账单数据不可审计，仍记为 null。北京案例的具体失败路段或校验项尚未定位；不能声称公共交通完整规划已通过。真实官方 RAG 语料、持久 checkpoint、浏览器 E2E 和远端 CI 仍待完成。
