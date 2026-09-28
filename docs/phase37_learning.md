# TripPilot Phase 37 学习文档：多城市真实 E2E 与失败分类

## 1. 为什么一个成功案例不够

西安公交成功只能证明一个输入组合。交通 Service 有公交、步行和驾车三条不同路径，真实验收至少要覆盖这些分支。Phase 37 增加上海步行和杭州自驾，并在请求层断言实际提交的交通方式，防止 UI 自动化仍提交默认值。

## 2. 真实用例必须默认关闭

真实 LLM 和地图调用慢、有成本且受网络影响，因此使用两个环境变量控制：

~~~typescript
const liveEnabled = process.env.TRIPPILOT_LIVE_E2E === '1'
const selectedCases = new Set(
  (process.env.TRIPPILOT_LIVE_CASES || 'xi-an').split(',')
)
~~~

普通测试会看到三个 skip；手动验收可以只跑一个城市，避免无意调用全部供应商。

## 3. 自动化必须确认下拉框真正改变

Ant Design 的 option 可访问性角色在当前版本不稳定。测试改为点击可见下拉项，并检查选择框最终文本：

~~~typescript
const field = page.locator('.ant-form-item').filter({ hasText: label })
await field.locator('.ant-select-selector').click()
await page.locator('.ant-select-dropdown:visible .ant-select-item-option')
  .filter({ hasText: option }).click()
await expect(field.locator('.ant-select-selection-item')).toContainText(option)
~~~

此外，测试监听 `/api/trip/plan/stream` 的 POST body，断言 `transportation`、预算、日期和上限。这一层证明后端收到的不是页面视觉假象。

## 4. 区分业务失败和测试脚本失败

第一次上海结果已经生成，但脚本要求纯文本“预算明细”，实际 UI 带有 emoji，因此断言失败。业务日志是 `stream.completed`，页面快照也有两天完整行程。这属于测试选择器错误，不应记为 Agent 规划失败。

另一次上海请求在 LLM 180 秒边界返回 `UPSTREAM_TIMEOUT`，属于真实供应商失败。用例同时等待结果页与错误消息：

~~~typescript
const outcome = await Promise.race([
  page.waitForURL(/\/result$/).then(() => ({ kind: 'result' })),
  page.locator('.ant-message-error').last().waitFor({ state: 'visible' })
    .then(async () => ({ kind: 'error', message: await errorText() })),
])
~~~

这样失败会快速、明确地落到类型化错误，而不是继续等待十分钟。

## 5. 结果页功能也要验收

真实上海成功重试不仅检查计划，还展开第二天并下载 PDF。测试检查扩展状态、下载错误、PDF 文件签名和最小大小。它证明导出功能能处理真实计划，而不只是固定 fixture。

## 6. 如何报告结果

`live_browser_e2e_results.json` 保存每次 request ID、输入、结果、单次耗时、页面证据和 warning。不能把相关的重复尝试计算成“成功率”，也不能把这些逐次耗时写成 P50/P95。没有 provider usage 时，不报告 token 和成本。

面试中可以说：“我把测试脚本错误、硬约束失败和供应商超时分别分类；三种交通路径都有真实成功案例，同时保留一次超时失败。真实 E2E 默认跳过，逐次证据进 JSON，但不对小样本做成功率或性能包装。”
