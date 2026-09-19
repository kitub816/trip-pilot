# 给新对话的 Prompt

请接手本地 TripPilot 项目，工作目录为 `E:\travel-agents-1\helloagents-trip-planner`。先读取根目录 `AGENTS.md`、`docs-project_spec.md`、`README.md`、`docs/progress.md`、`docs/refactor_plan.md` 和 `docs/handoff.md`，再检查当前 Git 状态与最近提交。注意规格文件在根目录叫 `docs-project_spec.md`，不是 `docs/project_spec.md`。以当前代码、测试和进度文档为事实来源，不依赖旧对话，也不要仅凭 Phase 编号推断原始规格已全部实现。

目前 Phase 0–18 的阶段代码、文档、提交及 `E:\TP各版本文档\1` 至 `18` 的归档学习资料均已完成；交接时最近阶段提交为 `5187096`。后端最近全量离线回归 154 passed、2 skipped；前端构建通过；Docker Compose 曾用占位凭据完成本地首页/API 冒烟。`docs/benchmark_results.json` 中的 P50/P95 只针对本地约束层，绝不可写成全链路性能。真实官方 RAG 语料、自由文本提取、时间窗/预约硬约束、持久 LangGraph checkpoint、真实高德/LLM 端到端评测、浏览器 E2E 和远端 CI 验证仍未完成。

请先简要报告你核对到的状态和最值得处理的下一项缺口；如果我给出具体任务，就直接执行该任务。遵守 `AGENTS.md` 的渐进重构、确定性业务优先、测试和进度更新规则；未经我明确授权连续推进时，完成当前阶段后停止。学习文档若涉及新阶段，必须附实际实现代码，并按既有格式归档到 `E:\TP各版本文档`。不要编造性能、供应商调用结果或成本。