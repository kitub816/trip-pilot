# Phase 37：多城市真实浏览器验收与可审计结果

完成日期：2026-09-28。

## 完成内容

真实 Playwright 用例扩展为三个可选择场景：西安公交 3 天、上海步行 2 天、杭州自驾 2 天。每个场景从 Vue 首页选择日期、交通、住宿、偏好和硬约束，提交真实 SSE 请求，再检查城市标题、天数、预算和天气。测试会核对实际 POST 载荷，避免自动化看似选中但仍提交默认值。

上海场景还会展开最后一天并导出 PDF，检查下载成功、文件头为 `%PDF-` 且大小超过 1 KB。页面等待同时监听结果 URL 和 Ant Design 错误消息；真实 LLM 超时时立即留下明确诊断，不再空等结果页超时。

逐次结果保存于 `docs/live_browser_e2e_results.json`。当前记录包含西安完成、上海完成、杭州完成、一次上海 `UPSTREAM_TIMEOUT`、以及上海重试完成并导出 PDF。相关尝试不是随机独立样本，不能计算或宣称线上成功率、性能、token 或成本。

## 修改文件

- `frontend/e2e/live-trip-real.spec.ts`
- `frontend/package.json`
- `docs/live_browser_e2e_results.json`
- `README.md`
- `docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`
- `docs/TripPilot使用手册.md`
- `docs/phase37_learning.md`
- `E:\TP各版本文档\37\学习文档.md`

## 架构变化

运行时主链不变。测试体系增加可按 `TRIPPILOT_LIVE_CASES` 选择的真实场景层，并把供应商失败与 UI 断言失败分开记录。普通 CI 默认跳过三个真实用例。

## 验证

- 西安公交：完整结果页，后端 `stream.completed`，115578 ms。
- 上海步行：完整结果页，真实步行路线；最终重试同时完成最后一天切换和 PDF 校验，120109 ms。另一次完成尝试为 129000 ms。
- 杭州自驾：Playwright 正式通过，真实驾车路线，110782 ms。
- 上海另一次尝试：LLM 180 秒边界返回 `UPSTREAM_TIMEOUT`，未生成虚假结果。
- 前端生产构建：通过。
- 默认 Playwright：12 passed、3 skipped；三个 skip 是显式真实供应商用例。
- JSON 结果文件可解析。

## 边界与遗留问题

- 单次时长仅是逐次验收记录，不是全链路 P50/P95。
- 真实结果仍有 `BUDGET_INCOMPLETE` 和 `EVIDENCE_UNAVAILABLE`，西安、上海、杭州官方语料没有补齐。
- 测试浏览器没有高德 JS Key，地图组件未验收；POI、天气和路线后端调用已执行。
- Unsplash 照片请求失败时返回 502，前端显示本地占位图；不影响行程，但照片供应商仍需独立修复或移除。
- 真实用例需要本地凭据，会产生供应商调用，不能默认放入 CI。

## 下一阶段建议

为真实场景增加独立评测运行器与失败分类汇总，扩大官方景区语料；若继续处理 UI，优先验证带高德 JS Key 的地图和照片服务，而不是继续增加相似成功样本。
