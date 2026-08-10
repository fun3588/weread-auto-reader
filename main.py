# main.py 主逻辑：包括字段拼接、模拟请求
import os
import json
import sys
import time
import random
import logging
import hashlib
import urllib.parse

# 凭证加载：与 collector.py 一致，环境变量 > 项目根目录 wxread_curl.txt
# 必须在导入 config 之前完成，否则 config 会落到占位 cookies
if not os.getenv("WXREAD_CURL_BASH"):
    _curl_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wxread_curl.txt")
    if os.path.exists(_curl_file):
        with open(_curl_file, encoding="utf-8") as f:
            os.environ["WXREAD_CURL_BASH"] = f.read().strip()

import requests

from push import push
from log_utils import setup_logging, sanitize, mask
from config import (
    data,
    headers,
    cookies,
    READ_NUM,
    DEFAULT_BOOK_ID,
    FALLBACK_CHAPTERS,
    HTTP_PROXY,
)

import sys as _sys
_v2_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v2")
if _v2_dir not in _sys.path:
    _sys.path.insert(0, _v2_dir)
import idgen

# 加密盐及其它默认值
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
READER_URL = "https://weread.qq.com/web/reader"
COOKIE_DATA_VARIANTS = [
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": True},
    {"rq": "%2Fweb%2Fbook%2Fread"},
]

REQUEST_TIMEOUT = 30   # 单次请求超时（秒），GitHub 网络较慢时留足余量
MAX_FAIL_COUNT = 5     # 连续失败上限，超过则终止
SLEEP_RANGE = (30, 35)  # 每次成功阅读后的随机等待区间（秒），保持 30 秒起的真人节奏
CO_RANGE = (300, 700)   # 阅读页码随机范围，模拟真人翻页
SESSION_REFRESH_EVERY = 6  # 每成功 N 次重新获取阅读页会话（psvts 有效期约几分钟）

# 代理不可达时置为 True，后续所有请求自动改直连
_PROXY_FAILED = False

# 运行状态（供本地 WebUI 只读展示，严禁放入凭证类字段）
RUNTIME_STATE = {
    "round": 0,             # 挂机轮次（由本地挂机脚本写入）
    "status": "idle",       # idle/reading/done/error
    "read_num": READ_NUM,   # 本轮目标次数
    "index": 0,             # 当前进度
    "success_count": 0,     # 累计成功次数
    "fail_count": 0,        # 当前连续失败次数
    "last_result": "",      # 最近一次请求结果描述
    "cookie_refreshed_at": "",
    "started_at": "",
    "finished_at": "",
}


def _now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def encode_data(payload):
    """数据编码"""
    return '&'.join(
        f"{k}={urllib.parse.quote(str(payload[k]), safe='')}" for k in sorted(payload.keys())
    )


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()


def create_session():
    """创建带鉴权信息的会话，后续响应的 Set-Cookie 会自动更新会话凭证"""
    global _PROXY_FAILED
    session = requests.Session()
    # 关闭环境代理自动接管，仅使用显式配置的 HTTP_PROXY，避免 GitHub 内部代理干扰
    session.trust_env = False
    session.headers.update(headers)
    session.cookies.update(cookies)
    # 代理先前不可达则直接直连
    if HTTP_PROXY and not _PROXY_FAILED:
        proxy = HTTP_PROXY.strip()
        # 代理值含空格/控制字符时视为无效，回退直连
        if " " in proxy or "\n" in proxy or "\r" in proxy:
            logging.warning("HTTP_PROXY 含非法字符（空格/换行），已忽略并改用直连。")
            proxy = ""
        if proxy and not proxy.startswith(("http://", "https://", "socks")):
            logging.warning("HTTP_PROXY 格式无效：%s，已忽略并改用直连。", proxy)
            proxy = ""
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
    return session


def get_wr_skey(session):
    """刷新 cookie 密钥，成功返回新的 wr_skey，否则返回 None。
    _session_request 已内置代理不可达时自动直连回退。"""
    for cookie_data in COOKIE_DATA_VARIANTS:
        try:
            response = _session_request(
                session, "POST", RENEW_URL,
                data=json.dumps(cookie_data, separators=(',', ':')),
                timeout=REQUEST_TIMEOUT,
            )
            if 'wr_skey' in response.cookies:
                # 先清除旧 wr_skey，避免 session 中多值冲突导致发送时用错 key
                for c in list(session.cookies):
                    if c.name == 'wr_skey':
                        session.cookies.clear(c.domain, c.path, c.name)
                session.cookies.update(response.cookies)
                return response.cookies['wr_skey']
        except requests.RequestException as exc:
            logging.warning("refresh_cookie 请求失败，原因：%s", sanitize(exc))
    return None


def refresh_cookie(session):
    """刷新 cookie，失败时推送失败消息并终止运行"""
    logging.info("刷新 cookie")
    new_skey = get_wr_skey(session)
    if new_skey:
        cookies['wr_skey'] = new_skey
        RUNTIME_STATE["cookie_refreshed_at"] = _now_str()
        logging.info("密钥刷新成功，新密钥：%s", mask(new_skey))
    else:
        error_msg = "无法获取新密钥或者 WXREAD_CURL_BASH 配置有误，终止运行。"
        RUNTIME_STATE["status"] = "error"
        RUNTIME_STATE["last_result"] = error_msg
        logging.error(error_msg)
        push(error_msg, is_success=False)
        raise SystemExit(error_msg)


def _session_request(session, method, url, **kwargs):
    """带代理回退的请求：代理不可达时自动改直连重试一次。
    返回响应对象；代理整体不可用时置 _PROXY_FAILED 并直连。"""
    global _PROXY_FAILED
    if _PROXY_FAILED and session.proxies:
        # 已知代理不可达，直接清空改直连
        session.proxies = {}
    try:
        return session.request(method, url, **kwargs)
    except requests.RequestException:
        if session.proxies and not _PROXY_FAILED:
            _PROXY_FAILED = True
            logging.warning("代理不可达，后续自动改用直连。")
            saved = session.proxies
            session.proxies = {}
            try:
                return session.request(method, url, **kwargs)
            except requests.RequestException:
                pass
            finally:
                session.proxies = saved
        raise


def fix_no_synckey(session):
    """响应缺失 synckey 时，通过 chapterInfos 接口尝试修复"""
    try:
        response = _session_request(
            session, "POST", "https://weread.qq.com/web/book/chapterInfos",
            data=json.dumps({"bookIds": [DEFAULT_BOOK_ID]}, separators=(',', ':')),
            timeout=REQUEST_TIMEOUT,
        )
        logging.info("synckey 修复请求返回：%s", response.status_code)
    except requests.RequestException as exc:
        logging.warning("synckey 修复请求失败：%s", sanitize(exc))


def _extract_chapters(node):
    """防御式解析：递归查找含 chapterId 的 dict 列表，提取章节信息"""
    results = []
    if isinstance(node, dict):
        for value in node.values():
            results.extend(_extract_chapters(value))
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and (
                "chapterId" in item or "chapter_id" in item or "cid" in item
            ):
                chapter_id = item.get("chapterId") or item.get("chapter_id") or item.get("cid")
                if not chapter_id:
                    continue
                results.append({
                    "chapterId": chapter_id,
                    "chapterIndex": item.get("chapterIndex", item.get("index")),
                    "title": item.get("title", ""),
                })
            else:
                results.extend(_extract_chapters(item))
    return results


def extract_state(html):
    """平衡括号提取 window.__INITIAL_STATE__ 后的 JSON 对象。解析失败返回 None。"""
    idx = html.find("window.__INITIAL_STATE__")
    if idx < 0:
        return None
    start = html.find("{", html.find("=", idx))
    if start < 0:
        return None
    depth, i, in_str, esc = 0, start, False, False
    length = len(html)
    while i < length:
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i + 1])
                    except ValueError:
                        return None
        i += 1
    return None


def fetch_reader_session(session, url_book_id):
    """抓取阅读页，获取数字 bookId / psvts / token 与完整章节列表。
    返回 (book_id_num, psvts, token, chapters)，失败返回 None。
    chapters: 每项含 chapterUid/chapterIdx/title，用于构造 c/ci/sm 完全匹配的请求。"""
    try:
        response = _session_request(
            session, "GET", f"{READER_URL}/{url_book_id}", timeout=REQUEST_TIMEOUT
        )
        state = extract_state(response.text)
    except requests.RequestException as exc:
        logging.warning("阅读页 %s 请求失败：%s", url_book_id, sanitize(exc))
        return None
    if not state:
        logging.warning("阅读页 %s 未提取到内嵌数据。", url_book_id)
        return None
    reader = state.get("reader", {})
    book_id_num = reader.get("bookId")
    psvts = reader.get("psvts")
    token = reader.get("token", "")
    if not book_id_num or not psvts:
        logging.warning("阅读页 %s 缺少 bookId/psvts。", url_book_id)
        return None
    chapters = []
    for ch in (reader.get("chapterInfos") or []):
        uid = ch.get("chapterUid")
        if uid is None:
            continue
        chapters.append({
            "chapterUid": uid,
            "chapterIdx": ch.get("chapterIdx", ch.get("index", 0)),
            "title": ch.get("title", ""),
        })
    if not chapters:
        logging.warning("阅读页 %s 未提取到章节列表，使用回退章节。", url_book_id)
    else:
        logging.info("阅读页章节列表 %d 章。", len(chapters))
    return str(book_id_num), psvts, token, chapters


def fetch_chapters(session, book_id):
    """每次运行抓取一次书籍的真实章节列表，失败或解析为空时返回 None"""
    try:
        response = _session_request(
            session, "POST", "https://weread.qq.com/web/book/chapterInfos",
            data=json.dumps({"bookIds": [book_id]}, separators=(',', ':')),
            timeout=REQUEST_TIMEOUT,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logging.warning("章节列表抓取失败：%s", sanitize(exc))
        return None

    chapters = _extract_chapters(payload)
    if not chapters:
        logging.info("章节列表接口无增量数据（HTTP %s），使用回退章节。", response.status_code)
        return None
    logging.info("章节列表抓取成功（HTTP %s），共 %d 章。", response.status_code, len(chapters))
    return chapters


def build_data(last_time, chapters, session_info):
    """构造一次阅读请求的 data 字段（动态会话签名）。
    session_info: (book_id_num, psvts, token, chapters)，来自阅读页动态获取。"""
    book_id_num, psvts, token, _ = session_info
    this_time = int(time.time())
    data["b"] = idgen.e(book_id_num)
    picked = random.choice(chapters)
    if isinstance(picked, dict):
        if picked.get("chapterUid") is not None:
            data["c"] = idgen.e(picked["chapterUid"])
        else:
            data["c"] = picked["chapterId"]
        if picked.get("chapterIdx") is not None:
            data["ci"] = picked["chapterIdx"]
        elif picked.get("chapterIndex") is not None:
            data["ci"] = picked["chapterIndex"]
        if picked.get("title"):
            data["sm"] = picked["title"]
    else:
        # 回退列表仅含 chapterId，ci 保持模板默认（可能不匹配，慎用）
        data["c"] = picked
    data["co"] = random.randint(*CO_RANGE)
    data["ct"] = this_time
    data["rt"] = this_time - last_time
    data["ts"] = int(this_time * 1000) + random.randint(0, 1000)
    data["rn"] = random.randint(0, 1000)
    data["ps"] = psvts
    data["pc"] = idgen.e(str(int(time.time())))
    data["sg"] = hashlib.sha256(f"{data['ts']}{data['rn']}{token}".encode()).hexdigest()
    # 先移除旧 s，避免上一轮残留值污染本次签名
    data.pop("s", None)
    data["s"] = cal_hash(encode_data(data))
    return this_time


def send_read_request(session):
    """发送一次阅读请求，返回解析后的响应 dict，网络/解析异常返回 None"""
    try:
        response = _session_request(
            session, "POST", READ_URL,
            data=json.dumps(data, separators=(',', ':')),
            timeout=REQUEST_TIMEOUT,
        )
        res_data = response.json()
        if not res_data or not res_data.get('succ'):
            logging.warning("read 响应异常：HTTP %s，body=%s", response.status_code, sanitize(res_data))
        return res_data
    except (requests.RequestException, ValueError) as exc:
        logging.warning("阅读请求失败：%s", sanitize(exc))
        return None


def main():
    refresh_print = setup_logging()

    session = create_session()
    refresh_cookie(session)

    # 每次运行从阅读页获取动态会话（psvts/token）与完整章节列表
    session_info = fetch_reader_session(session, DEFAULT_BOOK_ID)
    if not session_info:
        logging.error("无法获取阅读页会话，终止运行。")
        sys.exit(1)
    book_id_num, psvts, token, reader_chapters = session_info
    # 优先用阅读页章节（c/ci/sm 完全匹配），否则动态抓取，最后回退
    chapters = reader_chapters or (fetch_chapters(session, DEFAULT_BOOK_ID) or FALLBACK_CHAPTERS)

    index = 1
    fail_count = 0
    last_time = int(time.time()) - 30
    RUNTIME_STATE.update({
        "status": "reading",
        "read_num": READ_NUM,
        "index": 1,
        "success_count": 0,
        "fail_count": 0,
        "last_result": "",
        "started_at": _now_str(),
        "finished_at": "",
    })
    logging.info("一共需要阅读 %d 次。", READ_NUM)

    while index <= READ_NUM:
        # 定期重新获取阅读页会话，避免 psvts 过期导致签名失败
        if index > 1 and (index - 1) % SESSION_REFRESH_EVERY == 0:
            refreshed = fetch_reader_session(session, DEFAULT_BOOK_ID)
            if refreshed:
                session_info = refreshed
                logging.info("已刷新阅读页会话（第 %d 次）。", index)
            else:
                logging.warning("刷新阅读页会话失败，继续用旧会话。")

        this_time = build_data(last_time, chapters, session_info)

        refresh_print(f"阅读进度: 第 {index}/{READ_NUM} 次，已完成 {(index - 1) * 0.5:.1f} 分钟")
        res_data = send_read_request(session)

        if res_data is None:
            # 网络异常或非 JSON 响应，计入失败次数
            fail_count += 1
            RUNTIME_STATE["last_result"] = "请求失败（网络/解析异常）"
        elif res_data.get('succ'):
            if 'synckey' in res_data:
                fail_count = 0
                last_time = this_time
                index += 1
                RUNTIME_STATE["success_count"] += 1
                RUNTIME_STATE["last_result"] = "成功，synckey 已返回"
                time.sleep(random.randint(*SLEEP_RANGE))
                refresh_print(
                    f"阅读进度: 第 {min(index, READ_NUM + 1) - 1}/{READ_NUM} 次，"
                    f"已完成 {(index - 1) * 0.5:.1f} 分钟"
                )
                continue
            logging.warning("无 synckey，尝试修复...")
            fix_no_synckey(session)
            fail_count += 1
            RUNTIME_STATE["last_result"] = "无 synckey，已尝试修复"
        else:
            logging.warning("read 返回失败，尝试刷新会话与 cookie...")
            # psvts/token 过期是主要失败原因，先重新获取阅读页会话
            refreshed = fetch_reader_session(session, DEFAULT_BOOK_ID)
            if refreshed:
                session_info = refreshed
                logging.info("阅读页会话已刷新。")
            refresh_cookie(session)
            fail_count += 1
            RUNTIME_STATE["last_result"] = "会话过期，已刷新重试"

        RUNTIME_STATE["index"] = index
        RUNTIME_STATE["fail_count"] = fail_count

        if fail_count >= MAX_FAIL_COUNT:
            error_msg = f"连续失败 {fail_count} 次，终止运行。"
            RUNTIME_STATE["status"] = "error"
            RUNTIME_STATE["last_result"] = error_msg
            logging.error(error_msg)
            push(error_msg, is_success=False)
            sys.exit(1)
        time.sleep(random.randint(5, 10))

    RUNTIME_STATE["status"] = "done"
    RUNTIME_STATE["finished_at"] = _now_str()
    logging.info("阅读脚本已完成。")
    push(f"微信读书自动阅读完成。\n阅读时长：{READ_NUM * 0.5:.1f} 分钟。", is_success=True)


if __name__ == "__main__":
    main()
