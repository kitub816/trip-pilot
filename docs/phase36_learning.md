# TripPilot Phase 36 学习文档：把真实浏览器验收做成可重复测试

## 1. 为什么离线测试通过仍要跑真实浏览器

离线测试能证明约束算法、错误语义和 API 契约，但不能证明浏览器长连接、高德返回、LLM 输出、路线计算和结果页能在同一次请求中协同工作。Phase 36 用真实 Chromium 从表单开始，最终要求进入结果页，覆盖完整用户路径。

## 2. 明确区分三层测试

- 后端离线回归使用 fixture 和替身，快且确定，适合 CI。
- 浏览器契约回归使用固定 API 响应，验证表单、SSE、恢复和结果页。
- 真实浏览器验收调用本地后端及真实供应商，慢、有成本且可能受网络影响，所以必须显式开启。

实际开关代码：

~~~typescript
const liveEnabled = process.env.TRIPPILOT_LIVE_E2E === '1'
test.skip(!liveEnabled, 'requires the local backend and real configured providers')
~~~

这样普通 `npm run test:e2e` 不会偷偷调用 LLM 或地图服务；只有明确设置环境变量时才运行真实案例。

## 3. 测试必须验证用户输入确实传到了后端

浏览器成功跳转还不够。用例监听规划请求并检查城市、日期、交通、偏好、预算和限制：

~~~typescript
page.on('request', request => {
  if (request.url().includes('/api/trip/plan/stream')) {
    submitted = request.postDataJSON() as Record<string, unknown>
  }
})

expect(submitted).toMatchObject({
  city: '西安',
  travel_days: 3,
  budget_limit: 3000,
  max_single_transport_minutes: 60,
})
~~~

这次检查发现未勾选的布尔字段原来被序列化时省略。后端默认值使业务结果正确，但请求契约不够明确，因此表单状态改为显式初始化：

~~~typescript
const formData = reactive<TripFormState>({
  // ...
  travelers: undefined,
  avoid_reservation_required: false,
})
~~~

## 4. 成功证据如何判定

本次真实请求的可信证据包括：浏览器进入 `/result`；结果页出现 3 个日期页签；景点、到访时间、住宿、餐饮、天气和预算可见；后端对同一请求记录 `stream.completed`。日志耗时 115578 ms 只描述这一次运行，不能写成平均性能。

页面同时显示“部分费用未知”和西安景点缺少官方证据。这些 warning 是正确的不确定性表达，不能为了页面看起来完整而删除。

## 5. 面试讲法

“我把测试拆成离线确定性回归、固定响应浏览器契约和显式开启的真实供应商 E2E。真实用例从 Vue 表单提交 SSE 请求，经过高德、LLM、路线、预算和 Validator，最终检查三天结果页。真实测试不默认进 CI，避免不可控成本；单次 115 秒只作为验收记录，不包装成性能指标。”
