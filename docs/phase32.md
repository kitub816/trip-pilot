# Phase 32：Windows 代理环境下的高德 MCP 直连修复

完成日期：2026-09-28。

## 完成内容

真实运行出现 `NO_CANDIDATES`。脱敏诊断确认固定版 `amap-mcp-server==0.1.11` 内部 `requests` 读取 Windows 系统代理后发生 `ProxyError + SSL EOF`；同一 Key 使用 `httpx(..., trust_env=False)` 直连高德返回 HTTP 200、`infocode=10000` 和有效 POI。

`ToolRuntime` 现在为 MCP 子进程同时设置 `NO_PROXY/no_proxy`，强制 `restapi.amap.com` 绕过系统代理，并保留用户已有直连域名但不复制代理凭据。公交 HTTP 适配器也设置 `trust_env=False`。实际实现：

~~~python
def amap_child_env(key: str) -> dict[str, str]:
    bypasses: list[str] = []
    for name in ("NO_PROXY", "no_proxy"):
        bypasses.extend(value.strip() for value in os.environ.get(name, "").split(",")
                        if value.strip())
    if AMAP_API_HOST not in {value.casefold() for value in bypasses}:
        bypasses.append(AMAP_API_HOST)
    no_proxy = ",".join(dict.fromkeys(bypasses))
    return {"AMAP_MAPS_API_KEY": key, "NO_PROXY": no_proxy, "no_proxy": no_proxy}
~~~

## 修改文件

- `backend/app/services/tool_runtime.py`
- `backend/app/services/amap_service.py`
- `backend/tests/test_phase32_proxy_bypass.py`
- `README.md`
- `docs/progress.md`、`docs/refactor_plan.md`、`docs/handoff.md`
- `docs/TripPilot使用手册.md`、本文件
- `E:\TP各版本文档\32\学习文档.md`

## 架构变化

没有改变 LangGraph、MCP 工具协议或业务规则，只收紧高德供应商调用的网络环境：高德请求不再隐式使用工作站代理。其他网络客户端不受影响。

## 验证

- 代理绕过与既有路线聚焦回归：18 passed。
- 后端完整离线回归：219 passed、2 skipped、1 条 HelloAgents 第三方警告。
- Windows 本地真实高德 MCP 查询：北京“景点”返回 6 个类型化 POI。
- 本地前端 `http://localhost:5173` 返回 200，经 Vite 代理的 `/api/map/poi` 返回 success=true、6 条 POI。

## 遗留问题

Docker Desktop 容器内访问 `restapi.amap.com:443` 仍发生 TLS `UNEXPECTED_EOF`；curl、httpx、较小 MTU和 host network 探针结果一致。Windows 与 WSL 直连成功，因此该问题属于当前设备的 Docker 网络出口，不是本阶段代码已解决的能力。当前可用方式是 Windows 本地后端与 Vite 前端。未重新运行真实 LLM 完整规划，不能声称真实全链路已通过。

## 下一阶段建议

先处理 Docker Desktop 的网络出口或在另一台可用容器主机验证高德 TLS，再执行真实高德+LLM+SSE 的完整浏览器案例。
