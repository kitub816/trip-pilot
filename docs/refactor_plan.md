# TripPilot 渐进重构计划

本计划基于 [现状分析](current_architecture.md)，规格来源为根目录 `docs-project_spec.md`。Phase 0–3 已完成；Phase 4–18 为待办。实际范围、验证与限制见 [progress.md](progress.md)。

## 迁移原则与落点

保留 `backend/app/api/main.py`、现有路由及 Vue 两页，维持 TripPlanResponse 的兼容适配。先修复失败语义和请求隔离，再接 LangGraph；不能将 AmapService 当前的空结果 TODO 当成可用检索。LangGraph 管控流程，POI/天气/酒店/路线是 Service，LLM 保留语义提取与规划。预算、时间和硬约束采用代码。

预期主链逐阶段形成：TripRequest → TravelConstraints → LangGraph State → 检索 Service → 候选及路线 → Planner → 确定性 Validator → 有上限的 Replan → TripPlan。未完成的节点必须显式声明不可用，不能用虚构结果伪装成功。

## 分阶段实施与验收

| Phase | 针对现有代码的改动 | 验收与范围边界 |
| --- | --- | --- |
| 1 配置、日志、异常（已完成，限制见 progress） | 整理 config.py 的双套 LLM 配置和 .env 查找；示例凭据改占位符；补直接依赖；将 trip.py、map.py、poi.py 的错误统一，停用成功式虚构 fallback；修复 agent.agent 健康检查；给请求加关联 ID；明确共享 Agent 历史隔离及资源关闭 | 缺配置、上游失败、解析失败有可区别错误；健康检查不报属性错误；日志不含密钥；离线两请求不互带历史。暂不接 LangGraph/数据库 |
| 2 Constraint Engine（已完成，限制见 progress） | 在 models 下从 TripRequest 渐进增加 TravelConstraints；日期改为可验证类型，推导天数；结构化预算、人数、must/avoid、交通/步行上限；free_text_input 仅需语义理解时调用提取器 | 反向日期/冲突天数拒绝；显式字段与提取字段冲突规则有测试；现有前端输入经适配可用 |
| 3 LangGraph 基础（已完成） | 已建立 `TripWorkflowState` 和 `START → plan → END` 最小图；路由构建约束后按请求创建图，旧 Planner 作为适配节点注入 | 57 项后端测试通过；替身 Planner 覆盖成功与 `AppError` 失败终态；无 checkpointer、恢复或检索并行 |
| 4 检索与 asyncio | 补 AmapService.search_poi/get_weather/geocode/plan_route 的 TODO；统一类型化检索结果；以 Weather/POI/Hotel Service 替换三类检索 Agent；覆盖所有偏好并去重；并发三类独立检索 | 固定 MCP 响应样例能解析空/正常/异常；并发探针证明任务重叠，不写未经测量的提速百分比；慢天气/缺酒店不抹掉有效 POI；MCP 并发安全验证前受控串行或隔离会话 |
| 5 Tool Runtime | 合并 planner 和 AmapService 重复 MCP 构造到统一适配器；统一工具名称/schema、参数验证、超时、可重试错误、有界重试、并发配额和 provenance | 假工具覆盖超时、格式错误、限流、取消和部分失败；显式生命周期关闭；确认 SDK 同步桥接的取消边界；在 Phase 4 基础策略上集中实现 |
| 6 Redis | 在检索边界加缓存，键含工具/规范化参数/版本；天气、POI、路线各自 TTL；避免缓存失败为正常空结果 | 命中/过期/参数隔离/Redis 不可用降级测试；不直接缓存带用户敏感要求的完整 Prompt |
| 7 MySQL | 保存计划、请求状态和版本，取代只靠 sessionStorage 的结果来源；工作流 checkpoint 采用匹配的持久化适配方案 | 保存再读、版本冲突、重启恢复测试；明确计划存储与 checkpoint 的边界 |
| 8 Budget Engine | 从 Attraction.ticket_price、Hotel/Meal.estimated_cost 生成费用明细与 Budget；补交通项、人数、实际住宿夜数、币种及未知价格状态 | 汇总一致、非负、预算临界值、未知费用、末日不住宿等测试；LLM 输出 total 不能覆盖代码结果 |
| 9 Route Optimizer | 复用 AmapService 路线工具映射和 Location；标准化 RouteInfo，构建有界路线矩阵，按交通方式确定性排序与时间计算 | 固定矩阵可复现顺序，处理不可达/缺路段；限制步行和交通时间；前端折线不作为真实路网证据 |
| 10 Structured Planner | 改造 PLANNER_AGENT_PROMPT、_build_planner_query 和 _parse_response；模型从候选 ID 中选择，结果按 schema 返回；预算字段由代码补算 | 非法 JSON、未知 POI ID、越界日期被拒绝；有界格式修复；不恢复虚构 fallback；保留现有响应字段适配 |
| 11 Validator + Replan | 新增确定性 validator，LangGraph 按 violations 分支；检查预算、必去/避开、重复、时段、开放时间、交通和步行；Planner 仅处理重排及软偏好 | 每条约束有正反例；无解/达到最大轮数明确终止；修改计划后重算、重验 |
| 12 RAG | 在候选景点 ID 上补官方开放时间/预约/无障碍等证据；输入 Planner 与 Validator | 引用来自真实 metadata（来源、抓取时间、适用日期）；无来源不编引用；缺证据返回不确定，而不是默认为开放 |
| 13 Model Gateway | 在 llm_service.py 的现有 get_llm 边界集中 provider 配置、结构化输出适配、错误分类及用量记录 | 替身测试超时/限流/响应不兼容；明确 fallback 模型策略及总调用预算 |
| 14 Observability | 扩展 Phase 1 日志关联到图节点、MCP、缓存、模型和校验；避免打印完整用户输入 | 一个请求可追踪各阶段和失败原因；记录真实耗时、用量与重试，不把模拟进度当指标 |
| 15 Evaluation | 新建离线约束/工具/计划数据集和在线可选 benchmark；为现有失败探针建立回归 | 固定样例、随机性与环境说明；真实计算提取准确率、满足率、工具/计划成功率、P50/P95、Token/成本和命中率 |
| 16 Frontend | 延续 Home/Result；统一图片 API baseURL、取消/限流/去重；地图独立加载；增加结构化约束输入及真实状态；编辑调用服务端校验重算；地图输出处理不可信文本 | build 通过；浏览器验证错误/降级/恢复、编辑预算更新、非 localhost 部署；保留导出能力 |
| 17 Docker + CI | 基于 backend/requirements.txt、frontend/package-lock.json 明确可重复运行环境；容器包含所需 MCP 启动依赖 | 干净环境构建、离线回归和启动冒烟；凭据从环境注入 |
| 18 README/Benchmark/Resume | 修正当前 README 对路线和工具能力的过度描述；报告真实架构与测试限制 | 每条性能数字可追溯到 benchmark 数据及运行条件；无测量不填写 |

## 先处理的具体风险

1. 失败返回 success=True、虚构景点、全局历史跨请求复用：必须在基础阶段消除，不能等评价阶段才发现。
2. MCP 结果解析未实现：先补返回协议与固定样例，再移除检索 Agent，避免迁移后变成全空结果。
3. async 路由包装同步调用：只加 async 关键字或 Promise.all 不会解决后端阻塞；必须覆盖调用栈和共享状态。
4. 输入无硬约束、输出无真实来源：先定义模型再建预算/路线/Validator，不能让模型输出金额充当预算引擎。
5. Git 已初始化并有基线提交；每个后续阶段继续以真实 diff 和测试结果更新进度。

## 下一阶段执行清单（Phase 4，尚未执行）

先重读 progress.md 与 Amap/MCP 源码。以固定 MCP 返回样例定义 POI、天气、酒店的类型化 parser；将三类检索 Agent 渐进替换为 Service，并对彼此独立的 I/O 建立可验证的并发与部分失败行为。不进入 Phase 5 的统一 Tool Runtime、Redis 或数据库。
