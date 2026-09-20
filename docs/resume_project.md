# TripPilot 求职项目说明（证据版）

适用定位：AI Application Engineer / Agent 应用开发。请只使用自己能在源码和测试中解释的内容，不把教程代码或未测指标写成线上成果。

## 简历可用表述

- 基于 HelloAgents 旅行助手源码完成渐进式重构：FastAPI 接收 Pydantic 约束，LangGraph 编排并发检索、候选 ID 规划、确定性路线/预算/校验和有上限重规划；将天气、POI、酒店、路线从“Agent 角色”收敛为 Service。
- 建立 MCP Tool Runtime：参数与工具 schema 校验、单次/总超时、有界重试和并发配额；Redis 类型化缓存只保存验证后的检索事实，MySQL 以版本号保护计划编辑。
- 将 LLM 输出限制为私有 PlannerDraft 和候选 ID，由服务端水合 POI；预算、路线和硬约束由代码验证。带来源与适用期的 RAG 证据只在 verified 时用于闭园判断，缺证据保持未知。
- 建立离线回归、固定约束评测和 Docker Compose 冒烟。最近一次后端回归 171 passed、2 skipped；本机容器构建与首页/API 200 冒烟通过。另有三条固定真实服务案例初测，其中两条成功、一条失败；该小样本不等于线上成功率。

## 面试时必须说明的边界

当前没有真实官方景区知识库、自由文本结构化提取器、LangGraph 持久 checkpoint 或真实线上 benchmark。3/3 固定约束样例和约束层 P50/P95 只来自 [benchmark_results.json](benchmark_results.json) 对应的离线脚本；不得扩展为规划成功率或模型成本。

建议面试演示：先解释一条请求从 Home 到 TripRequest、候选 POI、PlannerDraft、路线/预算/Validator 的流向；然后展示一次无效候选 ID 被拒绝、预算超限触发 Replan、PUT 版本冲突拒写、MCP 超时安全退出的离线测试。
