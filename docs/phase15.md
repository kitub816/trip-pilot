# Phase 15：离线评测基线

完成日期：2026-09-15。

新增固定的 `backend/evaluation/constraint_cases.json` 和纯离线 `run_constraint_cases`。每个 case 记录输入、期望 accepted/rejected，runner 调用实际 `TripRequest` 与 Constraint Service，输出 total/matched。当前基线有 3 条样例，结果为 3/3；该数字只代表该固定约束集，不代表模型准确率、路线成功率或线上性能。

修改：`backend/evaluation/constraint_cases.json`、`backend/app/services/evaluation_service.py`、`backend/tests/test_phase15_evaluation.py`。

验证：专项 1 passed；完整后端回归 154 passed，2 skipped，10 warnings；`git diff --check` 通过。

限制：尚无真实模型、线上工具或延迟/成本 benchmark，且不能由这个小数据集推导 P50/P95、token 成本或 RAG 准确率。下一阶段处理前端输入、状态和服务端更新链路。
