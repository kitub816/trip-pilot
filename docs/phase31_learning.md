# TripPilot Phase 31 学习文档：真实工作流进度流

## 1. 为什么 Agent 规划需要流式进度

一次规划会经历地图检索、模型草稿、路线矩阵、预算与硬约束校验。原网页只显示“等待服务端结果”，用户无法区分正常长任务和断线。Phase 31 让这些真实完成点变成事件；它是**阶段流**，不是 LLM token 流，也不预测剩余时间。

## 2. 请求与事件契约

网页仍发送 `TripRequest`、`X-Trip-Plan-ID` 和 `X-Trip-Owner-Token`，但目标是 `POST /api/trip/plan/stream`。服务端返回 `text/event-stream`，事件只有三类：

~~~text
event: progress
data: {"stage":"retrieved"}

event: result
data: {"success":true,"data":{...},"plan_id":"...","version":2}

event: error
data: {"error_code":"PLAN_VALIDATION_ERROR","message":"...","status_code":422}
~~~

`result` 和 `error` 是终态。原 `POST /api/trip/plan` 继续返回普通 JSON。浏览器使用 `fetch` 读取 POST 响应流，因为原生 `EventSource` 不能直接发送该请求的 JSON body 与所有权 header。

## 3. 事件必须来自真实完成点

实际 `backend/app/workflows/trip_workflow.py`：

~~~python
retrieval = retrieve_trip_context(state["constraints"])
evidence_result = retrieve_trip_evidence(
    retrieval.attractions, state["constraints"].start_date,
    state["constraints"].end_date,
)
self._progress("retrieved")

planner = self._planner_factory()
# ...从候选生成并水合 plan...
self._progress("drafted")
~~~

路线和预算阶段也只在 Service 返回后发送 `routed`、`budgeted`；Validator 确认通过后才发送 `validated`。如果 Validator 要求重规划，则发送 `replanning`，再产生新的草稿和校验事件。前端用 `Math.max` 保证阶段指示不会倒退。任何草稿在校验前都不作为最终计划展示。

## 4. 同步工作流如何给 HTTP 流发事件

现有 HelloAgents 调用是同步的。API 在后台工作线程执行原业务路径，把事件放进请求内队列；SSE 迭代器从队列读取并立即发送。实际 `backend/app/api/routes/trip.py`：

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

心跳避免长模型调用期间代理认为连接空闲。Nginx 对 `/api/` 关闭响应缓冲；接口还发送 `X-Accel-Buffering: no`。每进程最多同时执行 4 个流式规划，以免浏览器连接无限创建工作线程。连接断开不强行中止工作线程，结果仍可走既有 MySQL 计划状态与 SQLite checkpoint 恢复路径。

## 5. 前端读取与失败语义

实际 `frontend/src/services/api.ts` 使用 `response.body.getReader()`、`TextDecoder` 及空行帧边界解析 SSE。收到 `progress` 更新页面；收到 `result` 返回原 `TripPlanResponse`，沿用现有 `plan_id/version` 存储；收到 `error` 生成 `PlanningRequestError`。流意外结束而没有终态，提示用户检查恢复状态。600 秒是客户端总等待上限，不是规划固定耗时。

## 6. 怎样验证确实在流式输出

`backend/tests/test_phase31_streaming.py` 用事件闸门暂停后台规划：先读取 `progress(retrieved)`，再释放工作线程，随后读取 `result`。这证明进度先于最终结果可用。另有真实 LangGraph 替身测试检查阶段顺序，API 测试检查结果结构与安全错误。前端 Playwright 走固定 SSE 契约，不调用真实供应商。

本阶段回归：后端 217 passed、2 skipped；前端 build 和 Playwright 12 passed。真实高德/LLM 加代理长连接仍待验收，不能把这些离线结果称为供应商 E2E。

## 7. 面试中怎么讲

“我把 Agent 长任务的可观测性与结果正确性分开。LangGraph 的检索、草稿、路线、预算和校验完成后发结构化阶段事件，FastAPI 通过 SSE 及时传给页面；未经校验的草稿不会当最终答案。同步 SDK 在受限后台线程中执行，15 秒心跳防空闲断连，断线后仍可按 plan ID 查状态或恢复。进度百分比只是阶段提示，不是时间预测。离线测试证明事件先于结果到达；真实供应商网络与代理尚未完成长连接验收。”

下一步应验证真实供应商下的断线、限流及部署代理表现，再决定是否升级为异步任务/跨实例进度服务。
