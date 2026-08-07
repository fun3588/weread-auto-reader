# 微信读书自动阅读

通过对微信读书官网接口的抓包和 JS 逆向分析，实现自动刷阅读时长，用于阅读挑战赛保天数、保入场费。

## 功能特性

- **阅读时长调节**：默认计入排行榜和挑战赛，默认每天约 20 小时（6 个定时窗口接力，单窗口次数可配置）。
- **定时运行推送**：部署在 GitHub Action 后每天定时运行，结果通过 ServerChan 推送到微信。
- **Cookie 自动更新**：脚本自动刷新 `wr_skey`，一次部署长期有效。
- **稳定健壮**：请求带超时、失败重试有上限、随机间隔模拟真人节奏。

***

## 部署步骤（GitHub Action）

### 1. 抓包准备

推荐使用 [PacketMind](https://github.com/yumeizh/PacketMind) 进行抓包，导出后可直接定位 `read` 接口请求。

在微信读书官网 [weread.qq.com](https://weread.qq.com/) 搜索【三体】，点开阅读并翻页，抓包找到 `read` 接口（`https://weread.qq.com/web/book/read`）。返回格式正常（如 `{"succ": 1, "synckey": 564589834}`）时，右键该请求选择 **复制为 cURL (Bash)**。

### 2. 配置 Secrets 与 Variables

Fork 本仓库后，进入 **Settings** -> **Secrets and variables** -> **Actions**：

**Repository secrets** 中添加：

| key | 说明 |
| --- | --- |
| `WXREAD_CURL_BASH` | **必填**，上一步抓包复制的 curl bash 命令全文 |
| `WXREAD_CURL_BASH_BACKUP` | **可选**，第二个账号的 curl bash 命令全文。配置后主/备两账号**并行刷**；不配置则仅跑主账号（单线程） |
| `SERVERCHAN_SPT` | **必填**，ServerChan 的 SendKey，[获取地址](https://sct.ftqq.com/sendkey) |
| `HTTP_PROXY` | **可选**，主账号 HTTP 代理地址（如 `http://ip:port`）。当运行环境 IP 被微信读书风控（常见于 GitHub Action 节点）导致阅读失败时，可设置该值让请求走代理；留空则直连 |
| `HTTP_PROXY_BACKUP` | **可选**，备用账号的 HTTP 代理地址。建议两账号用不同代理，避免同一出口 IP 并行被判定关联账号 |

**Variables** 中添加：

| key | 说明 |
| --- | --- |
| `READ_NUM` | 可选，单个窗口的阅读次数（每次约 30 秒），默认 55 次 ≈ 30 分钟 |
| `BOOK_ID` | 可选，阅读的书籍 ID，默认《三体全集》（`ce032b305a9bc1ce0b0dd2a`），换其它书需自行测试时长是否计入 |

### 3. 运行

- 定时运行：workflow **每小时整点**运行一次，每次约 30 分钟（55 次），全天 24 小时接力（见 `.github/workflows/weread.yml`，可自行修改 cron）。
- 手动运行：进入 **Actions** -> **微信读书自动阅读** -> **Run workflow**。

运行结束后，成功/失败结果会通过 ServerChan 推送到你的微信。

***

## 本地运行

### 本地挂机 + WebUI 监控（推荐）

```bash
pip install -r requirements.txt
python localTest/run_local.py
```

- 凭证自动读取项目根目录的 `wxread_curl.txt`（抓包复制的 curl bash 命令全文，已被 git 忽略），也可用环境变量 `WXREAD_CURL_BASH` 覆盖
- 每轮阅读 400 次（约 3 小时 20 分钟），轮间随机休息 5-10 分钟后自动续下一轮，Ctrl+C 停止
- 启动后自动开启 WebUI 监控：`http://127.0.0.1:3000`（端口从 3000 起探测，仅本机可访问），实时展示进度、成功/失败数、计入时长与脱敏日志
- 设置环境变量 `SERVERCHAN_SPT` 即启用推送；推送内容仅为固定文案（完成/失败通知），凭证不会进入任何推送消息与 WebUI 页面

### 单次运行

```bash
pip install -r requirements.txt

# 配置环境变量（或直接修改 config.py）
set WXREAD_CURL_BASH=<抓包的curl命令>
set SERVERCHAN_SPT=<你的SendKey>
set READ_NUM=400

python main.py
```

***

## v2 榜单书库

`v2/` 目录提供榜单图书与章节的采集沉淀，以及按阅读节奏的干跑模拟，**只采集不发 read 请求**（真实刷时长仍由主工程承担）。凭证与主工程共用（`WXREAD_CURL_BASH` 或 `wxread_curl.txt`）。

```bash
# 采集榜单并抓取章节入库（默认每榜前 20 名，产物在 v2/data/，已被 git 忽略）
python v2/collector.py --ranks rising,all --chapters

# 干跑模拟：随机挑书打印将要阅读的章节与 URL，不产生任何请求
python v2/runner.py --minutes 1
```

数据结构与更多参数见 [v2/README.md](v2/README.md)。

***

## 常见问题

1. **阅读时间没有增加**：默认书籍为《三体全集》（`ce032b305a9bc1ce0b0dd2a`），章节列表每次运行时通过接口动态抓取；若抓取失败会自动回退到内置兜底章节。换其它书籍可通过 `BOOK_ID` 环境变量配置，需自行测试时长是否计入。
2. **提示「无法获取新密钥」**：`WXREAD_CURL_BASH` 内容失效或不完整，重新抓包替换即可。
3. **连续失败终止**：脚本连续失败 5 次会自动停止并推送失败通知，避免空转。
4. **风控观察**：当前默认 2400 次/天，是早期版本的约 60 倍请求量。部署后前几天请观察推送结果与 App 内实际时长；若出现频繁掉 `synckey`、强制退登等风控迹象，请调低 `READ_NUM`。
5. **平台计入上限**：微信读书对单日计入时长可能有封顶。若发现时长稳定卡在某值不再增长，说明已达平台上限，按实际上限调低 `READ_NUM` 即可，避免浪费 Actions 额度。

***

## 字段解释

| 字段 | 示例值 | 解释 |
| --- | --- | --- |
| `appId` | `"wbxxxxxxxxxxxxxxxxxxxxxxxx"` | 应用的唯一标识符 |
| `b` | `"ce032b305a9bc1ce0b0dd2a"` | 书籍的唯一标识符 |
| `c` | `"0723244023c072b030ba601"` | 章节的唯一标识符 |
| `ci` | `60` | 章节索引 |
| `co` | `336` | 内容的具体位置或页码 |
| `sm` | `"[插图]威慑纪元61年，执剑人在一棵巨树"` | 当前阅读的内容摘要 |
| `pr` | `65` | 页码或段落索引 |
| `rt` | `88` | 本次阅读时长（秒） |
| `ts` | `1727580815581` | 请求时间戳（毫秒级） |
| `rn` | `114` | 随机数 |
| `sg` | `"bfdf7de2..."` | 安全签名（SHA256） |
| `ct` | `1727580815` | 请求时间戳（秒级） |
| `ps` | `"xxxxxxxxxxxxxxxxxxxxxxxx"` | 用户会话标识 |
| `pc` | `"xxxxxxxxxxxxxxxxxxxxxxxx"` | 设备标识 |
| `s` | `"fadcb9de"` | 请求数据校验和 |
