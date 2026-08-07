# weread-auto-reader 交接

> 本文件是给 AI 的工作交接文档，请先阅读此文档再继续对本仓库进行操作。

## 一、还没做完的事 & 动手前注意

### 尚未完成 / 待办

- [ ] 确认 GitHub 仓库 Settings -> Secrets and variables -> Actions 已配置：secrets `WXREAD_CURL_BASH`（抓包 curl 全文）、`SERVERCHAN_SPT`（SendKey）；variables `READ_NUM`（可选）、`BOOK_ID`（可选）
- [ ] 部署后观察前几天风控：推送结果与 App 实际时长；若出现频繁掉 `synckey`、强制退登或时长封顶，调低 `READ_NUM`
- [ ] ServerChan SendKey 曾在对话记录中出现过，建议在 https://sct.ftqq.com 重置一次密钥
- [ ] 日志出现「章节列表接口未返回完整列表」属预期行为（`chapterInfos` 接口仅返回增量更新，无增量时自动用 `FALLBACK_CHAPTERS` 兜底）；若未来接口结构变化，按真实响应微调 `main.py` 的 `_extract_chapters` 解析器
- [ ] v2 未来若做真实阅读：需逆向推导 read 请求用的哈希 `chapterId`（阅读页只能拿到 `chapterUid`）；`chapterInfos` 接口带不带 `synckey` 都只返回增量（2026-08-07 实测确认），全量章节只能从阅读页内嵌数据解析

### 动手前注意事项

1. 严禁提交 `wxread_curl.txt`、`weread-*.json` 及任何真实 cookie / curl 原文，`.gitignore` 已忽略它们，不要移除这些规则
2. 不擅自 `git push`，推送前必须先询问用户确认
3. 凭证只通过环境变量（`WXREAD_CURL_BASH`、`SERVERCHAN_SPT`）或本地 `wxread_curl.txt` 传递，不得硬编码进代码、文档或提交记录
4. 日志 / 推送 / WebUI 中严禁出现环境变量原值、请求头、cookie 明文；所有新增日志输出必须经过 `log_utils.py` 的脱敏体系（`register_secret` / `sanitize` / `mask`，handler 层有兜底过滤）
5. 修改 `config.py` 时保留「建议保留区域」结构：`data` 模板字段是 2026-08-07 抓包验证过可成功计入的真实值，其中 `ts`/`rn`/`sg`/`ct`/`s` 会在运行时重新生成，不要改动其余字段的取值来源
6. 本地挂机进程由 `python localTest/run_local.py` 启动；停止用 Ctrl+C，或按命令行包含 `run_local` 定位 python 进程结束
7. 签名链逻辑（`KEY` 盐、`cal_hash`、`sg=SHA256({ts}{rn}{KEY})`）来自逆向，接口若升级失效需重新抓包分析，不要凭空修改

## 二、历史记录（我们做了什么、怎么做的）

- 2026-08-07（深夜）：新建 v2 榜单书库采集工程——`v2/collector.py`（榜单页 `__INITIAL_STATE__.categoryStoreModule.categoryBookList` 抓榜单、deepLink 的 `v=` 提取哈希 bookId、阅读页 `reader.chapterInfos` 抓全量章节）、`v2/library.py`（JSON 书库读写/增量去重/原子写）、`v2/pace.py`（60 秒/页、20 小时/天 ≈ 1200 页）、`v2/runner.py`（干跑模拟，不发 read 请求）；实测确认 `chapterInfos` 增量接口拿不到全量章节故弃用；rising/all 榜 + 10 本章节采集与干跑均测试通过，凭证无泄露、`v2/data/` 已被 git 忽略；README 增加 v2 小节
- 2026-08-07（晚）：启用本地推送并重启挂机——以环境变量注入 SendKey，`push.push()` 测试推送返回 True；README 加入 PacketMind 抓包推荐与本地挂机 + WebUI 小节
- 2026-08-07（晚）：新建本地测试体系——`localTest/run_local.py` 挂机脚本（每轮 400 次、轮间随机休息 5-10 分钟自动续轮）、`localTest/webui.py` 监控页（纯标准库，仅 127.0.0.1，端口从 3000 起随机探测）；`main.py` 新增 `RUNTIME_STATE` 运行状态供 WebUI 只读展示；`log_utils.py` 新增 `LOG_TAIL` 脱敏日志环形缓冲（`TailHandler`）
- 2026-08-07（下午）：从 PacketMind 抓包文件 `weread-2026-08-07.json` 定位 2 条 `web/book/read` 请求（均 `succ:1`），选取签名链完整的一条生成 `wxread_curl.txt`（6 个有效 headers + 26 项 cookie，剔除 x-wrpa-0/sentry 等噪声头），并用项目 `convert()` 实测解析通过；`config.py` 的 `data` 模板同步抓包真实值，验证过的章节加入 `FALLBACK_CHAPTERS` 首位；新建 `.gitignore` 保护敏感文件
- 2026-08-07（下午）：动态章节抓取——每次运行经 `chapterInfos` 接口防御式解析章节列表，失败自动回退兜底章节；默认书籍设为《三体全集》（`ce032b305a9bc1ce0b0dd2a`，可用 `BOOK_ID` 覆盖）；README 补充风控观察与平台上限两条提醒
- 2026-08-07：每日 20 小时方案——`READ_NUM` 默认 400，`.github/workflows/weread.yml` 改为 6 个 cron 窗口（UTC 0/4/8/12/16/20，即北京时间 08/12/16/20/24/04 点），`timeout-minutes: 350`，`concurrency` 排队不取消
- 2026-08-07：安全加固——`log_utils.py` 建立 `register_secret`/`sanitize`/`mask` 与 handler 兜底脱敏；`main.py` 改用 `requests.Session` 自动继承 Set-Cookie 实现凭证自我续期；推送异常日志脱敏（SendKey 在 URL 路径中）
- 2026-08-07：全量重写——`main.py` 函数化、`config.py` 仅保留 ServerChan 并容错解析 curl（兼容 `-H Cookie` 与 `-b` 两种写法并合并）、`push.py` 精简为仅 ServerChan（业务码 `code==0` 判成功、最多重试 3 次）、新建 `requirements.txt`（仅 requests）与 `.github/workflows/weread.yml`
- 2026-08-07：初始提交 `6de0b8a`（`git commit -m "init: weread auto reader"`），远端 `origin` 为 https://github.com/fun3588/weread-auto-reader.git

当前仓库状态：

```text
weread-auto-reader/
├── .github/workflows/weread.yml    # 6 窗口定时调度 + 手动触发
├── localTest/
│   ├── run_local.py                # 本地挂机脚本
│   └── webui.py                    # 本地监控页（127.0.0.1:3000 起）
├── v2/
│   ├── collector.py                # 榜单/图书/章节采集入口（只采集不发 read）
│   ├── library.py                  # 书库 JSON 读写与增量去重
│   ├── pace.py                     # 阅读节奏参数（60 秒/页、20 小时/天）
│   ├── runner.py                   # 干跑模拟（打印将读章节/URL，不发请求）
│   ├── README.md                   # v2 用法与数据结构说明
│   └── data/                       # 采集产物（git 忽略，不入库）
├── .gitignore                      # 忽略敏感文件与缓存
├── ai.md                           # 本交接文档
├── config.py                       # 配置与 curl 解析、凭证注册脱敏
├── log_utils.py                    # 日志与脱敏基础设施
├── main.py                         # 阅读主逻辑（签名、续期、熔断）
├── push.py                         # ServerChan 推送
├── README.md                       # 部署与使用说明
└── requirements.txt                # 仅 requests
```

本地存在但不在 git 中的敏感文件：`wxread_curl.txt`（真实 curl 凭证）、`weread-*.json`（抓包原始数据）；采集产物 `v2/data/` 同样不入库。

## 三、为什么做这件事

- 目标：自动刷微信读书阅读时长，用于阅读挑战赛保天数、保入场费，无需人工挂机翻页
- 价值：部署到 GitHub Actions 后每天 6 个窗口接力运行合计约 20 小时，Cookie 自动续期一次配置长期有效，结果经 ServerChan 推送到微信；本地也可挂机并带 WebUI 监控
- 复用方式：Fork 仓库后按 README 配置 secrets/variables 即可运行；本地使用参考 `localTest/`；核心的接口签名、Cookie 续期、日志脱敏方案可作为同类自动化脚本的参考实现
