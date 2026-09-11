# Phase 6：Redis 类型化检索缓存

完成日期：2026-09-11。

## 目标与范围

本阶段只缓存高德 MCP 已解析、已通过 Pydantic 校验的检索结果，降低重复查询的外部 I/O。缓存不保存完整用户请求、自由文本、LangGraph state 或 LLM 行程；这些数据仍由后续持久化阶段处理。

## 实现

- 新增 `app/services/cache_service.py`：`RetrievalCache` 负责读取、校验、回源和写回；`RedisBackend` 只封装短连接 Redis I/O。
- `AmapService` 的 POI 搜索、天气、地理编码和路线调用接入装饰器。POI 详情仍作为一次搜索的内部补全步骤，因此缓存的是完整、已补全的 POI 列表。
- 键格式为 `trippilot:<版本>:<操作>:<SHA-256>`。哈希输入是按键排序、去除字符串首尾空白后的参数 JSON；版本将高德 MCP 0.1.11 的结果协议和缓存隔离。
- Redis 值是带版本、原键、到期时间和 JSON payload 的 `CacheEnvelope`。命中后 payload 必须再次通过目标 Pydantic 类型校验；损坏、键/版本不符或应用层过期都回源。
- TTL：POI 24 小时、地理编码 24 小时、路线 30 分钟、天气 10 分钟。Redis `EX` 和 envelope 到期时间同时约束有效期。
- Redis 连接、读写和超时均失败开放：记录安全日志后直接回源，不把缓存故障变成地图能力故障。配置为空时完全禁用 Redis。
- 空结果、上游失败导致的不完整 POI 详情、取消请求均不写缓存；取消异常继续向上游传播。每次 Redis 操作建立并关闭独立异步客户端，避免跨 event loop 复用连接。

## 配置与依赖

`Settings` 增加可选 `REDIS_URL` 与 `REDIS_TIMEOUT`（默认 0.3 秒），`.env.example` 给出无凭据样例；新增锁定依赖 `redis==5.3.1`。测试 fixture 显式清空 Redis 配置，保持默认离线。

## 验证

- `python -m pytest tests/test_phase6_cache.py -q`：命中、规范化参数、TTL、键隔离、损坏值、错误降级、空/部分结果不缓存、取消传播、路线和 geocode TTL。
- `python -m pytest tests/test_phase6_redis.py -q`：本地阻塞 socket 验证超时后的连接关闭。
- `TRIPPILOT_TEST_REDIS_URL=redis://127.0.0.1:6380/0 python -m pytest tests/test_phase6_redis.py -q`：一次性 `redis:7-alpine` 容器中真实 Redis 读写与 1 秒 TTL 过期，2 passed；容器已删除。

完整后端回归结果写入 [progress.md](progress.md)。没有声明缓存命中率、延迟或成本收益，因为尚未在真实负载上测量。

## 已知边界

当前没有跨请求 single-flight、缓存预热、主动失效、命中率指标或 Redis 认证/TLS 部署配置。TTL 只能限制陈旧性，不能替代高德数据变更事件；这些能力应结合 Phase 7 持久化、Phase 14 可观测性和 Phase 15 评测再决定。
