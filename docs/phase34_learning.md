# TripPilot Phase 34 学习文档：部分失败不是一律放行或一律失败

## 1. 为什么 LLM 重规划无效

日志显示首次和第二次草稿都完成，但每轮都在同一条公交路线出现 `UPSTREAM_ERROR`，最终 violation 都是 `ROUTE_UNAVAILABLE`。这不是景点顺序或到访时间的语义问题，重复调用 LLM 无法修复供应商对该交通方式没有候选的事实。

## 2. 识别“无公交候选”和“供应商失败”

代码只在以下条件同时满足时回退：

- HTTP 和高德业务状态成功；
- `route` 是合法对象；
- `transits` 是合法列表；
- `transits` 明确为空。

状态失败、限流、超时、缺少字段或类型错误不会触发回退。这样不会把供应商故障伪装成步行路线。

## 3. 实际实现

~~~python
data = parse_payload(payload)
route = data.get("route") if isinstance(data, dict) else None
transits = route.get("transits") if isinstance(route, dict) else None
if isinstance(transits, list) and not transits:
    fallback = await self.runtime.call(
        "maps_direction_walking_by_coordinates", coordinates,
    )
    return self._parse_route(fallback.payload, "walking")
~~~

回退结果仍来自高德坐标路线，不是直线距离或固定时间。`RouteOptimizer` 会继续检查 `max_single_transport_minutes`；超过上限仍生成 `SEGMENT_TIME_EXCEEDED`。

## 4. 测试为什么必须保留限流用例

第一次实现把 `parse_payload` 移出了原有限流捕获范围，专项测试立即发现 HTTP 200 + `infocode=10021` 不再执行一次有界重试。修复后，新分支回到同一异常边界，40 项路线相关测试全部通过。这说明新增降级策略必须与既有 timeout、rate limit 和 protocol error 语义一起测试。

## 5. 面试讲法

“真实规划两次都败在同一条 `ROUTE_UNAVAILABLE`，说明让 LLM 重排不是有效修复。我检查高德响应语义后发现，相邻北京景点会出现成功响应但公交候选为空。公共交通行程允许短途步行，所以只对这个明确状态调用坐标步行工具，仍使用供应商实测距离和时长；真正的错误继续失败。真实探针中天安门到故宫得到 1064 米、851 秒，完整回归 220 passed、2 skipped。”
