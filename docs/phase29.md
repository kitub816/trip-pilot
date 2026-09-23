# Phase 29：持久状态安全与生命周期

完成日期：2026-09-23。

## 完成内容

用 Alembic 取代 PlanStore 的运行时 create_all。首个迁移既能创建全新 trip_plans 表，也能为 Phase 7/28 遗留表补充所有权、租约和工作流版本字段；容器镜像包含 alembic.ini 与 migrations。

浏览器为每个安装生成 256 bit 随机所有权令牌，保存于 localStorage，并在创建、读取、恢复和更新计划时发送 X-Trip-Owner-Token。服务端只保存 SHA-256 摘要，并以常量时间比较；Compose 默认强制要求令牌。它是适合个人应用的 capability，不是账号体系。

同一计划的执行互斥从进程内集合升级为数据库租约。租约使用条件 UPDATE 获取，后台心跳续租，正常结束主动释放，实例崩溃后可在 TTL 到期时接管。业务版本仍用乐观锁，供应商节点仍是 at-least-once。

业务记录增加 workflow_version；不兼容的旧工作流返回 409，避免用新代码盲目恢复旧 checkpoint。新增保留期配置和 cleanup_state 命令，只清理截止时间前的 completed/failed 记录，并同步删除对应 LangGraph checkpoint；支持 dry-run。

## 修改文件

- backend/alembic.ini
- backend/migrations/env.py
- backend/migrations/script.py.mako
- backend/migrations/versions/0001_plan_ownership.py
- backend/app/api/routes/trip.py
- backend/app/config.py
- backend/app/errors.py
- backend/app/services/checkpoint_service.py
- backend/app/services/migration_service.py
- backend/app/services/ownership_service.py
- backend/app/services/persistence_service.py
- backend/app/services/state_cleanup_service.py
- backend/evaluation/cleanup_state.py
- backend/tests/test_phase29_state_security.py
- backend/requirements.txt
- backend/.env.example
- backend/Dockerfile
- compose.yaml
- frontend/src/services/api.ts
- frontend/e2e/trip.spec.ts
- README.md
- docs/progress.md
- docs/refactor_plan.md
- docs/handoff.md

## 架构变化

MySQL 仍是业务状态事实来源，SQLite 仍只保存 LangGraph checkpoint。计划 ID 关联二者；owner token 控制计划 API 访问；数据库租约协调多个后端实例；workflow_version 阻止不兼容恢复；清理服务按终态和保留期同时删除两类状态。

令牌没有进入响应、日志或数据库明文。遗留 owner_token_hash 为空的记录只在 REQUIRE_PLAN_OWNER_TOKEN=false 时兼容读取；Compose 设置为 true。

## 实际验证

- 后端完整离线回归：**212 passed，2 skipped，1 warning**。
- Phase 29 测试覆盖：旧 SQLite 表原地迁移、所有权令牌缺失/错误/正确、两个 PlanStore 实例争用同一租约、dry-run 与真实终态记录/checkpoint 清理。
- 前端生产构建：通过；原有大包 warning 保留。
- Playwright：**10 passed**；创建和刷新恢复均验证 64 位所有权令牌，恢复沿用同一令牌。
- 更新后的前后端 Docker 镜像构建通过。
- 隔离的 MySQL 8.4 Compose 实例实际迁移到 0001_plan_ownership；12 个字段和两个二级索引已查询确认。
- 容器 API 对缺失/错误/正确令牌分别返回 403/403/200；使用人工插入的合成记录，没有调用高德或 LLM。隔离容器及测试卷已删除。
- 约束层历史 P50/P95 没有重测，也没有把它解释为全链路性能。

## 清理命令

在 backend 目录并配置 DATABASE_URL、CHECKPOINT_PATH 后：

~~~powershell
python -m evaluation.cleanup_state --dry-run
python -m evaluation.cleanup_state --older-than-days 30
~~~

默认天数来自 CHECKPOINT_RETENTION_DAYS。建议先 dry-run；命令不会删除 planning 记录。

## 遗留问题

- capability token 只适合单浏览器个人应用；清理浏览器存储会失去计划访问能力。公网多用户产品仍需账号、会话、撤销和找回机制。
- 数据库租约防止正常情况下多实例同时推进，但无法让外部供应商调用 exactly-once；节点在提交 checkpoint 前中断仍可能重试。
- SQLite checkpoint 文件是单节点存储；多副本共享部署应改用供应商支持的网络 checkpoint store，并做备份/恢复演练。
- cleanup_state 已实现但未加入定时调度；部署方需用任务调度器周期运行。
- 真实官方语料仍只覆盖故宫有限范围；票务余量、真实预约完成、节假日例外和无障碍资料没有实现。
- 本阶段没有真实高德/LLM 全链路、真实浏览器供应商 E2E、token/成本或远端部署验收，不能给出这些结论。

## 下一阶段建议

外部条件具备时，优先扩充带抓取时间和适用期的官方景区语料，并做真实高德/LLM 固定案例回归；若准备公网开放，先实现账号鉴权和可撤销的计划授权。当前个人演示定位下，状态恢复的迁移、所有权、跨实例租约和清理基础已经齐全。
