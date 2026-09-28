# TripPilot Phase 33 学习文档：为什么 Agent 需要分层控制重试

## 1. 85% 不代表规则计算卡死

SSE 的 85% 对应 `replanning`。真实日志显示首次规划已经结束，路线与预算也完成；确定性 Validator 发现单段交通超限和到访时间冲突后，LangGraph 才进入一次有限重规划。定位这类问题要按工作流节点看日志，不能只按进度条猜测。

## 2. 三层“重试”不是同一件事

TripPilot 有三种不同机制：

1. JSON 格式修复：模型输出不符合私有 Pydantic schema 时，允许有界修复。
2. 业务重规划：硬约束失败时，LangGraph 把类型化 violation 反馈给 Planner，一次后必须停止。
3. HTTP 传输重试：OpenAI SDK 对超时或连接错误自动重发请求。

前两层具有明确业务语义和调用预算。第三层如果保持 SDK 默认值，会把 180 秒超时放大成三次尝试；对长生成 POST 还可能带来重复计费风险。因此项目关闭第三层隐式重试。

## 3. 实际代码

`backend/app/services/llm_service.py` 在固定版 HelloAgents 创建客户端后设置：

~~~python
_llm_instance = HelloAgentsLLM(
    api_key=settings.llm_api_key.get_secret_value(),
    base_url=settings.llm_base_url,
    model=settings.llm_model,
    timeout=settings.llm_timeout,
    provider="custom",
)
_llm_instance._client.max_retries = 0
~~~

项目已经把对第三方私有属性的访问隔离在 `llm_service.py`；关闭资源时也只在该模块访问 `_client.close()`。依赖升级时，这个边界需要专项回归。

## 4. 为什么不把超时直接降到很低

真实首次规划曾在 180 秒配置下完成，说明长上下文结构化计划可能需要超过 60 秒。直接把超时缩短会增加误杀。当前修复保留用户配置的单次超时，只去掉没有业务语义的额外传输重试，使一次调用的上界与配置一致。

## 5. 面试讲法

“我用 SSE 节点日志确认 85% 不是 Validator 卡死，而是第二次 LLM 调用。项目配置单次 180 秒，但 OpenAI SDK 默认自动重试两次，最坏会变成约 540 秒。由于 LangGraph 已经负责有界重规划，ModelGateway 也负责调用预算，我关闭了 SDK 的隐式重试，让每次业务调用只对应一次传输尝试。完整回归 219 passed、2 skipped；真实供应商重规划仍需单独复测，所以没有把代码修复写成端到端成功。”
