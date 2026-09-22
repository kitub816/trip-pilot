# TripPilot 求职项目说明（证据版）

适用定位：AI Application Engineer / Agent 应用开发。请只使用自己能在源码和测试中解释的内容，不把教程代码或未测指标写成线上成果。

## 简历可用表述

- 基于 HelloAgents 旅行助手源码完成渐进式重构：FastAPI 接收 Pydantic 约束，LangGraph 编排并发检索、候选 ID 规划、确定性路线/预算/校验和有上限重规划；将天气、POI、酒店、路线从“Agent 角色”收敛为 Service。
- 建立 MCP Tool Runtime：参数与工具 schema 校验、单次/总超时、有界重试和并发配额；Redis 类型化缓存只保存验证后的检索事实，MySQL 以版本号保护计划编辑。
- 将 LLM 输出限制为私有 PlannerDraft 和候选 ID，由服务端水合 POI；预算、路线和硬约束由代码验证。带来源与适用期的 RAG 证据只在 verified 时用于闭园判断，缺证据保持未知。
- 建立离线回归、固定约束评测和 Docker Compose 冒烟。最近一次后端回归 192 passed、2 skipped；本机容器构建与首页/API 200 冒烟通过。另有三条固定真实服务案例初测，其中两条成功、一条失败；该小样本不等于线上成功率。

## 面试时必须说明的边界

当前没有真实官方景区知识库、自由文本结构化提取器、LangGraph 持久 checkpoint 或真实线上 benchmark。3/3 固定约束样例和约束层 P50/P95 只来自 [benchmark_results.json](benchmark_results.json) 对应的离线脚本；不得扩展为规划成功率或模型成本。

建议面试演示：先解释一条请求从 Home 到 TripRequest、候选 POI、PlannerDraft、路线/预算/Validator 的流向；然后展示一次无效候选 ID 被拒绝、预算超限触发 Replan、PUT 版本冲突拒写、MCP 超时安全退出的离线测试。

Phase 21 已修复北京公交限流重试和交通时长反馈，原失败案例单独复测通过；属于单例结果，不改变历史三例初测记录，也不代表线上成功率。详见 [阶段记录](phase21.md)。

2026-09-22 更新：已增加自由文本约束提取预览（用户确认后填入空白字段）、7 项浏览器 API 契约回归、PDF 下载验证；依赖审计当前为 0 项。浏览器测试使用固定 API 响应，远端 CI 未验证。

## 2026-09-22 当前验证

阶段 22–27 已补浏览器回归、前端依赖审计、提取预览、故宫有限官方证据、SQLite 本地 checkpoint 与长请求等待修复。项目 .venv 后端 205 passed、2 skipped、1 warning；浏览器 9 passed；build 通过。远端 CI 无 remote，等待用户目标仓库与推送授权；不能声称原始规格全部完成。
