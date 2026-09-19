# Phase 16：前端约束与服务端编辑

完成日期：2026-09-19。

沿用 Home/Result 两页。Home 新增人数、预算、必去/避开、每日步行和单段交通上限输入，直接送入现有 TripRequest；去掉模拟百分比阶段文本，保留真实等待状态，并在离开页面时取消请求。API 统一使用 VITE_API_BASE_URL 或同源地址，不再硬编码 localhost。

Result 优先用 plan_id 读取服务端计划及版本；编辑时 PUT 发送 expected_version，只有后端路线/预算重算与 Validator 通过后才更新本地展示。未启用持久化时明确禁止编辑。预算未知与超限状态有提示。图片请求使用统一 API、按名字去重且最多 6 项，地图不再等待图片；占位 SVG 不插入未经信任的景点名称。

修改：frontend/src/services/api.ts、frontend/src/types/index.ts、frontend/src/views/Home.vue、frontend/src/views/Result.vue。

验证：frontend npm run build 成功；git diff --check 通过。未做浏览器端到端测试；构建报告仍有 2MB 级大包告警。下一阶段处理容器化和 CI。
