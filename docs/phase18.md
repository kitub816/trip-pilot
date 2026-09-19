# Phase 18：README、Benchmark 与求职材料

完成日期：2026-09-19。

重写根 README，修正“Phase 2”“Agent 自动调用地图工具”和前端地图连线等过时表述；按真实源码解释 FastAPI、LangGraph、检索 Service、PlannerDraft、路线/预算/Validator、Redis/MySQL、RAG 证据与 Docker。新增固定约束 benchmark 运行器、原始 JSON、方法说明和可追溯的简历项目表述。

修改：README.md、backend/evaluation/benchmark.py、docs/benchmark_results.json、docs/benchmark.md、docs/resume_project.md、docs/phase18.md、docs/progress.md、docs/refactor_plan.md。

验证：固定约束集 3/3；100 次约束层测量 P50 0.138 ms、P95 0.174 ms（Windows/Python 3.10.1，详见原始 JSON）。最近一次后端完整回归 154 passed、2 skipped；前端生产构建、前后端 Docker 镜像构建和首页/API 200 冒烟通过。性能数字仅适用于本地约束层，不外推至完整规划。

仍未实现：官方真实 RAG 语料、自由文本约束提取、时段冲突与预约硬约束、持久 LangGraph checkpoint、真实 LLM/高德端到端评测，以及 GitHub CI 远端执行。求职材料明确标出这些边界，不将其写成已完成成果。
