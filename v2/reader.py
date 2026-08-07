# reader.py 真实阅读刷榜：从书库中按榜单图书逐章发送 read 请求，走代理
#
# 与干跑 runner.py 不同，本脚本发送真实的 /web/book/read 请求（计入阅读时长）。
# 依赖破解的 chapterId 算法（idgen.e(chapterUid)），鉴权复用根目录凭证。
#
# 用法：
#   python v2/reader.py --minutes 5                  # 从书库随机挑书刷 5 分钟
#   python v2/reader.py --book <bookId> --minutes 5 # 指定书目
#   python v2/reader.py --ranks rising,all --top 3  # 刷榜单前 3 名（每本按节奏推进）
#   python v2/reader.py --dry-run                   # 不真正发请求，仅打印计划
#
# 代理：优先环境变量 HTTP_PROXY（或 --proxy），请求经代理出口发送。
import os
import sys
import json
import time
import random
import hashlib
import logging
import argparse
import urllib.parse

V2_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(V2_DIR)
for _path in (ROOT_DIR, V2_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# 凭证加载：环境变量 > 项目根目录 wxread_curl.txt（必须在导入 config 之前）
if not os.getenv("WXREAD_CURL_BASH"):
    _curl_file = os.path.join(ROOT_DIR, "wxread_curl.txt")
    if os.path.exists(_curl_file):
        with open(_curl_file, encoding="utf-8") as f:
            os.environ["WXREAD_CURL_BASH"] = f.read().strip()

import requests
from log_utils import setup_logging, sanitize, mask
from config import data, headers, cookies, HTTP_PROXY, FALLBACK_CHAPTERS
import library
import pace
import idgen

logger = logging.getLogger(__name__)

READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
KEY = "3c5c8717f3daf09iop3423zafeqoi"

REQUEST_TIMEOUT = 15
MAX_FAIL_COUNT = 5
SLEEP_RANGE = (8, 15)   # 每次成功阅读后的等待（秒），比 main.py 略短便于测试
COOKIE_DATA_VARIANTS = [
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
    {"rq": "%2Fweb%2Fbook%2Fread", "ql": True},
    {"rq": "%2Fweb%2Fbook%2Fread"},
]

# ps/pc 为抓包固定的阅读上下文参数（与 main.py 一致）
PS = "fc732b007aa56428g01604c"
PC = "7a432b507aa56430g01640c"

CHARS_PER_PAGE = 300


def create_session(proxy):
    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(cookies)
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
        logger.info("已启用代理：%s", proxy)
    return session


def encode_data(payload):
    return '&'.join(
        f"{k}={urllib.parse.quote(str(payload[k]), safe='')}" for k in sorted(payload.keys())
    )


def cal_hash(input_string):
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1
    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2
    return hex(_7032f5 + _cc1055)[2:].lower()


def refresh_cookie(session):
    """刷新 wr_skey，成功返回 True"""
    for cookie_data in COOKIE_DATA_VARIANTS:
        try:
            response = session.post(
                RENEW_URL,
                data=json.dumps(cookie_data, separators=(',', ':')),
                timeout=REQUEST_TIMEOUT,
            )
            if 'wr_skey' in response.cookies:
                session.cookies.update(response.cookies)
                return True
        except requests.RequestException as exc:
            logger.warning("刷新 cookie 请求失败：%s", sanitize(exc))
    return False


def build_data(book, chapter, last_time):
    """构造一次阅读请求。chapter 为书库章节条目（含 chapterUid/chapterIdx）"""
    payload = {
        "appId": "wb182564874663h571399877",
        "b": book["bookId"],
        "c": idgen.e(chapter["chapterUid"]),
        "ci": chapter.get("chapterIdx") or 0,
        "co": random.randint(0, 800),
        "sm": chapter.get("title", ""),
        "pr": 0,
        "rt": pace.PAGE_SECONDS,
        "ps": PS,
        "pc": PC,
    }
    this_time = int(time.time())
    payload['ct'] = this_time
    payload['rt'] = this_time - last_time
    payload['ts'] = int(this_time * 1000) + random.randint(0, 1000)
    payload['rn'] = random.randint(0, 1000)
    payload['sg'] = hashlib.sha256(f"{payload['ts']}{payload['rn']}{KEY}".encode()).hexdigest()
    payload['s'] = cal_hash(encode_data(payload))
    return this_time


def send_read(session, payload):
    """发送一次阅读请求，返回响应 dict，失败返回 None"""
    try:
        response = session.post(
            READ_URL,
            data=json.dumps(payload, separators=(',', ':')),
            timeout=REQUEST_TIMEOUT,
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("阅读请求失败：%s", sanitize(exc))
        return None


def pages_of(chapter):
    word_count = chapter.get("wordCount") or 0
    return max(1, (word_count + CHARS_PER_PAGE - 1) // CHARS_PER_PAGE)


def read_book(session, book, minutes, dry_run):
    """对一本书按节奏逐章发送阅读请求。返回成功次数。"""
    chapters = book.get("chapters", [])
    if not chapters:
        logger.warning("《%s》无章节数据，跳过。", book.get("title", ""))
        return 0

    budget = int(minutes * 60)
    elapsed = 0
    success = 0
    last_time = int(time.time()) - 60
    fail_count = 0

    logger.info("开始阅读《%s》 bookId=%s（%d 分钟）", book.get("title", ""), book.get("bookId", ""), minutes)
    for chapter in chapters:
        if elapsed >= budget:
            break
        pages = pages_of(chapter)
        chapter_seconds = pages * pace.PAGE_SECONDS
        uid = chapter.get("chapterUid")
        cid = idgen.e(uid) if uid is not None else None
        logger.info("[%02d:%02d:%02d] 第 %s 章《%s》 uid=%s chapterId=%s 约 %d 页",
                    elapsed // 3600, elapsed % 3600 // 60, elapsed % 60,
                    chapter.get("chapterIdx"), chapter.get("title", ""), uid, cid, pages)
        if dry_run:
            elapsed += chapter_seconds
            success += 1
            continue

        this_time = build_data(book, chapter, last_time)
        res = send_read(session, this_time)
        if res is None:
            fail_count += 1
        elif res.get('succ'):
            fail_count = 0
            success += 1
            last_time = this_time
            elapsed += chapter_seconds
            time.sleep(random.randint(*SLEEP_RANGE))
        else:
            logger.warning("read 失败：%s（wr_skey=%s），刷新重试", sanitize(res), mask(cookies.get('wr_skey', '')))
            refresh_cookie(session)
            fail_count += 1

        if fail_count >= MAX_FAIL_COUNT:
            logger.error("连续失败 %d 次，终止本书。", fail_count)
            break

    logger.info("《%s》阅读结束，成功 %d 次。", book.get("title", ""), success)
    return success


def parse_args():
    parser = argparse.ArgumentParser(description="v2 真实阅读刷榜（发送 read 请求，走代理）")
    parser.add_argument("--minutes", type=float, default=5.0, help="每本书阅读分钟数（默认 5）")
    parser.add_argument("--book", default="", help="指定 bookId；缺省从书库随机挑选")
    parser.add_argument("--ranks", default="", help="逗号分隔榜单类型，从当日榜单快照取书刷（如 rising,all）")
    parser.add_argument("--top", type=int, default=5, help="每榜取前 N 名（配合 --ranks）")
    parser.add_argument("--proxy", default="", help="HTTP 代理，默认用环境变量 HTTP_PROXY")
    parser.add_argument("--dry-run", action="store_true", help="不真正发请求，仅打印计划")
    return parser.parse_args()


def books_from_ranks(rank_types, top):
    """从当日榜单快照提取图书 bookId 列表（跨榜去重）"""
    snapshot = library.load_rank_snapshot()
    if not snapshot:
        logger.error("无榜单快照，请先运行 python v2/collector.py。")
        return []
    ranks = snapshot.get("ranks", {})
    books = []
    seen = set()
    for rtype in rank_types:
        for entry in (ranks.get(rtype) or [])[:top]:
            book_id = entry.get("bookId")
            if book_id and book_id not in seen:
                seen.add(book_id)
                books.append(book_id)
    return books


def main():
    args = parse_args()
    setup_logging()

    proxy = args.proxy or HTTP_PROXY or os.getenv("HTTP_PROXY", "")
    session = create_session(proxy)
    if not refresh_cookie(session):
        logger.error("无法刷新 wr_skey，请检查凭证。")
        sys.exit(1)
    logger.info("cookie 刷新成功。")

    book_ids = []
    if args.ranks:
        rank_types = [r.strip() for r in args.ranks.split(",") if r.strip()]
        book_ids = books_from_ranks(rank_types, args.top)
        logger.info("榜单 %s 取前 %d 名，共 %d 本。", ",".join(rank_types), args.top, len(book_ids))
    elif args.book:
        book_ids = [args.book]
    else:
        all_ids = library.list_book_ids()
        if not all_ids:
            logger.error("书库为空，请先采集。")
            sys.exit(1)
        book_ids = [random.choice(all_ids)]

    total_success = 0
    for book_id in book_ids:
        book = library.load_book(book_id)
        if not book:
            logger.warning("书库无 bookId=%s，跳过。", book_id)
            continue
        total_success += read_book(session, book, args.minutes, args.dry_run)
        time.sleep(random.randint(3, 6))

    logger.info("全部完成，共成功 %d 次。", total_success)


if __name__ == "__main__":
    main()
