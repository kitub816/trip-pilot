# Phase 1：运行与验证

## 配置

将 backend/.env.example 复制为 backend/.env，填入 AMAP_API_KEY、LLM_API_KEY、LLM_MODEL_ID；LLM_BASE_URL 使用所需的 OpenAI-compatible 服务地址。应用只读取固定 backend/.env，系统环境变量覆盖文件，同一来源中 LLM_* 优先于兼容别名 OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL。不再借用相邻 HelloAgents/.env。

LLM_TIMEOUT 默认 60 秒，是单次 SDK 请求 timeout；并非整个计划截止时间。Unsplash 密钥可选，缺少时图片接口返回配置错误，行程功能不依赖图片配置。密钥不得写入示例或提交版本库。

在 backend 下执行：

```powershell
python -m pip install -r requirements-dev.txt
python run.py
```

默认 DEBUG=false，不启动 reload。run.py 关闭 Uvicorn 访问日志；自行用 uvicorn 启动时可加 --no-access-log 以避免 query string 被记录。应用日志为 JSON 事件，request_id 可与响应 X-Request-ID 对应。

## API 行为

成功仍保持 TripPlanResponse。失败返回非 2xx 状态及统一字段：

```json
{"success": false, "message": "安全错误说明", "error_code": "PLAN_PARSE_ERROR", "request_id": "服务器生成ID", "detail": "安全错误说明"}
```

- 422 VALIDATION_ERROR：输入结构不合法，不返回输入值。
- 502 PLAN_PARSE_ERROR / UPSTREAM_ERROR：生成结果解析失败或上游失败。
- 504 UPSTREAM_TIMEOUT：可识别的超时（包含异常原因链）。
- 503 CONFIGURATION_ERROR / SERVICE_BUSY / FEATURE_NOT_READY：配置缺失、已有规划执行或解析未实现。
- 500 INTERNAL_ERROR：未知错误，隐藏原文。

/health 只证明进程可响应；两个 /api/*/health 是配置检查，不是外部连通性探测。未实现的地图 POI/天气/路线解析明确返回 503，暂不发起无用的 MCP 调用。重叠规划在同一进程被拒绝，每个已接受请求前后清理历史。

## 离线验证

```powershell
# backend 下
python -m pytest tests -q
# frontend 下
npm ci --ignore-scripts --offline
npm run build
```

本机已有 npm 缓存，因此离线安装成功；其他环境缺缓存时需要正常 npm ci。测试使用替身与真实 SimpleAgent 的内存历史逻辑，禁止外网，未测试真实模型质量和 MCP 服务器。当前结果是 31 个测试通过、前端类型检查和构建通过；已知限制详见 [progress.md](progress.md)。
