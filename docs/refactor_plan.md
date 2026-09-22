# TripPilot 渐进重构计划

本计划基于 [现状分析](current_architecture.md)，规格来源为根目录 `docs-project_spec.md`。Phase 0–20 的阶段代码与记录已落地；剩余规格缺口见 progress。实际范围、验证与限制见 [progress.md](progress.md)。

## 迁移原则与落点

保留 `backend/app/api/main.py`、现有路由及 Vue 两页，维持 TripPlanResponse 的兼容适配。先修复失败语义和请求隔离，再接 LangGraph；不能将 AmapService 当前的空结果 TODO 当成可用检索。LangGraph 管控流程，POI/天气/酒店/路线是 Service，LLM 保留语义提取与规划。预算、时间和硬约束采用代码。

预期主链逐阶段形成：TripRequest → TravelConstraints → LangGraph State → 检索 Service → 候选及路线 → Planner → 确定性 Validator → 有上限的 Replan → TripPlan。未完成的节点必须显式声明不可用，不能用虚构结果伪装成功。

## 分阶段实施与验收

| Phase | 针对现有代码的改动 | 验收与范围边界 |
| --- | --- | --- |
| 1 配置、日志、异常（已完成，限制见 progress） | 整理 config.py 的双套 LLM 配置和 .env 查找；示例凭据改占位符；补直接依赖；将 trip.py、map.py、poi.py 的错误统一，停用成功式虚构 fallback；修复 agent.agent 健康检查；给请求加关联 ID；明确共享 Agent 历史隔离及资源关闭 | 缺配置、上游失败、解析失败有可区别错误；健康检查不报属性错误；日志不含密钥；离线两请求不互带历史。暂不接 LangGraph/数据库 |
| 2 Constraint Engine（已完成，限制见 progress） | 在 models 下从 TripRequest 渐进增加 TravelConstraints；日期改为可验证类型，推导天数；结构化预算、人数、must/avoid、交通/步行上限；free_text_input 仅需语义理解时调用提取器 | 反向日期/冲突天数拒绝；显式字段与提取字段冲突规则有测试；现有前端输入经适配可用 |
| 3 LangGraph 基础（已完成） | 已建立 `TripWorkflowState` 和 `START → plan → END` 最小图；路由构建约束后按请求创建图，旧 Planner 作为适配节点注入 | 57 项后端测试通过；替身 Planner 覆盖成功与 `AppError` 失败终态；无 checkpointer、恢复或检索并行 |
| 4 检索与 asyncio（缺口在 Phase 5 补齐） | POI/天气/详情/geocode/路线按服务源码格式解析；异步 Service 取代检索 Agent | 真实响应形状、并发重叠、超时部分失败测试通过；无候选终止，不伪造坐标 |
| 5 Tool Runtime（已完成） | 原生 MCP 独立会话；参数/schema 校验、单次和总超时、有界重试、全局配额和 provenance；关闭时清理 | 84 项回归通过，包括真实本地 stdio 子进程超时退出；HTTP 断开和同步 LLM 取消仍有限制 |
| 6 Redis（已完成） | Amap 类型化结果边界接入可选 Redis；版本化规范参数哈希键，POI/geocode 24h、路线 30m、天气 10m，缓存 envelope 与二次 Pydantic 校验 | 命中、过期、参数隔离、损坏值、取消与断连回源测试；真实一次性 Redis 容器验证读写和 TTL；未缓存完整 Prompt、state 或 LLM 结果 |
| 7 MySQL（已完成） | SQLAlchemy + PyMySQL 保存请求、计划、状态和乐观锁版本；提供 GET/PUT；业务计划记录与 LangGraph checkpoint 分离 | SQLite 文件重启与真实 MySQL 8.4 容器验证；前端切换、Alembic、鉴权和中断工作流恢复尚未完成 |
| 8 Budget Engine（已完成） | 从门票、餐饮、酒店和新增每日交通单价生成 Budget；按人数、两人一间及实际住宿夜数计算，0/null 分离，输出未知项与上限三态 | 人数、房间、夜数、临界值、未知费用、负数、单日和末日酒店测试；LangGraph 与 PUT 都覆盖 LLM/客户端总价 |
| 9 Route Optimizer（已完成） | 复用 AmapService 的 RouteInfo、Tool Runtime 与 Redis 路线缓存；每天最多 6 点构建有向矩阵，固定首点作确定性最近邻排序；新增类型化路段和每日路线汇总 | 12 项专项测试覆盖可复现顺序、四种交通输入、并发/规模、不可达、分段与步行限制、取消和矩阵截止；不声称 TSP 最优或前端折线为真实路网 |
| 10 Structured Planner（已完成） | 私有 PlannerDraft 使用 extra=forbid；候选映射为 A/H 作用域 ID，服务端水合 POI 与请求事实；默认一次修复、50k 响应上限 | 13 项专项测试覆盖稳定 ID、可信水合、未知引用、日期/索引、额外字段、三餐和修复上限；真实模型遵循率、候选数量与 token 预算仍待评测/网关阶段 |
| 11 Validator + Replan（已完成） | 新增类型化 PlanViolation/Result 和确定性 Validator；检查当前有证据的日期、预算、must/avoid、重复与路线告警；LangGraph 以 error violations 触发默认一次 Replan，PUT 写前复验 | 11 项专项测试覆盖正反例、修正规则、一次成功/上限终止和 PUT 拒写；开放时间、时段和预约没有证据，明确留给 RAG 阶段 |
| 12 RAG（已完成，限制见 progress） | 以候选景点 ID 读取带来源、抓取时间、适用期和状态的本地证据；输入 Planner，Validator 仅检查适用的 verified 闭园事实 | 默认空语料和损坏语料明确返回不确定；未提交虚构官方资料，远程知识库/前端引用展示待后续 |
| 13 Model Gateway（已完成） | 新增请求级 ModelGateway，集中调用次数、Prompt 长度、本地 token 估算和 429/超时分类；Planner 初始调用、修复和 Replan 共用预算 | 离线替身验证边界；SDK 缺可靠 provider usage，未实现真实账单、fallback 或流式策略 |
| 14 Observability（已完成） | JSON 白名单日志关联请求 ID、HTTP 状态/耗时、稳定错误码与 LangGraph 节点事件；避免输出输入、Prompt 和异常原文 | 离线日志测试通过；跨节点聚合指标、缓存命中率和真实模型用量尚未接入 |
| 15 Evaluation（离线基线已完成） | 新增 3 条固定约束案例与确定性评测服务，复用约束构建路径并输出逐例结果 | 3/3 离线样例通过；真实提取、工具/计划成功率、Token/成本和缓存命中率仍缺供应商数据 |
| 16 Frontend（已完成，端到端验收待补） | 延续 Home/Result；统一图片 API baseURL、取消/限流/去重；地图独立加载；增加结构化约束输入及真实状态；编辑调用服务端校验重算；地图输出处理不可信文本 | build 通过；浏览器验证错误/降级/恢复、编辑预算更新、非 localhost 部署；保留导出能力 |
| 17 Docker + CI（本地构建/冒烟完成） | 基于 backend/requirements.txt、frontend/package-lock.json 明确可重复运行环境；容器包含所需 MCP 启动依赖 | 干净环境构建、离线回归和启动冒烟；凭据从环境注入 |
| 18 README/Benchmark/Resume（已完成） | 修正当前 README 对路线和工具能力的过度描述；报告真实架构与测试限制 | 每条性能数字可追溯到 benchmark 数据及运行条件；无测量不填写 |

## 先处理的具体风险

1. 失败返回 success=True、虚构景点、全局历史跨请求复用：必须在基础阶段消除，不能等评价阶段才发现。
2. MCP 结果解析未实现：先补返回协议与固定样例，再移除检索 Agent，避免迁移后变成全空结果。
3. async 路由包装同步调用：只加 async 关键字或 Promise.all 不会解决后端阻塞；必须覆盖调用栈和共享状态。
4. 输入无硬约束、输出无真实来源：先定义模型再建预算/路线/Validator，不能让模型输出金额充当预算引擎。
5. Git 已初始化并有基线提交；每个后续阶段继续以真实 diff 和测试结果更新进度。

## 后续工程缺口

真实官方 RAG 语料、自由文本提取、景区营业时间/预约约束、持久 checkpoint、真实 LLM/高德端到端评测和 CI 远端运行仍需继续；这些不能用阶段编号或离线样例替代。

## Phase 19 到访时间窗（已完成）

计划景点支持可选时刻，服务端按时长和路线交通秒数校验内部时间冲突。没有时刻的旧计划不做完整时间断言；景区开放时间与预约事实仍待真实证据。详见 [phase19.md](phase19.md)。

## Phase 20 真实服务初测（局部通过）

修复候选坐标路线、MCP 公交 stdout 缺陷和 Planner 酒店未知字段 null；真实三例初测 2/3 成功，北京公交仍返回 422。详见 [phase20.md](phase20.md)。下一步应先定位其剩余路段失败和校验项，再扩大真实案例；不能用小样本推断线上指标。

## 2026-09-22：Phase 21 完成

北京公交真实单例复测通过（运行于 2026-09-20），后端回归 178 passed、2 skipped。已补公交业务限流重试、保序相邻路线查询、带交通秒数的重规划反馈与 Redis 总超时归一化。历史 Phase 20 失败结果保留。详见 [phase21.md](phase21.md)。下一建议是浏览器 E2E；当前阶段完成后停止。

## Phase 22–24 更新

用户已明确授权连续优化。已完成浏览器契约回归、依赖修复和按需导出、自由文本约束提取预览。当前后端 192 passed、2 skipped，浏览器 7 passed，build 通过。下一步官方证据与营业/预约校验；主规划的自动语义提取、全栈浏览器真实联调、持久 checkpoint 与远端 CI 不应声称完成。详见 phase22.md 至 phase24.md。

## Phase 25 更新

故宫官方证据、营业时段与免预约约束、引用和 warning 持久化展示已完成。202 passed、2 skipped；8 项浏览器回归，build 通过。具体边界见 [phase25.md](phase25.md)，下一项持久 checkpoint。
