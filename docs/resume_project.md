# TripPilot 求职项目说明（当前证据版）

适用岗位：AI Application Engineer、Agent 应用开发、LLM 工程实习。

详细学习与面试准备见 [研二 Agent 实习项目学习教程](研二Agent实习项目学习教程.md)，运行方式见 [TripPilot 使用手册](TripPilot使用手册.md)。

## 项目名称

**TripPilot｜约束驱动、可验证、可恢复的旅行规划 Agent**

## 简历描述

- 基于 FastAPI、LangGraph 和 Pydantic 构建 plan → route → budget → validate → bounded replan 工作流；LLM 只生成候选 ID 草稿，地点身份由服务端检索结果水合，拒绝未知引用和额外字段。
- 设计 MCP Tool Runtime，支持工具 schema 与参数校验、单次/总超时、有界重试、并发配额、部分失败和子进程清理；Redis 仅缓存类型校验后的地图检索事实。
- 使用确定性 Python 实现有界路线矩阵与稳定排序、预算汇总、时间窗和硬约束 Validator；仅带来源 URL、抓取时间、适用期和可信状态的 RAG 证据参与开放/预约判断。
- 使用 MySQL、Alembic、乐观锁、capability token、数据库租约和 SQLite LangGraph checkpoint 实现计划持久化与网页恢复；建立后端 212 passed、2 skipped、Playwright 10 passed、Docker Compose 和 GitHub Actions 验证。

## 30 秒介绍

TripPilot 是我从 Hello-Agents 教程项目渐进重构的旅行规划 Agent。它用 LangGraph 编排检索、规划、路线、预算、校验和有限 Replan；LLM 只做语义与候选组合，预算、路线、时间和硬约束由 Python 确定性计算。工程上加入 MCP Runtime、Redis、MySQL、Alembic、RAG 证据、checkpoint 恢复、数据库租约、Vue 前端、Docker 和 CI。

## 面试证据

- 后端完整离线回归：212 passed、2 skipped。
- 前端生产构建通过；Playwright 10 passed。
- GitHub Actions backend/frontend 作业成功。
- 隔离 MySQL 8.4 实际迁移到 0001_plan_ownership。
- 容器 API 对缺失、错误、正确 owner token 返回 403、403、200。
- 三条固定真实高德/LLM 案例初测为 2 成功、1 失败；北京失败案例后续单独修复复测成功。该小样本不是线上成功率。

## 必须说明的边界

- benchmark_results.json 的 P50/P95 只测本地约束层。
- 官方 RAG 只覆盖故宫主 POI 的有限日期和规则。
- 未实现真实票务预约、完整账号系统或网络 checkpoint store。
- 没有可审计的真实 token、成本、缓存命中率和全链路 P50/P95。
- 浏览器 E2E 使用固定 API 响应，真实供应商浏览器 E2E 尚未完成。
- SQLite checkpoint 是 at-least-once，不能承诺供应商调用 exactly-once。

只在自己能指向源码和测试解释时使用上述简历表述。
