# Phase 25：故宫官方证据与营业、免预约约束
完成日期：2026-09-22。

## 官方来源与边界
- 故宫导览：https://www.dpm.org.cn/Visit.html （官网检索结果核对旺季 08:30 开放、16:00 停止入馆、17:00 闭馆）。
- 故宫参观须知：https://www.dpm.org.cn/singles_detail/259831.html （实际读取，预约要求与周一节假日例外）。
- 真实高德 POI 查询确认故宫博物院主条目 B000A8UIN8，坐标 116.397029,39.917839；不把午门或检票处当成主馆。

内置 backend/data/palace_evidence.json，保留抓取时间、来源、适用期。2026-09-22 至 2026-10-31 是本项目人为限定的维护范围，不是官方承诺期间。超期需重查；临时开放公告、法定节假日例外和冬季未编码。仅主 POI 命中，不覆盖宫内所有地点。RAG_KNOWLEDGE_PATH 可替换默认语料。

## 实现
类型化 OpeningWindow 校验月份和本地起止时刻；计划到访必须满足开放、停止入馆与闭馆时间。没有时刻保留 OPENING_TIME_UNVERIFIED，不声称已验证。
预约要求默认展示 warning；勾选“仅安排无需预约的景点”后，需要预约或证据未知均拒绝通过。周一只提示核对例外，不伪造节假日日历。此功能不代表已买票、实时余票查询或预约时段核验。

计划保存 evidence 与 validation_warnings；结果页展示官方链接与中文提示。编辑重新读取服务端可信语料，覆盖客户端回传证据。空或过期语料也显示缺失警告。只有硬错误送入重规划，warning 不要求模型凭空补证据。容器增加 COPY data。

## 修改与架构
修改 backend/app/models/{knowledge,schemas,validation}.py，services/{constraint_service,rag_service,validation_service}.py，workflows/trip_workflow.py，agents/trip_planner_agent.py，api/routes/trip.py，Dockerfile，新增 data/palace_evidence.json 与 tests/test_phase25_palace.py；同步旧测试替身、前端 Home/Result/types 与浏览器用例。
架构继续由本地证据检索、确定性 Validator 与 LangGraph 重规划组成；并非新增向量检索，也没有让模型生成官方事实。

## 验证
后端 202 passed、2 skipped、9 warnings；浏览器 8 passed；前端 build 通过。覆盖开放前、停止入馆边界、闭馆后、正常时段、未知预约、免预约硬约束、无时刻、证据过期与可信重载、浏览器来源可见。未重新跑真实完整规划、Docker 构建或远端 CI，不能宣称这些验收通过。
最初新增空证据 warning 导致原重规划测试失败，修复为只发送 error 后全量通过。

下一步：持久 checkpoint 与中断恢复；随后扩大官方语料和真实综合评测。预约购买、实际票面时段核验、无障碍事实仍是缺口。
