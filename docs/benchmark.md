# Benchmark 方法与边界

运行命令：在 `backend` 目录执行 `python -m evaluation.benchmark`。数据集为 `backend/evaluation/constraint_cases.json`，结果文件为 [benchmark_results.json](benchmark_results.json)。脚本先预热 10 次，再连续测量 100 次，每次执行同一套 3 条约束样例；用 `time.perf_counter` 计时，并从有序样本取中位数及第 95 个样本。

本次环境：Windows-10-10.0.26200-SP0、Python 3.10.1。结果：3 条样例匹配 3 条，P50 0.138 ms、P95 0.174 ms。输入数据的 SHA-256 保存在 JSON 中。重复运行受机器负载影响，数值会变化。

测量范围仅包括本地 JSON 读取、Pydantic TripRequest 校验和 Constraint Service，不包括检索、MCP 子进程、模型调用、路线矩阵、数据库或 HTTP。不能把该数值当作完整规划延迟。没有真实 provider usage 与 API 账单，也没有足够的样本计算真实规划成功率、工具成功率、缓存命中率或 RAG 准确率。
