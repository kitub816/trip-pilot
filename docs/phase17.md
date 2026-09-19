# Phase 17：Docker Compose 与 CI

完成日期：2026-09-19。

新增 backend Dockerfile（Python 3.10、requirements.txt、uvx/MCP 启动依赖）、frontend 多阶段 Dockerfile（Node 22 构建、Nginx 同源 /api 代理）、各自的 .dockerignore、compose.yaml、根目录 .env.example 和 GitHub Actions 验证工作流。Compose 包含 Redis 与 MySQL；后端等健康检查通过后启动。所有外部密钥通过环境变量注入。

修改：backend/Dockerfile、backend/.dockerignore、frontend/Dockerfile、frontend/.dockerignore、frontend/nginx.conf、compose.yaml、.env.example、.github/workflows/verify.yml。

验证：使用非功能性占位环境变量运行 docker compose config --quiet 通过；前后端镜像均真实构建成功。docker compose up -d 启动四个服务，MySQL/Redis 健康检查通过；127.0.0.1:18080 首页与经 Nginx 代理的 /api/trip/health 均返回 HTTP 200。临时容器已 docker compose down，未删除数据卷。后端回归最近一次 154 passed、2 skipped。CI 工作流尚未在 GitHub 执行；依赖文件仍有版本范围，尚非完全锁定的构建。首次后端构建因 Python 包源下载超时失败，增大超时并加入 pip 构建缓存后重试成功。npm ci 报告 15 个依赖告警，需单独审计。

下一阶段：修订 README、给出真实 benchmark 边界与求职表述，不编造线上性能。
