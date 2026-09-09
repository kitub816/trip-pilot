# TripPilot 进度

更新时间：2026-09-09。

## 当前阶段

**Phase 2 已完成；Phase 3 尚未开始。本次完成后停止。**

事实来源为当前代码与本文件。规格仍为根目录 `docs-project_spec.md`。[current_architecture.md](current_architecture.md) 保留 Phase 0 历史快照；其旧故障描述不能当作修复后的当前行为。

## Phase 2 做了什么

- `TripRequest` 的日期改为 Pydantic `date`，`travel_days` 可省略并按包含首尾日期推导；显式天数不一致、反向日期和超过 30 天均在 Planner 初始化前返回 422。
- 新增交通与住宿枚举，保持现有前端四个选项兼容；新增人数、CNY 总预算上限、必去/避开、每日步行公里上限和单段交通分钟上限。
- 新增 `constraint_service.py`，构建规范化、不可变的 `TravelConstraints`；偏好和地点去空白、去空项、大小写不敏感去重，必去/避开冲突确定性拒绝。
- 新增 `ExtractedConstraints` 合并边界：显式结构化值（含空列表）优先，语义提取只补缺失值，最后才采用默认值。本阶段未新增 LLM 提取调用，空自由文本不会触发额外模型调用。
- 旅行 API 现在把约束模型传给现有 Planner；Planner Prompt 接收人数、预算、必去/避开、步行和单段交通上限。硬约束最终验证仍属于后续阶段。
- 前端 `TripFormData` 增加对应可选类型；现有表单无需改动即可继续发送旧请求。
- 新增 `backend/tests/test_phase2_constraints.py` 和 [phase2.md](phase2.md)。

Phase 2 修改文件：`backend/app/models/schemas.py`、新增 `backend/app/services/constraint_service.py`、`backend/app/api/routes/trip.py`、`backend/app/agents/trip_planner_agent.py`、`frontend/src/types/index.ts`、新增 `backend/tests/test_phase2_constraints.py`、`docs/phase2.md`、`docs/progress.md`、`docs/refactor_plan.md`、`README.md`。

## Phase 1 做了什么

- 配置：固定读取 backend/.env，移除工作目录查找和邻近 HelloAgents 项目的隐式回退；统一 LLM_* 配置并兼容 OPENAI_* 别名。环境变量优先于文件，同一来源中 LLM_* 优先。密钥用 SecretStr，LLM 构造显式传参，启动必须具备地图密钥、LLM 密钥及模型名，Unsplash 可选。
- 错误：引入 AppError 分类和统一 ErrorResponse（success/message/error_code/request_id/detail），保留 detail 兼容现有前端；422、502、503、504 与未知 500 不再暴露异常原文或用户输入。
- 规划：删除虚构 fallback；JSON/模型解析失败明确报错。保留原四个 Agent、Prompt 与查询构建。全局实例增加初始化保护、请求互斥和前后清理历史，并在异常后释放锁；同一进程已有规划时返回 SERVICE_BUSY，不排无限队列。
- 执行：同步规划、地图和图片 API 使用普通 def，由 FastAPI 工作线程运行，避免在 async 路由直接阻塞事件循环。这是基础修复，尚未实现检索 asyncio 并发。
- 健康检查：/health 是 liveness；/api/trip/health 和 /api/map/health 仅检查配置并明确 external_dependencies=not_checked，不初始化 MCP/LLM、不访问不存在的 agent.agent。
- 地图：保留原工具名称与参数映射，未实现解析的 search_poi/get_weather/plan_route/geocode 在外部调用前明确 FEATURE_NOT_READY；POI detail 无效结果转 502，不再包装 raw 错误文本为成功。
- 图片：区分正常无结果与缺配置/上游错误/超时；密钥从 query string 移到 Authorization header；保留同步 10 秒 timeout 和两级名称查询。
- 日志：应用 JSON 事件日志及服务器生成的 X-Request-ID，工作线程继承请求上下文；不记录输入、Prompt、工具结果或异常原文。run.py 默认不 reload，关闭访问日志以避免记录 query string。
- 生命周期：FastAPI lifespan 启停；关闭时清空 planner 历史/引用、地图包装器缓存，并关闭 LLM HTTP client；任一清理失败仍尝试其余资源。
- 依赖与示例：固定已检查的 hello-agents 0.2.9，补 requests、pytest 开发依赖与前端直接依赖 dayjs/icons-vue；同步 lockfile；示例密钥置空，frontend/.gitignore 补 .env。未修改用户实际 .env，未使用或轮换此前疑似凭据。

## 修改文件

| 类别 | 文件 |
| --- | --- |
| 配置与日志 | backend/app/config.py；新增 backend/app/errors.py、backend/app/logging_config.py；backend/run.py |
| API/模型 | backend/app/api/main.py、routes/trip.py、routes/map.py、routes/poi.py；backend/app/models/schemas.py（只扩展错误响应） |
| 规划/服务 | backend/app/agents/trip_planner_agent.py；backend/app/services/llm_service.py、amap_service.py、unsplash_service.py |
| 依赖/示例 | backend/requirements.txt；新增 backend/requirements-dev.txt；backend/.env.example；frontend/package.json、package-lock.json、.env.example、.gitignore |
| 测试 | 新增 backend/tests/conftest.py、backend/tests/test_phase1.py |
| 文档 | docs/progress.md、docs/refactor_plan.md、docs/current_architecture.md；新增 docs/phase1.md；README.md 增补当前阶段说明 |

## 架构变化

当前主链为 FastAPI → TripRequest → Constraint Service → TravelConstraints → MultiAgentTripPlanner → 四个 SimpleAgent → MCP/LLM。已有统一配置、错误、日志和 lifespan 边界，阻塞 I/O 放工作线程；临时用进程内互斥及历史清理隔离请求。尚未实现 LangGraph、缓存、数据库或新的 Agent。地图解析仍是明确未就绪状态。

MCPTool 0.2.9 的发现与调用使用每次操作的 MCPClient async context，SDK 不提供持久会话 close；本阶段不伪造关闭方法。LLM 关闭使用 SDK 的 _client.close 私有字段，已集中在 llm_service.py，版本变更时需复核。

## 实际验证

环境：Python 3.10.1，pydantic 2.13.4，fastapi 0.141.1，hello-agents 0.2.9；Node 24.15.0。

| 命令/检查 | 结果 |
| --- | --- |
| backend 下 python -m pytest tests -q | **55 passed**；9 条旧 Pydantic/FastAPI/SDK/测试客户端弃用警告，无失败 |
| 导入 app.api.main | 成功，不初始化外部客户端 |
| frontend 下 npm ci --ignore-scripts --offline | 成功，从本地缓存安装 128 个包 |
| frontend 下 npm run build | vue-tsc 和 Vite 均通过；仍有 >500kB 产物体积警告 |
| 示例配置/依赖/文档检查 | 示例敏感字段为空；package.json 与 lockfile 直接依赖匹配；本地 Markdown 链接有效 |

测试覆盖 Phase 1 全部边界，以及日期推导/冲突、30 天限制、枚举和数值范围、列表规范化、必去/避开冲突、显式字段优先、提取值补缺、约束不可变、旧请求兼容、Planner 约束输入与校验先于 Planner 初始化。

测试禁止外网 socket 连接，仅放行 Windows asyncio 内部 socketpair 所需 loopback；外部 SDK 调用使用替身，未调用真实 LLM/MCP/Unsplash。测试最初的网络拦截误伤 Windows loopback，修正测试隔离后通过。前端依赖安装和构建生成 node_modules/dist（已在 ignore 中）。测试不是联网质量评估或性能 benchmark；没有性能收益数据。

## 遗留问题与边界

1. Git 已在 `main` 分支初始化，基线提交为 `73d0e36`；Phase 2 修改当前尚未提交。
2. 三类检索仍走 Agent 串行调用；Service parser 和统一 Tool Runtime 留到 Phase 4/5。SDK 可能把工具失败转为普通文本，尚不能证明所有底层失败都会向外抛出。
3. 仅应用日志与 API 已去除原始敏感内容；第三方 HelloAgents/MCP 内部仍可能 print 工具参数/异常，本阶段没有修改 site-packages 或全局重定向 stdout；上线前需在 Tool Runtime 阶段统一收敛。run.py 的访问日志关闭不影响用户自行执行 uvicorn 的默认日志选项。
4. 未做真实 API/地图联调，MCP 会话异常清理依赖 SDK；仅验证了应用的生命周期回调。
5. LLM_TIMEOUT 是单次客户端超时，不是四 Agent 总 deadline；SDK 内部重试、客户端断开后的任务取消和前端 120 秒 timeout 尚未统一。同步工作线程不能靠超时强制杀死。
6. 当前只允许每进程一个规划执行，多 worker 各自隔离；不是分布式并发控制或持久状态。LangGraph 请求状态仍待 Phase 3。
7. 日期和请求级约束已结构化；预算汇总、坐标/来源、开放时间及硬约束结果验证仍未实现。模型合法不等于行程可行；原 JSON 截取方式暂留，Structured Planner 在 Phase 10。
8. 旧弃用告警与前端大包警告未在本阶段扩大处理；backend 全依赖环境未从零安装，仅固定已验证的 SDK 并补直接依赖。
9. 旧示例凭据已移除但未撤销；若真实，仍需持有人轮换。

## 下一阶段建议

只执行 Phase 3 LangGraph 基础 Workflow：建立请求级 typed state 和最小图编排，以现有 Planner 作为适配节点；不提前实现 Phase 4 的检索解析与并发。不自动进入下一阶段。

## Phase 0 记录

已完成入口/调用链/问题/复用分析，创建三份文档；17 个原始 Python 文件 AST 检查通过；离线复现原模型与失败路径问题。当时前端缺 vue-tsc，本阶段已通过缓存安装依赖并构建。
