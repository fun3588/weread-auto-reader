# weread-auto-reader 交接

> 本文件是给 AI 的工作交接文档，请先阅读此文档再继续对本仓库进行操作。

## 一、还没做完的事 & 动手前注意

### 尚未完成 / 待办

- [ ] **隐私清理（重要）**：`v2/reader.py` 第 59-60 行硬编码了真实抓包值 `PS = "fc732b007aa56428g01604c"`、`PC = "7a432b507aa56430g01640c"`，这是用户会话/设备标识，公开仓库不应提交。改为从 `config.data` 读取（main.py 已从 curl 运行时注入），或运行时用 `build_data` 生成，删除硬编码
- [ ] 确认 GitHub 仓库 Settings -> Secrets and variables -> Actions 已配置：secrets `WXREAD_CURL_BASH`（主账号 curl 全文）、`WXREAD_CURL_BASH_BACKUP`（可选，备用账号）、`HTTP_PROXY`（可选，防 IP 风控）、`HTTP_PROXY_BACKUP`（可选，备用账号独立代理）、`SERVERCHAN_SPT`（SendKey）；variables `READ_NUM`（可选，默认 55）、`BOOK_ID`（可选，默认三体）
- [ ] 部署后观察前几天风控：推送结果与 App 实际时长；若出现频繁掉 `synckey`、强制退登或时长封顶，调低 `READ_NUM`
- [ ] ServerChan SendKey 曾在对话记录中出现过，建议在 https://sct.ftqq.com 重置一次密钥
- [ ] 私有仓库额度警告：每小时定时 + 双账号并行消耗 Actions 分钟数巨大（双账号 ≈ 1440 分钟/天），私有仓库免费额度仅 2000 分钟/月，会扣费/停跑；如需长期稳定运行请转 public
- [ ] `v2/reader.py`（真实阅读刷榜）尚未在本仓库 CI 中接入，仅本地可用；如需接入需评估其与 `main.py` 的关系

### 动手前注意事项

1. 严禁提交 `wxread_curl.txt`、`weread-*.json` 及任何真实 cookie / curl 原文，`.gitignore` 已忽略它们（`wxread_curl.txt`、`weread-*.json`、`v2/data/`、`localTest/_*`、`.qoder/`），不要移除这些规则
2. 不擅自 `git push`，推送前必须先询问用户确认
3. 凭证只通过环境变量（`WXREAD_CURL_BASH`、`SERVERCHAN_SPT`）或本地 `wxread_curl.txt` 传递，不得硬编码进代码、文档或提交记录。**注意检查 `v2/`、`localTest/` 下的脚本是否有硬编码的 ps/pc/curl 片段**
4. 日志 / 推送 / WebUI 中严禁出现环境变量原值、请求头、cookie 明文；所有新增日志输出必须经过 `log_utils.py` 的脱敏体系（`register_secret` / `sanitize` / `mask`，handler 层有兜底过滤）
5. `config.py` 的 `data` 模板已改为**占位符**，敏感字段（`appId`/`ps`/`pc`/`sm` 等）在运行时由 `parse_data_from_curl()` 从 `WXREAD_CURL_BASH` 的 `--data-raw` 解析注入。**不要**把真实抓包值直接写回模板
6. 签名链逻辑（`KEY` 盐、`cal_hash`、`sg=SHA256({ts}{rn}{KEY})`）来自逆向，接口若升级失效需重新抓包分析，不要凭空修改
7. `chapterInfos` 接口仅返回增量更新，无增量时日志出现「无增量数据」并自动用 `FALLBACK_CHAPTERS` 兜底，属预期行为；若接口结构变化，按真实响应微调 `_extract_chapters` 解析器
8. 本地挂机进程由 `python localTest/run_local.py` 启动；停止用 Ctrl+C，或按命令行包含 `run_local` 定位 python 进程结束
9. `main.py` 顶部会自动加载项目根目录 `wxread_curl.txt` 作为凭证（环境变量 `WXREAD_CURL_BASH` 优先），因此本地直接 `python main.py` 即可跑，无需手动设环境变量

## 二、历史记录（我们做了什么、怎么做的）

- 2026-08-08：**多账号并行**——`push.py` 读取 `ACCOUNT_ID` 环境变量在推送标题加账号名（如 `微信读书自动阅读(主账号)-成功`）；`.github/workflows/weread.yml` 改为 bash 脚本内 `run_account()` 并行启动主/备账号进程，配置了 `WXREAD_CURL_BASH_BACKUP` 则两账号并行、否则仅主账号单线程，任一失败退出非 0；README 增加多账号 secret 表格（`WXREAD_CURL_BASH_BACKUP`、`HTTP_PROXY_BACKUP`）。commit `dbb31b4`
- 2026-08-08：**v2 真实阅读与 id 逆向**——新增 `v2/idgen.py`（逆向 web 前端模块156 的 chapterId 哈希算法 `e()`：md5 + 编码分段 + 校验位，已用三体 `e(89) == '764323602597647966b7a1c'` 验证）与 `v2/reader.py`（从书库按榜单图书发真实 read 请求刷榜，复用根目录凭证/脱敏体系，支持 `--dry-run`/`--minutes`/`--ranks`/`--book`）。commit `ee4f4c4`
- 2026-08-08：**代码精简与隐私加固**——`main.py` 移除全部诊断日志（`get_public_ip`、renewal/read 详细响应、会话 Cookie 列表等）、`co` 页码随机化（`CO_RANGE=(300,700)`）、`data` 模板敏感字段改占位符并新增 `parse_data_from_curl()` 运行时注入；workflow 关闭 `LOG_LEVEL=DEBUG`；`.gitignore` 补全 `localTest/_*`、`.qoder/`、`test_parse*.py`。commit `4c32030`
- 2026-08-08：**修复 GitHub 上 read 返回 `{}` 的根因**——`BOOK_ID: ${{ vars.BOOK_ID }}` 在未配置变量时注入空字符串，覆盖 `os.getenv("BOOK_ID", 默认值)` 导致 `data['b']` 为空、read 静默返回 `{}`。修复为 `os.getenv("BOOK_ID") or "ce032b..."`（空串兜底）+ workflow `vars.BOOK_ID || 'ce032b...'`。commit `cce9ca7`
- 2026-08-08：**删除 git 历史、重新初始化**——`Remove-Item .git` + `git init` + `git add -A` + `git commit "init: 微信读书自动阅读脚本"` + `git push -f`，本地与远程均只剩 1 个 commit `7c3e530`（原 8 个 commit 历史已清空）
- 2026-08-08（诊断）：排查 GitHub 上「连续失败」——加详细日志（renewal/read 完整响应体、密钥前后对比、会话 Cookie 概况），定位到 `b` 字段为空（见上条修复）
- 2026-08-08：headers 对齐真实浏览器请求——`config.py` 的 `headers` 补全 `content-type`/`origin`/`referer` 并 UA 对齐抓包 Chrome/150
- 2026-08-07（深夜）：新建 v2 榜单书库采集工程——`v2/collector.py`（榜单页 `__INITIAL_STATE__.categoryStoreModule.categoryBookList` 抓榜单、deepLink 的 `v=` 提取哈希 bookId、阅读页 `reader.chapterInfos` 抓全量章节）、`v2/library.py`（JSON 书库读写/增量去重/原子写）、`v2/pace.py`（60 秒/页、20 小时/天 ≈ 1200 页）、`v2/runner.py`（干跑模拟，不发 read 请求）；实测确认 `chapterInfos` 增量接口拿不到全量章节故弃用；`v2/data/` 已被 git 忽略
- 2026-08-07（晚）：启用本地推送并重启挂机——环境变量注入 SendKey；新建 `localTest/run_local.py`（每轮 400 次、轮间随机休息 5-10 分钟自动续轮）、`localTest/webui.py`（纯标准库 WebUI，仅 127.0.0.1，端口 3000 起探测）；`main.py` 新增 `RUNTIME_STATE` 供 WebUI 只读展示；`log_utils.py` 新增 `LOG_TAIL` 脱敏日志环形缓冲（`TailHandler`）
- 2026-08-07（下午）：从 PacketMind 抓包文件 `weread-2026-08-07.json` 定位 `web/book/read` 请求并生成 `wxread_curl.txt`；`config.py` 的 `data` 模板同步抓包真实值；动态章节抓取 + 兜底章节；README 补充风控观察与平台上限提醒

当前仓库状态（仅列 git 内文件）：

```text
weread-auto-reader/
├── .github/workflows/weread.yml    # 每小时定时 + 手动触发，主/备账号并行
├── localTest/
│   ├── run_local.py                # 本地挂机脚本（每轮 400 次，自动续轮）
│   └── webui.py                    # 本地监控页（127.0.0.1:3000 起）
├── v2/
│   ├── collector.py                # 榜单/图书/章节采集入口
│   ├── idgen.py                    # chapterId 哈希算法（逆向模块156）
│   ├── library.py                  # 书库 JSON 读写与增量去重
│   ├── pace.py                     # 阅读节奏参数（60 秒/页、20 小时/天）
│   ├── reader.py                   # 真实阅读刷榜（发 read 请求，⚠️含硬编码 ps/pc）
│   ├── runner.py                   # 干跑模拟（打印将读章节/URL，不发请求）
│   ├── README.md                   # v2 用法与数据结构说明
│   └── data/                       # 采集产物（git 忽略，不入库）
├── .gitignore                      # 忽略敏感文件与缓存
├── ai.md                           # 本交接文档
├── config.py                       # 配置与 curl 解析、data 运行时注入、凭证脱敏
├── log_utils.py                    # 日志与脱敏基础设施
├── main.py                         # 阅读主逻辑（签名、续期、熔断、co 随机）
├── push.py                         # ServerChan 推送（支持 ACCOUNT_ID 标题）
├── README.md                       # 部署与使用说明
└── requirements.txt                # 仅 requests
```

本地存在但不在 git 中的敏感文件：`wxread_curl.txt`（真实 curl 凭证）、`weread-2026-08-07.json`（抓包原始数据）；采集产物 `v2/data/`、本地探针 `localTest/_*` 均不入库。

## 三、为什么做这件事

- 目标：自动刷微信读书阅读时长，用于阅读挑战赛保天数、保入场费，无需人工挂机翻页；支持多账号并行批量刷
- 价值：部署到 GitHub Actions 后每小时自动运行（每次约 30 分钟），Cookie 自动续期一次配置长期有效，结果经 ServerChan 推送到微信；支持主/备两账号并行且推送标题区分账号；本地可挂机并带 WebUI 监控
- 复用方式：Fork 仓库后按 README 配置 secrets/variables 即可运行；多账号只需追加 `WXREAD_CURL_BASH_BACKUP` secret；核心的接口签名、Cookie 续期、`chapterId` 逆向算法、日志脱敏方案可作为同类自动化脚本的参考实现
