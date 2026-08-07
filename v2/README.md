# v2 榜单书库采集

采集微信读书各榜单图书及其完整章节列表，沉淀为本地 JSON 书库，并提供按阅读节奏的干跑模拟。**本阶段只做数据采集与干跑，不发送任何 read 请求**（真实刷时长仍由根目录主工程 `main.py` 承担）。

## 用法

凭证与主工程一致：环境变量 `WXREAD_CURL_BASH` 优先，其次项目根目录 `wxread_curl.txt`。

```bash
# 采集榜单（默认 rising,all，每榜前 20 名）并抓取章节入库
python v2/collector.py --ranks rising,all --top 5 --chapters

# 干跑模拟：从书库随机挑一本书，打印将要阅读的章节与 URL（不发请求）
python v2/runner.py --minutes 1
python v2/runner.py --list                        # 查看书库
python v2/runner.py --book <bookId> --minutes 3   # 指定书目
```

`collector.py` 参数：

| 参数 | 说明 |
| --- | --- |
| `--ranks` | 榜单类型逗号分隔：`rising` 飙升 / `hot_search` 热搜 / `newbook` 新书 / `all` 总榜 / `newrating_publish` 新评分 / `general_novel_rising` 小说飙升 / `newrating_potential_publish` 潜力 |
| `--top` | 每榜前 N 名，默认 20（榜单页单页上限） |
| `--chapters` | 同时抓取章节列表入库（不带则只存榜单快照） |
| `--force` | 已入库的书也强制重新抓取 |

请求间随机延迟 2-5 秒，失败重试 3 次后跳过；日志全部走根目录 `log_utils.py` 脱敏体系。

## 数据来源（2026-08-07 实测确认）

- 榜单：`GET /web/category/{type}` 页面内嵌 `window.__INITIAL_STATE__.categoryStoreModule.categoryBookList`（含排名 `searchIdx`、书名/作者、推荐值指标）
- 章节：`GET /web/reader/{bookId}` 页面内嵌 `window.__INITIAL_STATE__.reader.chapterInfos`（完整章节列表）
- `POST /web/book/chapterInfos` 实测仅返回增量（`updated` 为空），无法拿全量章节，故不使用
- 榜单 `bookInfo.bookId` 是数字 id；阅读 URL 用的是 `deepLink` 中 `v=` 参数的哈希 id，书库以后者为主键（`numericBookId` 一并保存）

## 数据结构

```text
v2/data/                              # 已被 .gitignore 忽略
├── ranks_YYYY-MM-DD.json             # 榜单快照
└── books/{bookId}.json               # 单本书
```

榜单快照：`ranks.{榜单类型}[]`，每条含 `rank`（排名）、`bookId`、`numericBookId`、`title`、`author`、`recommend`（推荐值，字段来源记录在 `recommend_field`：热搜榜 `searchCount`、飙升榜 `riseCount`、其余多为 `readingCount`）、`cover`、`reader_url`。

单本书：`bookId`/`title`/`author`/`reader_url`/`collected_at`/`chapter_count`/`chapters[]`，章节条目为 `chapterUid`（章节标识）、`chapterIdx`（序号）、`title`、`wordCount`。

> 注：真实 read 请求使用的哈希 `chapterId` 与 `chapterUid` 不同，需要另行逆向推导，属未来真实阅读阶段的工作，本期不涉及。

## 阅读节奏（pace.py）

`PAGE_SECONDS=60`（每页约 60 秒）、`DAILY_HOURS=20`，推导每日约 **1200 页**。未来真实阅读时按此节奏构造 `rt≈60` 的请求。`runner.py` 干跑即按该节奏把时长折算为逐章推进（约 300 字/页估算章节页数），只打印计划、不发请求。
