# Phase 7：MySQL 计划与请求状态持久化

完成日期：2026-09-11。

## 目标与边界

本阶段建立服务端计划事实来源：保存请求快照、计划 JSON、执行状态和版本，并提供读取与乐观锁更新 API。生产连接采用 SQLAlchemy + PyMySQL；SQLite 只用于快速离线事务与重启测试。

LangGraph checkpoint 没有写入 `trip_plans`。当前工作流是单次同步图，工具和 LLM 节点缺少可安全恢复的幂等语义；强行把业务计划表当 checkpoint 会制造“看似恢复、实际重复调用”的风险。数据库目前恢复的是已保存记录和 `planning/failed/completed` 状态，不恢复执行到一半的图。

## 实现

- 新增 `PlanStore` 和 `trip_plans` SQLAlchemy 模型。字段包括 UUID 计划 ID、状态、整数版本、请求 JSON、计划 JSON、安全错误码及创建/更新时间。
- `POST /api/trip/plan` 在配置数据库后先写 version 1 的 `planning`；成功生成后事务更新为 `completed`/version 2，失败写入公开错误码并升版。
- `GET /api/trip/plans/{plan_id}` 从数据库重新验证请求与计划 Pydantic 模型后返回。
- `PUT /api/trip/plans/{plan_id}` 要求 `expected_version`。SQL UPDATE 同时匹配 ID 与版本；过期版本返回 409 `PLAN_VERSION_CONFLICT`，不存在返回 404。
- `DATABASE_URL` 为空时原规划接口保持兼容，返回的 `plan_id/version` 为 null；持久化读取/更新接口明确返回 503。配置数据库后，存储失败不会退化为未持久化的成功结果。
- 应用关闭时释放 Engine 连接池。日志只记录固定事件，不记录数据库 URL、请求 JSON、计划内容或异常原文。

## API 版本语义

| 操作 | 状态 | 版本 |
| --- | --- | ---: |
| 创建请求记录 | planning | 1 |
| 规划成功 | completed | 2 |
| 规划失败 | failed | 2 |
| 客户端基于 version 2 更新 | completed | 3 |

版本是单记录乐观锁，不是全局版本号。并发更新中只有一个匹配旧版本的事务成功，其余调用方必须重新读取。

## 验证

- 完整离线后端回归：`103 passed, 2 skipped, 10 warnings`。跳过项是需要显式配置的真实 Redis 与 MySQL 测试。
- `tests/test_phase7_persistence.py` 使用文件 SQLite 验证保存、关闭 Store、创建新 Store 后重读、失败状态、安全错误码、404、409、API 创建/读取/更新及禁用状态。
- 一次性 `mysql:8.4` 容器执行同一测试文件：`7 passed, 10 warnings`，真实验证 PyMySQL、建表、事务、版本 UPDATE 和新连接池重读；容器随后删除。

这些测试不构成生产 MySQL 高可用、连接池容量或吞吐结论。

## 已知边界

- 当前用 `create_all` 建立首版表结构，尚未加入 Alembic 迁移。
- 前端仍从 `sessionStorage` 加载结果；服务端 GET/PUT 已就绪，前端切换安排在 Phase 16。
- 没有鉴权与计划所有权模型，不能部署为多用户公开计划读取接口。
- `planning` 记录可用于发现中断，但尚无后台恢复或超时清理任务。
- 计划仍是整个 Pydantic JSON 文档，尚未为查询分析拆分日程、费用和引用表。
