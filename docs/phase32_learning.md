# TripPilot Phase 32 学习文档：供应商请求为何要控制代理环境

## 1. 从表面错误追到真实原因

网页提示“未获取到有效景点”，业务层对应 `NO_CANDIDATES`。但这不等于高德真的返回零条：检索服务允许单项上游失败，多个景点查询都失败后才形成无候选终态。

诊断顺序是：确认 MySQL 已正常 → 复现 MCP 搜索 → 只分类脱敏错误 → 直接调用同一高德 API。最终证据为：MCP 返回 `Request failed`，错误类型含 `ProxyError/SSL EOF`；相同 Key 绕过环境代理后返回 `status=1`、`infocode=10000` 和有效 POI。

## 2. 为什么显式 MCP env 仍不够

项目给 MCP 子进程传入 Key，但固定版服务内部使用 `requests`。在 Windows 上，`requests` 除环境变量外还可能读取系统代理设置。只是不复制 `HTTP_PROXY`，不能保证请求直连。

因此项目显式设置：

~~~python
return {
    "AMAP_MAPS_API_KEY": key,
    "NO_PROXY": no_proxy,
    "no_proxy": no_proxy,
}
~~~

同时设置大小写版本是为了兼容 Windows/Linux 和不同 HTTP 客户端。已有 `NO_PROXY` 条目会保留，高德域名去重追加；代理 URL和凭据不会进入子进程。

## 3. 为什么公交客户端还要 trust_env=False

公交坐标路线因第三方 MCP stdout 缺陷走项目自己的 `httpx.AsyncClient`。如果只修 MCP，公交仍可能读取工作站代理，所以该客户端也显式使用 `trust_env=False`。这是一项供应商级网络策略，不应全局关闭其他客户端的代理支持。

## 4. 测试与真实验证如何分层

离线测试验证 `NO_PROXY/no_proxy` 一致、保留已有条目、不重复高德域名、不复制代理变量；既有公交 MockTransport 测试证明请求解析与限流行为未回归。

真实验证只报告观察到的结果：Windows 本地 MCP 返回 6 个北京 POI，前端代理 API 同样返回 6 条。Docker 容器仍在 TLS 握手阶段失败，所以不能把本地成功外推成容器成功，也没有在本阶段声称 LLM 完整规划成功。

## 5. 面试讲法

“页面最初报无候选，但我没有把它当数据为空。我沿着 Retrieval → ToolRuntime → MCP → Provider 分层探针，发现固定版 MCP 的 requests 读取 Windows 系统代理，导致高德 TLS 被提前断开。修复时只给高德子进程增加 NO_PROXY，并让项目自有的高德 HTTP 客户端关闭环境代理继承，避免影响其他供应商。离线回归 219 passed、2 skipped；真实验证限定为 Windows 本地返回 6 个 POI。Docker 网络仍失败，因此文档明确保留这个边界。”
