# TripPilot 旅行助手使用手册

版本基线：Phase 29，2026-09-23。

本手册面向普通使用者和本地部署者，覆盖配置、启动、网页操作、API、恢复、测试、状态清理和故障排查。

## 1. 当前能力

TripPilot 可以：

- 按城市、日期、交通、住宿、偏好、人数和预算生成计划。
- 设置必去、避开、每日步行上限和单段交通时间上限。
- 从自由文本提取约束预览，经用户确认后填入表单。
- 并发查询景点、酒店和天气。
- 展示每日景点、餐饮、住宿、路线、天气和预算。
- 标记未知费用、证据不足和预约不确定。
- 编辑景点到访时刻，并由服务端重算路线、预算和校验。
- 在刷新或网络中断后检查并继续未完成计划。
- 导出 PNG 或 PDF。
- 用 Docker Compose 启动前端、后端、Redis 和 MySQL。

限制：

- 官方 RAG 仅覆盖北京故宫主 POI 的有限日期和规则。
- 系统不办理真实预约，也不查询实时余票。
- 地图连线不是道路 geometry。
- 未知价格会保持未知，不会自动编造。
- 真实服务受网络、限流、Key 权限和模型兼容性影响。
- owner token 适合个人浏览器，不是账号系统。

## 2. 准备凭据

至少需要：

1. 高德 Web 服务 Key：后端 POI、天气和路线。
2. OpenAI 兼容的 LLM API Key、Base URL 和模型 ID。
3. 高德 Web 端 JS API Key：前端地图。

Docker 还需 MYSQL_PASSWORD 和 MYSQL_ROOT_PASSWORD。

可选 Unsplash Key 用于图片。VITE_AMAP_SECURITY_JS_CODE 当前保留在模板中，但 Result.vue 尚未消费。

不要提交任何 .env。

## 3. Docker Compose 启动

要求：Docker Desktop 已启动，8080 端口可用。

### 3.1 配置

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner
Copy-Item .env.example .env
notepad .env
~~~

填写：

~~~dotenv
AMAP_API_KEY=你的高德Web服务Key
LLM_API_KEY=你的模型Key
LLM_MODEL_ID=你的模型ID
LLM_BASE_URL=你的OpenAI兼容接口地址
MYSQL_PASSWORD=本地数据库密码
MYSQL_ROOT_PASSWORD=本地root密码
VITE_AMAP_WEB_JS_KEY=你的高德Web端JS API Key
VITE_AMAP_SECURITY_JS_CODE=
TRIPPILOT_PORT=8080
~~~

### 3.2 启动

~~~powershell
docker compose build
docker compose up -d
docker compose ps
~~~

应看到 frontend、backend、redis、mysql。

访问：

- 应用：http://localhost:8080
- 配置检查：http://localhost:8080/api/trip/health

configured 只表示配置字段齐全，不代表已经成功调用高德或 LLM。

### 3.3 日志和停止

~~~powershell
docker compose logs --tail 100 backend
docker compose logs -f backend
docker compose down
~~~

保留数据时使用 docker compose down。只有确认不需要历史计划时才运行：

~~~powershell
docker compose down -v
~~~

该命令会永久删除 Compose 的 MySQL 和 checkpoint 数据卷。

## 4. 本地开发启动

### 4.1 后端

要求 Python 3.10 和可用的 uvx。

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\backend
Copy-Item .env.example .env
notepad .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python run.py
~~~

最低必填：

~~~dotenv
LLM_API_KEY=你的模型Key
LLM_BASE_URL=你的接口地址
LLM_MODEL_ID=你的模型ID
AMAP_API_KEY=你的高德Web服务Key
~~~

可选持久化：

~~~dotenv
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=mysql+pymysql://用户名:密码@localhost:3306/trippilot
CHECKPOINT_PATH=./state/workflow.sqlite
REQUIRE_PLAN_OWNER_TOKEN=false
~~~

设置 DATABASE_URL 后，PlanStore 首次使用时运行 Alembic upgrade。同时设置 CHECKPOINT_PATH 才能获得完整网页恢复。

后端地址：

- Swagger：http://localhost:8000/docs
- 存活：http://localhost:8000/health
- 配置：http://localhost:8000/api/trip/health

### 4.2 前端

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\frontend
Copy-Item .env.example .env
notepad .env
npm ci
npm run dev
~~~

~~~dotenv
VITE_API_BASE_URL=http://localhost:8000
VITE_AMAP_WEB_JS_KEY=你的高德Web端JS API Key
VITE_AMAP_SECURITY_JS_CODE=
~~~

访问 http://localhost:5173。修改前端环境变量后需重启 Vite。

## 5. 网页操作

### 5.1 基本信息

填写目的地、开始和结束日期、交通方式、住宿类型与偏好。

交通可选：公共交通、自驾、步行、混合。
住宿可选：经济型酒店、舒适型酒店、豪华酒店、民宿。
行程最长 30 天。

### 5.2 硬约束

可填写：

- 人数：1–20。
- CNY 预算上限。
- 必去地点，逗号分隔。
- 避开地点，逗号分隔。
- 每日最大步行公里数。
- 单段最大交通分钟数。
- 仅安排无需预约的景点。

同一地点不能同时必去和避开。“仅安排无需预约”是严格约束，预约状态未知不会被视为通过。

### 5.3 自由文本

示例：

~~~text
两个人去北京，预算 3000 元，必须去故宫，不去环球影城，
每天最多步行 8 公里，单段交通不要超过 45 分钟。
~~~

先提取预览，再确认应用：

- 手动字段优先。
- 提取结果只填空白字段。
- 未确认结果不会进入规划。

### 5.4 生成计划

点击“开始规划我的旅行”。真实规划可能较慢，前端和代理上限为 600 秒。关闭页面或网络中断不一定会取消后端计算。

请求前浏览器保存 32 位恢复 ID 和 64 位 owner token。规划期间不要清除该站点的 localStorage。

### 5.5 阅读结果

结果页展示行程、天气、预算、路线、来源、warning 和地图。

注意：

- 未知费用不是 0 元。
- warning 表示需要核实。
- 地图线段只是坐标连线。
- 来源缺失时，系统不会承诺开放、无需预约或无障碍。
- 真实预约仍需用户前往官方渠道完成。

### 5.6 编辑和保存

修改到访时刻后保存。后端会：

1. 校验 expected_version。
2. 重算路线。
3. 重算预算。
4. 运行 Validator。
5. 验证通过后写新版本。

版本冲突时刷新并基于最新计划重改，避免覆盖服务器新版本。

### 5.7 导出

可导出 PNG 或 PDF。地图受 Canvas 跨域策略影响，地图未进入导出文件时，文字行程和预算仍可导出。

## 6. 恢复未完成计划

网页恢复要求 DATABASE_URL、CHECKPOINT_PATH，以及原浏览器仍有 pending ID 和 owner token。

刷新首页后：

- planning：可继续规划。
- completed：打开结果。
- failed：显示安全错误码，不能恢复。
- 404：记录不存在。
- 403：owner token 不匹配，常见于换浏览器或清 localStorage。
- 409 WORKFLOW_VERSION_UNSUPPORTED：旧状态不兼容，需要重新规划。
- 503 SERVICE_BUSY：另一个请求或实例正在推进，稍后再查。

恢复不保证供应商调用 exactly-once。节点提交 checkpoint 前中断时可能重试。

## 7. API 示例

本地后端基址是 http://localhost:8000/api；Compose 入口是 http://localhost:8080/api。

### 7.1 配置检查

~~~powershell
curl.exe http://localhost:8000/api/trip/health
~~~

不会调用供应商。

### 7.2 创建计划

以下请求会真实调用高德和 LLM，可能产生费用：

~~~powershell
$owner = '1' * 64
$planId = 'a' * 32
$body = @{
  city = '北京'
  start_date = '2026-10-20'
  end_date = '2026-10-21'
  transportation = '公共交通'
  accommodation = '经济型酒店'
  preferences = @('历史文化')
  travelers = 2
  budget_limit = 3000
  currency = 'CNY'
  must_visit = @('故宫')
  avoid_places = @()
  max_daily_walking_km = 8
  max_single_transport_minutes = 45
  avoid_reservation_required = $false
  free_text_input = ''
} | ConvertTo-Json

$params = @{
  Method = 'Post'
  Uri = 'http://localhost:8000/api/trip/plan'
  ContentType = 'application/json'
  Headers = @{
    'X-Trip-Plan-ID' = $planId
    'X-Trip-Owner-Token' = $owner
  }
  Body = $body
}
Invoke-RestMethod @params
~~~

示例 owner 只用于本地调试。实际客户端应生成随机令牌。

### 7.3 查询和恢复

~~~powershell
$headers = @{ 'X-Trip-Owner-Token' = $owner }
Invoke-RestMethod -Uri "http://localhost:8000/api/trip/plans/$planId" -Headers $headers
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/trip/plans/$planId/resume" -Headers $headers
~~~

### 7.4 更新

PUT 需要 expected_version 和 GET 返回的完整 data。不要发送空 days。服务端会重算路线、预算并校验。

## 8. 测试

后端：

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\backend
.\.venv\Scripts\python.exe -m pytest
~~~

当前基线：212 passed、2 skipped、1 条第三方 warning。两个 skipped 是需外部 Redis/MySQL 条件的集成测试。

前端：

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\frontend
npm run build
npm run test:e2e
~~~

当前基线：构建通过，Playwright 10 passed；主包体积 warning 仍存在。

约束层 benchmark：

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\backend
.\.venv\Scripts\python.exe -m evaluation.benchmark
~~~

该结果不包括地图、LLM、路线网络或完整请求。

## 9. 状态清理

先预览：

~~~powershell
cd E:\travel-agents-1\helloagents-trip-planner\backend
.\.venv\Scripts\python.exe -m evaluation.cleanup_state --dry-run
~~~

执行 30 天保留期：

~~~powershell
.\.venv\Scripts\python.exe -m evaluation.cleanup_state --older-than-days 30
~~~

要求 DATABASE_URL 和 CHECKPOINT_PATH 已配置。只删除 completed/failed 及对应 checkpoint，不删除 planning。

## 10. 常见问题

### 配置检查通过但规划失败

配置接口不访问供应商。检查高德 Key 类型和权限、LLM Base URL、模型 ID、网络，以及后端 error_code 和 request_id。

### NO_CANDIDATES

未获得有效景点候选。检查城市、关键词、高德权限、网络和限流。系统不会编造候选。

### UPSTREAM_TIMEOUT / UPSTREAM_ERROR

供应商超时或返回不可解析结果。只对明确超时和结构化限流有限重试。

### PLAN_ACCESS_DENIED

owner token 缺失或不匹配。常见原因是换浏览器、清 localStorage 或 API 未发送 X-Trip-Owner-Token。当前无账号找回，只能使用原令牌或重新规划。

### PLAN_VERSION_CONFLICT

先 GET 最新版本，再编辑保存。

### CHECKPOINT_UNAVAILABLE

CHECKPOINT_PATH 未配置、不可写或文件不可访问。

### SERVICE_BUSY

同一计划正在由另一个请求或实例推进。等待后查询，避免连续恢复。

### 地图失败

检查 VITE_AMAP_WEB_JS_KEY、域名白名单、浏览器控制台，并确认改配置后已重启或重建。地图失败不等于后端规划失败。

### MySQL 改密码后仍连接失败

复用旧 Docker 卷时，新环境变量不会修改卷内已有用户密码。恢复原密码，或在确认不需要数据后删除卷重建。

## 11. 数据与安全

- 不提交 .env。
- checkpoint 含用户请求、候选和计划，应视为私有数据。
- MySQL 只保存 owner token 哈希。
- localStorage 保存 owner token，不要在不可信设备使用。
- 日志不应记录 Prompt、请求正文、密钥或供应商异常原文。
- 对外部署前启用 HTTPS，并增加账号、会话、撤销和找回。
- SQLite checkpoint 适合单节点；多副本共享应改用网络存储。

## 12. 修改代码后的检查清单

1. 读 AGENTS.md 和 docs/progress.md。
2. 数据库模型变更必须新增 Alembic revision。
3. 工作流 state 变化要评估 workflow_version。
4. 新硬约束放入确定性 Service/Validator 并补正反测试。
5. 新供应商调用定义超时、重试、部分失败、取消和日志边界。
6. 新 RAG 事实必须有 URL、抓取时间、适用期、可信状态。
7. 跑专项测试和后端全量回归。
8. 跑前端构建和 Playwright。
9. 更新 progress。
10. 只报告真实测量的性能与成本。

## 13. 能力速查

| 能力 | 状态 |
| --- | --- |
| 结构化约束 | 已实现 |
| 自由文本提取 | 预览并确认 |
| POI/酒店/天气 | 已实现，依赖高德 |
| 路线优化 | 有界启发式，非全局最优 |
| 预算 | 已知项汇总，未知项保留 |
| 时间窗 | 已实现 |
| 官方 RAG | 故宫有限范围 |
| 真实预约 | 未实现 |
| 网页恢复 | 已实现 |
| 计划所有权 | capability token |
| 多实例互斥 | 数据库租约 |
| 完整账号系统 | 未实现 |
| Docker/CI | 已验证 |
| 浏览器 E2E | 固定 API 契约已实现 |
| 真实供应商浏览器 E2E | 未完成 |
| 全链路 P50/P95 | 未测 |
| 可审计 token/成本 | 未取得 |

对外展示前，先完成离线测试和配置检查，再决定是否进行真实供应商演示。
