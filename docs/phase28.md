# Phase 28：HTTP 与网页 checkpoint 恢复

完成日期：2026-09-23。

## 完成内容

浏览器在发起规划前生成 128 bit 随机恢复 ID，写入 localStorage，并通过 X-Trip-Plan-ID 发送。启用业务数据库时，后端用该 ID 创建 planning 记录；同时配置 CHECKPOINT_PATH 时，LangGraph 以同一 ID 作为 thread ID 写入 SQLite checkpoint。

新增 POST /api/trip/plans/{plan_id}/resume。业务记录已完成时直接返回；已失败时拒绝恢复；仍在规划时，如果已有 checkpoint 就从最后提交节点继续，如果中断发生在首个 checkpoint 前则使用持久化请求启动图。预期的 AppError 会写入安全错误码并终止；未预期的进程或节点异常保留 planning 状态，供稍后恢复。

同一进程内按 plan ID 互斥，避免原同步请求仍在执行时再次推进同一图。该互斥不是跨实例分布式锁。

首页刷新时检查 localStorage 中的未完成 ID。用户可检查状态、继续规划或忽略记录；完成后写入既有 sessionStorage 结果引用并进入结果页。只有超时、取消、网络错误和服务端 5xx 保留恢复 ID；明确的客户端错误会清理它。

Compose 为后端设置 /app/state/workflow.sqlite，并挂载独立 checkpoint_data 命名卷。SQLite 文件包含用户请求与计划，按私有业务数据处理。

## 修改文件

- backend/app/api/routes/trip.py
- backend/app/config.py
- backend/app/errors.py
- backend/app/services/checkpoint_service.py
- backend/app/services/persistence_service.py
- backend/app/workflows/trip_workflow.py
- backend/tests/test_phase28_web_recovery.py
- frontend/src/services/api.ts
- frontend/src/types/index.ts
- frontend/src/views/Home.vue
- frontend/e2e/trip.spec.ts
- backend/.env.example
- compose.yaml
- README.md
- docs/progress.md

## 架构变化

MySQL 业务记录仍是查询状态和最终计划的事实来源；SQLite 只保存 LangGraph 执行状态。两者用同一 plan ID 关联，没有把 checkpoint 当业务数据库。Agent、路线、预算和校验节点职责不变。

## 实际验证

- 后端完整离线回归：**207 passed，2 skipped，1 warning**。
- 新增测试真实打开 SQLite checkpoint：路线节点模拟中断后经 HTTP 恢复，planner 只执行一次，route 执行两次；完成记录幂等读取，失败状态和未配置 checkpoint 均有明确错误。
- 前端生产构建：通过；原有大包 warning 保留。
- Playwright：**10 passed**，新增刷新后发现 pending 记录、继续并进入结果页的浏览器契约。
- docker compose config --quiet：使用进程内占位配置通过。
- 更新后的前后端镜像构建通过；npm ci 报告 0 vulnerabilities。
- 占位配置 Compose 四服务启动；首页与 /api/trip/health 均 HTTP 200；checkpoint 命名卷在后端容器内可写。未调用真实高德或 LLM，容器已停止，数据卷保留。

## 遗留问题

- 恢复 ID 尚未绑定登录用户；知道 ID 的调用者可以读取或继续记录，因此不适合直接作为公网多用户鉴权方案。
- 并发互斥仅限单进程；多副本部署需要数据库租约或分布式锁。
- 正在执行的节点中断后可能重试，供应商调用不保证 exactly-once；模型调用预算也没有跨进程累计。
- 同步 HTTP 请求仍不会因客户端断开自动取消后端计算；恢复功能降低结果丢失风险，但没有实现异步任务队列。
- checkpoint 没有版本迁移、保留期或自动清理。
- 本阶段没有运行真实高德/LLM 规划，不能据此报告真实成功率、延迟、token 或成本。

## 下一阶段建议

优先增加计划所有权与最小鉴权，并把单进程互斥升级为可跨实例的数据库租约；如果项目仍定位为单机个人演示，可先实现 checkpoint 保留期和清理命令，再扩大官方景区证据与真实端到端评测。