# Phase 27：长规划请求等待与弃用清理
完成日期：2026-09-22。

真实北京成功请求曾耗时 132.63 秒，而前端原规划请求超时仅 120 秒，Nginx 未显式设置长请求读取等待。现规划 POST 设置 600000ms，代理读写等待设置 600s；普通 API 仍使用原 120 秒。超时提示明确服务端可能仍在处理，不承诺客户端断开会取消后端任务。这是等待配置修复，不是性能提升或统一服务端截止时间。

项目自身 FastAPI Query/Pydantic Field 的 example 改为 examples，去除七项弃用警告；第三方 HelloAgents 仍有一项，未改供应商包。

验证：项目 .venv 后端 205 passed、2 skipped、1 warning；浏览器 9 passed，新增受控时钟推进 121 秒后仍接收成功结果；前端 build 通过，原有大包警告保留。受控时钟不是实际耗时 benchmark。

修改 frontend/src/services/api.ts、frontend/nginx.conf、frontend/e2e/trip.spec.ts、backend/app/models/schemas.py、backend/app/api/routes/map.py 和文档。主架构不变。服务端取消、全局截止时间、HTTP checkpoint 恢复、远端 CI 和大样本真实评测仍未完成。

容器验证阻塞：Docker Engine 未启动或不可连接；已尝试启动现有 Docker Desktop，仍无法连接 named pipe。Nginx 配置尚未实际执行 nginx -t，需引擎恢复后补验，未声称容器通过。远端 CI 等待目标仓库和新分支推送授权。
