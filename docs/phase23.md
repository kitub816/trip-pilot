# Phase 23：依赖修复与导出按需加载
完成日期：2026-09-22。

对前端执行 npm audit fix 更新兼容依赖，剩余 jsPDF 单独升级到 ^4.2.1；保留 package-lock 可复现安装。当前 npm audit 报告 0 项漏洞（仅代表当前依赖数据库扫描结果，不是无漏洞保证）。

Result 路由改为动态加载，html2canvas/jsPDF 在点击导出时并发导入。原主 JS 2193.57 kB，当前主 JS 1584.77 kB，导出库拆分为独立文件；这是构建产物大小，不是用户延迟测试，大包警告仍存在。

验证：前端 build 通过；Chromium 5 passed，新增实际 PDF 下载，验证 %PDF- 文件头与非空文件，覆盖 jsPDF 大版本兼容。地图未联网，PDF 排版尚未逐页视觉验收。后端未修改，保留最近 178 passed、2 skipped。

修改 frontend/package.json、package-lock.json、src/main.ts、src/views/Result.vue、e2e/trip.spec.ts 和文档。业务架构不变。

下一步继续补自由文本约束提取入口；官方证据、真实预约校验、持久 checkpoint 和远端 CI 仍未完成。
