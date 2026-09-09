# TripPilot Development Rules

你正在把 Datawhale Hello-Agents 第 13 章智能旅行助手重构为求职项目 TripPilot。

遵守以下规则：

1. 基于现有源码渐进式重构，禁止无必要地从零重写。
2. LangGraph 负责主工作流；Agent 负责决策，Service/普通函数负责确定性业务。
3. 不要为了 Multi-Agent 而 Multi-Agent。天气、酒店、POI、路线等优先做成 Service/Tool。
4. LLM 负责语义理解、结构化提取、规划和软约束判断；预算、时间、距离、排序、硬约束校验必须优先使用确定性 Python 代码。
5. 无依赖 I/O 优先异步并发，并正确处理 timeout、retry、partial failure。
6. 所有核心业务数据尽量使用明确类型和 Pydantic，不要大量使用 Any 和裸 dict。
7. 每个 Phase 只完成当前目标；修改前先读相关源码，完成后必须实际运行测试或最基本的运行验证。
8. 不要为了简历堆技术。当前重点是 FastAPI、LangGraph、MCP、Redis、MySQL、RAG、asyncio、Docker、Evaluation、Observability。
9. README 和简历中的性能数据只能来自真实测试，禁止编造。
10. 持续更新 `docs/progress.md`，把当前代码和该文件作为项目状态事实来源，不依赖聊天历史。

每个 Phase 完成后汇报：
- 做了什么
- 修改了哪些文件
- 架构变化
- 测试结果
- 遗留问题
- 下一阶段建议

完成当前 Phase 后停止，不自动进入下一阶段。