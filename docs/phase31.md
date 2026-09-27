# Phase 31：真实工作流进度流

完成日期：2026-09-27。

## 完成内容

新增 `POST /api/trip/plan/stream`，以 `text/event-stream` 发送 `progress`、`result`、`error` 事件。网页改用该接口显示实际阶段；原有 `POST /api/trip/plan` 的 JSON 契约保留。事件来自检索、草稿、路线、预算和校验代码的完成点，不能代表耗时百分比。最终 `result` 在校验后发出；启用业务存储时还要等写入完成。未经验证的草稿不作为最终计划展示。

实际后端实现片段（`backend/app/workflows/trip_workflow.py`）：

~~~python
retrieval = retrieve_trip_context(state["constraints"])
evidence_result = retrieve_trip_evidence(
    retrieval.attractions, state["constraints"].start_date,
    state["constraints"].end_date,
)
self._progress("retrieved")
# Planner 生成并水合 plan 后才调用 self._progress("drafted")。
~~~

实际流式传输片段（`backend/app/api/routes/trip.py`）：

~~~python
def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

def stream():
    while True:
        try:
            event, payload = events.get(timeout=15)
        except Empty:
            yield ": heartbeat\n\n"
            continue
        yield _sse(event, payload)
        if event in ("result", "error"):
            return
~~~

浏览器使用 `fetch` 的 `ReadableStream` 读取 POST 响应，因为请求需要 JSON body 和所有权 header；按 SSE 帧解析事件，更新阶段提示。`result` 复用原计划响应结构，仍按 plan ID/version 保存并进入结果页。`error` 只传安全错误码与提示。服务端线程继续完成持久化，即使浏览器断线；现有状态检查与 checkpoint 恢复负责后续处理。

## 修改文件

- `backend/app/workflows/trip_workflow.py`、`backend/app/api/routes/trip.py`
- `backend/tests/test_phase31_streaming.py`
- `frontend/src/services/api.ts`、`frontend/src/views/Home.vue`
- `frontend/e2e/trip.spec.ts`、`frontend/playwright.config.ts`、`frontend/nginx.conf`
- `README.md`、`docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`、`docs/TripPilot使用手册.md`、本文件
- `E:\TP各版本文档\31\学习文档.md`

## 架构变化

LangGraph 节点内以可选 callback 发出真实完成事件；SSE 是 API 展示层，不改变 Agent 的决策或确定性校验。每进程最多 4 个流式规划线程；心跳 15 秒，Nginx 关闭 `/api` 响应缓冲。JSON 接口与 HTTP 恢复接口保持原样。

## 验证

- 后端离线全量回归：217 passed、2 skipped、1 条 HelloAgents 第三方警告。
- 新测试确认阶段顺序、进度先于最终计划到达、错误仅含安全公开信息。
- 前端 `npm run build` 通过；Playwright 12 passed（含进度先于结果可见和流中校验失败，固定 API 契约，非真实供应商浏览器 E2E）。
- `git diff --check` 通过。

## 遗留问题

进度条百分比只表示已到阶段，不预测剩余时间；检索与 LLM 仍为同步 SDK 工作，取消浏览器连接不保证停止服务端执行。单进程最多 4 个流式任务，没有跨实例统一调度；真实高德/LLM 长连接及反向代理部署尚未做端到端验收。`resume` 仍返回一次性 JSON，不提供阶段流。

## 下一阶段建议

先用真实供应商与部署代理验证长连接、心跳、断线恢复和限流行为；之后再考虑按浏览器 token 明确授权保存可编辑偏好。
