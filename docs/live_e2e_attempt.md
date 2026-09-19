# 真实供应商端到端冒烟：首次尝试

日期：2026-09-19。运行器：[live_smoke.py](../backend/evaluation/live_smoke.py)。从 backend 目录运行 `python -m evaluation.live_smoke`；使用真实配置发出一条固定的单日上海规划请求，经过 FastAPI TestClient 和 LangGraph 进入 MCP 工具层。运行器只打印状态、耗时和计划数量，不输出密钥或完整计划。

本次结果：HTTP 503、`NO_CANDIDATES`，17.053 秒。日志显示 3 次地图文本搜索和 1 次天气工具调用报告 `UPSTREAM_ERROR`。不含密钥的直接高德探针返回 `URLError`，底层类型 `SSLEOFError`（errno 8）。因此没有候选景点、没有进入 LLM、没有生成计划。原始脱敏汇总在 [live_e2e_attempt.json](live_e2e_attempt.json)。

这次只证明请求进入工具层并安全失败，不能据此判断凭据有效性，也不能计算完整规划成功率、P50/P95、token 或成本。网络/TLS 可用后需复跑，再针对成功计划检查约束和到访时间。
