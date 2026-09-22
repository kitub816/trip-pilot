# Phase 26：本地持久 LangGraph checkpoint
完成日期：2026-09-22。

固定 langgraph 1.0.10、langgraph-checkpoint 4.2.0、langgraph-checkpoint-sqlite 3.1.1。新增可选 SqliteSaver 注入，线程 ID 仅接受字母数字下划线与连字符；重复创建已有 ID 拒绝，resume 从 pending 节点继续，已完成状态直接返回，已终止错误保持原安全类型。

新增受限序列化器：允许项目明确的 Pydantic/数据类/枚举，不启用 pickle；业务 AppError 只按安全 code 保存与恢复。SQLite 文件包含用户请求和计划，是本地私有数据，默认 gitignore 排除。模型密钥不在工作流 state 中。

## 使用
后端目录先安装 requirements-dev.txt。推荐项目虚拟环境；本机已创建 .venv（复用系统基础包，但新 LangGraph 组合仅安装在此环境，没有修改全局包）。

首次运行（真实调用取决于当前 provider 配置）：
    .venv/Scripts/python.exe -m evaluation.durable_plan --db local.sqlite --thread-id demo --request request.json --output plan.json
中断后：
    .venv/Scripts/python.exe -m evaluation.durable_plan --db local.sqlite --thread-id demo --resume --output plan.json

request.json 按 TripRequest API schema 填写。CLI 不自动写 MySQL；现有网页 POST 行为不变。仅支持本地单操作者，同一 thread 不应并发调用；SQLite 数据和应用版本需要配套管理。未实现 HTTP/网页自动恢复、所有权鉴权、跨版本迁移或自动清理。

## 实际验证
稳定组合下全量后端 205 passed、2 skipped、8 warnings；新增真实 SQLite 重开、独立 Python 子进程读取、路线节点模拟中断后恢复、重复 ID 拒绝、终止错误、两线程隔离。规划节点已完成时不重跑模型；正在执行的节点仍可能重试，不承诺供应商调用 exactly-once。模型调用预算未跨进程累计，恢复场景暂不承诺全任务调用配额。

本机 .venv 复用全局基础包，pip 对全局额外 langchain-openai/gradio-client 报版本冲突；这两者不是当前项目声明依赖，当前回归通过，但这不等于完成全新环境安装/远端 CI。全局 LangGraph 预发布版保留，运行新功能应使用项目 .venv 或重新安装项目 requirements。

修改 .gitignore、backend/requirements.txt、app/workflows/trip_workflow.py、app/services/checkpoint_service.py、evaluation/durable_plan.py、tests/test_phase26_checkpoint.py 和文档。工作流可选落盘，最终计划存储仍由原 MySQL 服务负责。

参考：LangGraph 官方 SQLite saver 文档 https://reference.langchain.com/python/langgraph.checkpoint.sqlite/SqliteSaver 。下一项修正浏览器/Nginx 请求超时；远端 CI 等待用户提供仓库与推送授权。
