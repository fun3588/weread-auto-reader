# config.py 自定义配置，包括阅读次数、推送token的填写
import os
import re
import json
import logging

from log_utils import register_secret

logger = logging.getLogger(__name__)

"""
可修改区域
默认使用环境变量中的值，本地部署时可直接修改下方默认值
"""


def _env_int(name, default):
    """读取整数型环境变量，非法时回退默认值"""
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是合法数字，使用默认值 %d", name, value, default)
        return default


# 单个运行窗口的阅读次数，每次约计入 30 秒。
# 默认 400 次 ≈ 3 小时 20 分钟；workflow 每天分 6 个窗口接力，合计约 20 小时
READ_NUM = _env_int("READ_NUM", 400)

# 默认阅读的书籍 bookId（《三体全集》，可通过环境变量 BOOK_ID 换成其它书自行测试）
DEFAULT_BOOK_ID = os.getenv("BOOK_ID") or "ce032b305a9bc1ce0b0dd2a"

# ServerChan 推送的 SendKey，获取地址：https://sct.ftqq.com/sendkey
SERVERCHAN_SPT = os.getenv("SERVERCHAN_SPT", "")


# 可选 HTTP 代理，例如 http://127.0.0.1:7890（GitHub Actions 中配置为 secret：HTTP_PROXY）
HTTP_PROXY = os.getenv("HTTP_PROXY", "")


# read 接口的 curl bash 命令（GitHub Actions 中配置为 secret）
# 支持两种格式：
#   1. 完整 curl：含 -H / -b / --data-raw 的 curl 命令（推荐，可自动提取 data）
#   2. 纯 Cookie：形如 "wr_skey=xxx; wr_vid=xxx; ..." 的 cookie 字符串
#      （此时 data 使用下方模板默认值，appId/ps/pc 需为有效值）
curl_str = os.getenv("WXREAD_CURL_BASH", "")

# 本地部署时的兜底 headers / cookies 占位，
# 也可直接在此粘贴抓包结果（不配置 WXREAD_CURL_BASH 时使用）
cookies = {
    "RK": "YOUR_RK",
    "ptcz": "YOUR_PTCZ",
    "pac_uid": "YOUR_PAC_UID",
    "iip": "0",
    "wr_skey": "YOUR_WR_SKEY",
    "wr_avatar": "",
    "wr_gender": "0",
}

headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://weread.qq.com",
    "referer": "https://weread.qq.com/web/reader/ce032b305a9bc1ce0b0dd2ak764323602597647966b7a1c",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
}


# 回退兜底章节（仅 chapterId）：运行时优先动态抓取章节列表，抓取失败时使用；
# 首项为 2026-08-07 抓包验证过可成功计入的章节
FALLBACK_CHAPTERS = [
    "764323602597647966b7a1c",
    "ecc32f3013eccbc87e4b62e", "a87322c014a87ff679a21ea", "e4d32d5015e4da3b7fbb1fa",
    "16732dc0161679091c5aeb1", "8f132430178f14e45fce0f7", "c9f326d018c9f0f895fb5e4",
    "45c322601945c48cce2e120", "d3d322001ad3d9446802347", "65132ca01b6512bd43d90e3",
    "c20321001cc20ad4d76f5ae", "c51323901dc51ce410c121b", "aab325601eaab3238922e53",
    "9bf32f301f9bf31c7ff0a60", "c7432af0210c74d97b01b1c", "70e32fb021170efdf2eca12",
    "6f4322302126f4922f45dec",
]

"""
建议保留区域 | 默认读三体，其它书籍自行测试时间是否增加
敏感字段（appId/ps/pc/sm 等）运行时从 WXREAD_CURL_BASH 的 --data-raw 解析，
仓库内仅保留占位符，避免真实会话/设备标识被公开。
"""
data = {
    "appId": "",
    "b": "ce032b305a9bc1ce0b0dd2a",
    "c": "764323602597647966b7a1c",
    "ci": 0,
    "co": 0,
    "sm": "",
    "pr": 0,
    "rt": 30,
    "ts": 0,
    "rn": 0,
    "sg": "",
    "ct": 0,
    "ps": "",
    "pc": "",
    "s": "",
}


def convert(curl_command):
    """提取 curl bash 命令中的 headers 与 cookies
    支持 -H 'Cookie: xxx' / -H "Cookie: xxx" 与 -b 'xxx' / -b "xxx" 两种 cookie 写法
    """
    # 提取 headers（兼容单双引号）
    headers_temp = {
        key: value
        for key, value in re.findall(r"-H\s+['\"]([^:]+):\s*([^'\"]+)['\"]", curl_command)
    }

    # 从 -H 'Cookie: xxx' 提取
    cookie_header = next(
        (value for key, value in headers_temp.items() if key.lower() == "cookie"), ""
    )
    # 从 -b 'xxx' 提取
    cookie_b = re.search(r"-b\s+['\"]([^'\"]+)['\"]", curl_command)
    cookie_b_str = cookie_b.group(1) if cookie_b else ""

    # 解析 cookie 字符串（两种来源合并，-b 优先）
    parsed_cookies = {}
    for cookie_string in (cookie_header, cookie_b_str):
        if not cookie_string:
            continue
        for item in cookie_string.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                parsed_cookies[key.strip()] = value.strip()

    # 移除 headers 中的 Cookie
    parsed_headers = {
        key: value for key, value in headers_temp.items() if key.lower() != "cookie"
    }
    return parsed_headers, parsed_cookies


def parse_data_from_curl(curl_command):
    """从 curl 的 --data-raw 中提取 data 字段（含 appId/ps/pc 等敏感值），
    仓库内 data 模板仅占位，真实值在此运行时解析注入。"""
    match = re.search(r"--data-raw\s+'([^']+)'", curl_command)
    if not match:
        match = re.search(r'--data-raw\s+"([^"]+)"', curl_command)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in data if key in payload}


def parse_cookie_str(cookie_str):
    """解析纯 cookie 字符串（"k1=v1; k2=v2"）为字典"""
    parsed = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def is_curl_command(text):
    """判断输入是否为 curl 命令格式（含 -H 或 curl 前缀）"""
    return bool(re.search(r"curl\s+'|-\s*H\s+['\"]|--data-raw", text))


if curl_str:
    if is_curl_command(curl_str):
        headers, cookies = convert(curl_str)
        data.update(parse_data_from_curl(curl_str))
    else:
        # 纯 cookie 字符串：data 用模板值，cookie 直接解析
        parsed = parse_cookie_str(curl_str)
        if parsed:
            cookies = parsed
            # 纯 cookie 模式缺少 appId/ps/pc 等字段，可通过 WXREAD_DATA_JSON 补充
            data_json = os.getenv("WXREAD_DATA_JSON", "")
            if data_json:
                try:
                    data.update({k: v for k, v in json.loads(data_json).items() if k in data})
                except (ValueError, TypeError):
                    logger.warning("WXREAD_DATA_JSON 不是合法 JSON，已忽略。")
            missing = [k for k in ("appId", "ps", "pc") if not data.get(k)]
            if missing:
                logger.warning(
                    "使用纯 Cookie 模式，data 缺失字段 %s（模板为占位符），"
                    "建议改用完整 curl 或设置 WXREAD_DATA_JSON。",
                    missing,
                )
    if not cookies or "wr_skey" not in cookies:
        raise ValueError(
            "WXREAD_CURL_BASH 解析失败或未包含 wr_skey，"
            "请确认抓包内容完整且来自 read 接口的『复制为 cURL (Bash)』"
            "或为包含 wr_skey 的 Cookie 字符串。"
        )
elif cookies.get("wr_skey", "").startswith("YOUR_"):
    logger.warning("未配置 WXREAD_CURL_BASH 且 config.py 中仍是占位 cookies，请完成配置后再运行。")

# 将所有敏感凭证注册到日志脱敏器：
# 后续任何日志（含异常堆栈）中出现这些值都会被替换为 ***
register_secret(SERVERCHAN_SPT)
register_secret(curl_str)
for _value in cookies.values():
    register_secret(_value)
