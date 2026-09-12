# Phase 12：来源可追溯的旅行 RAG

完成日期：2026-09-12

## 做了什么

新增以 POI 稳定 ID 为键的本地旅行证据检索层。`TravelEvidence` 强制包含来源 URL、抓取时间、适用日期和 `verified/uncertain` 状态；可选的结构化事实包括闭园日期、开放时间、预约和无障碍信息。默认语料为空，未配置 `RAG_KNOWLEDGE_PATH` 或语料损坏时只返回 `EVIDENCE_UNAVAILABLE`，不会制造“开放”或“无需预约”的结论。

LangGraph 的 plan/replan 节点将可用证据送入 Planner Prompt。Validator 仅依据适用日期内、`verified` 的闭园事实产生 `ATTRACTION_CLOSED` error；不确定或缺失证据只保留 warning，因此不会因猜测而阻断计划。

## 修改文件

- `backend/app/models/knowledge.py`：证据、事实和不确定性模型。
- `backend/app/services/rag_service.py`：异步文件语料读取、候选/日期过滤及同步工作流边界。
- `backend/app/config.py`：`RAG_KNOWLEDGE_PATH` 与每 POI 证据上限。
- `backend/app/agents/trip_planner_agent.py`：把证据摘要作为受限 Planner 输入。
- `backend/app/workflows/trip_workflow.py`：请求 state 保存 evidence，并传给 Planner/Validator/Replan。
- `backend/app/services/validation_service.py`、`backend/app/models/validation.py`：证据限定的闭园校验。
- `backend/tests/test_phase12_rag.py`：来源、日期、缺证据和闭园规则测试。

## 架构变化

链路成为：`候选 POI → FileEvidenceStore → TravelRagService → evidence state → Planner / Validator`。RAG 是 Service，不是新的 Agent；它不调用 LLM，也不改变候选身份。当前同步 FastAPI 工作线程通过一个很薄的同步包装进入异步文件读取，后续若接远程知识库应把整个工作流改为 async，并设置独立 timeout/retry。

## 验证

- `backend: python -m pytest tests/test_phase12_rag.py -q`：3 passed。
- `backend: python -m pytest tests -q`：150 passed，2 skipped，10 warnings。
- `git diff --check`：通过。

## 遗留问题

仓库没有可验证的官方景点资料，故不随代码提交虚构语料；要启用真实判断，维护方必须提供带 URL、抓取时间和适用期的 JSON 语料。证据 warning 尚未返回给前端或写入计划记录；预约、时段和无障碍目前只进入 Planner 提示，尚无对应的用户硬约束字段。

## 下一阶段建议

Phase 13 将 LLM 调用集中到 Model Gateway：统一 provider 配置、错误分类、结构化输出适配及真实用量记录，并为调用上限建立测试。
