# Phase 24：自由文本约束提取预览
完成日期：2026-09-22。

新增 POST /api/trip/extract，复用 HelloAgents/ModelGateway，每次预览最多一次模型调用；输入 2000 字符、输出 16000 字符上限。Pydantic 检查人数、预算、币种、地点冲突及数值范围，接受完整 JSON 或完整 json 代码围栏，拒绝混杂说明文字；日志只记录错误类型。

前端“提取约束预览”展示结果，确认后只填入空白字段，不覆盖显式输入。默认人数由空白回落为 1，避免默认值阻止提取。确认字段使用原请求和持久化接口，编辑时仍按确定性约束校验。未点击提取的自由文本仍仅交给 Planner，不自动成为硬约束。

首次真实提取未通过解析；兼容完整 JSON 围栏后，一条真实探针返回预期的两人、总预算3000元、必去故宫、避开长城、每日5公里、单段45分钟。见 phase24_live_extraction.json。不能从单例推断语义准确率；token/成本未取得，仍为 null。软偏好、外币、人均预算换算、过敏和无障碍不属于本次提取范围。

验证：后端 192 passed、2 skipped、9 warnings；浏览器 7 passed；前端 build 通过。浏览器新增确认不覆盖与失败恢复用例；修复预算输入可访问名称、导出改为点击展开，日期测试等待面板关闭后继续，避免动画竞争。

修改：backend/app/services/extraction_service.py、api/routes/trip.py、errors.py、tests/test_phase24_extraction.py；frontend/src/views/Home.vue、Result.vue、services/api.ts、types/index.ts、e2e/trip.spec.ts、playwright.config.ts；进度与真实探针记录。架构新增独立预览接口，不隐式增加每次规划的模型调用。

遗留：需要更大语义评测集；预览结果仍由用户核对。主规划尚无统一总截止时间，持久 checkpoint、官方证据和预约/营业校验、远端 CI 仍需推进。
