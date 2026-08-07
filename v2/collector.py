# collector.py 采集入口：榜单 -> 图书 -> 章节 -> 保存
#
# 数据来源（均经 2026-08-07 实测验证）：
# - 榜单：GET https://weread.qq.com/web/category/{type}，解析页面内嵌的
#   window.__INITIAL_STATE__.categoryStoreModule.categoryBookList（单页前 20 名）
# - 章节：GET https://weread.qq.com/web/reader/{bookId}，解析
#   window.__INITIAL_STATE__.reader.chapterInfos（完整章节列表）
#
# 注意：chapterInfos 增量接口实测仅返回增量（updated 为空），无法拿全量章节，
# 故章节改从阅读页内嵌数据解析（spec 已预留此兜底路径）。
#
# 鉴权：复用根目录 config.py 的 headers/cookies（环境变量 > wxread_curl.txt）。
# 本脚本只做数据采集，不发送任何 read 请求。
import os
import re
import sys
import json
import time
import random
import logging
import argparse

# 使本脚本可从任意工作目录运行：把仓库根目录与 v2/ 目录加入 sys.path
V2_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(V2_DIR)
for _path in (ROOT_DIR, V2_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import requests

# 凭证加载与根项目一致：环境变量 WXREAD_CURL_BASH > 项目根目录 wxread_curl.txt
# 必须在导入 config 之前完成，否则 config 会落到占位 cookies
if not os.getenv("WXREAD_CURL_BASH"):
    _curl_file = os.path.join(ROOT_DIR, "wxread_curl.txt")
    if os.path.exists(_curl_file):
        with open(_curl_file, encoding="utf-8") as f:
            os.environ["WXREAD_CURL_BASH"] = f.read().strip()

from config import headers, cookies
from log_utils import setup_logging, sanitize
import library

logger = logging.getLogger(__name__)

WEB_BASE = "https://weread.qq.com"
CATEGORY_URL = f"{WEB_BASE}/web/category"
READER_URL = f"{WEB_BASE}/web/reader"

# 已知榜单类型（spec 约定）
RANK_TYPES = [
    "rising",                      # 飙升榜
    "hot_search",                  # 热搜榜
    "newbook",                     # 新书榜
    "all",                         # 总榜
    "newrating_publish",           # 新评分榜
    "general_novel_rising",        # 小说飙升榜
    "newrating_potential_publish", # 潜力榜
]

# 推荐值候选字段：不同榜单用不同指标，按优先级取第一个非零值
RECOMMEND_FIELDS = ["searchCount", "riseCount", "readingCount"]

REQUEST_TIMEOUT = 15   # 单次请求超时（秒）
MAX_RETRY = 3          # 单步请求重试上限
DELAY_RANGE = (2, 5)   # 请求间随机延迟（秒），性能规范要求


def create_session():
    """创建带鉴权信息的会话，复用根项目凭证"""
    session = requests.Session()
    session.headers.update(headers)
    session.cookies.update(cookies)
    return session


def _polite_sleep():
    """请求间随机延迟，模拟真人节奏并降低风控压力"""
    time.sleep(random.uniform(*DELAY_RANGE))


def extract_state(html):
    """平衡括号提取 window.__INITIAL_STATE__ 后的 JSON 对象。
    页面内嵌 JSON 体积大且含嵌套，简单正则易越界，这里逐字符配对大括号，
    并正确处理字符串内的转义与花括号。解析失败返回 None。"""
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
                    except ValueError as exc:
                        logger.warning("INITIAL_STATE 解析失败：%s", sanitize(exc))
                        return None
        i += 1
    return None


def reader_book_id(book_info):
    """从 bookInfo.deepLink 的 v= 参数提取阅读页使用的哈希 bookId。
    榜单内 bookInfo.bookId 为数字 id，阅读 URL 用的是哈希形态 id，二者不同。"""
    match = re.search(r"[?&]v=([0-9a-zA-Z]+)", book_info.get("deepLink", ""))
    return match.group(1) if match else None


def pick_recommend(entry):
    """选取推荐值：按优先级取第一个非零指标，返回 (值, 字段名)"""
    for field in RECOMMEND_FIELDS:
        value = entry.get(field)
        if isinstance(value, (int, float)) and value > 0:
            return value, field
    for field in RECOMMEND_FIELDS:
        if field in entry:
            return entry.get(field), field
    return 0, ""


def build_rank_entry(entry):
    """把榜单原始条目整理为快照结构（榜单/排名/bookId/书名/作者/推荐值）"""
    info = entry.get("bookInfo", {}) or {}
    url_id = reader_book_id(info)
    recommend, recommend_field = pick_recommend(entry)
    return {
        "rank": entry.get("searchIdx"),
        "bookId": url_id,
        "numericBookId": str(info.get("bookId", "")),
        "title": info.get("title", ""),
        "author": info.get("author", ""),
        "recommend": recommend,
        "recommend_field": recommend_field,
        "cover": info.get("cover", ""),
        "reader_url": f"{READER_URL}/{url_id}" if url_id else "",
    }


def fetch_rank(session, rank_type):
    """抓取单个榜单的图书列表，返回整理后的条目列表，失败返回空列表"""
    url = f"{CATEGORY_URL}/{rank_type}"
    for attempt in range(1, MAX_RETRY + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            state = extract_state(response.text)
            if not state:
                logger.warning("榜单 %s 未提取到内嵌数据（第 %d 次）", rank_type, attempt)
                continue
            entries = state.get("categoryStoreModule", {}).get("categoryBookList", [])
            if entries:
                logger.info("榜单 %s 抓取成功，共 %d 条。", rank_type, len(entries))
                return [build_rank_entry(item) for item in entries]
            logger.warning("榜单 %s 条目为空（第 %d 次）", rank_type, attempt)
        except requests.RequestException as exc:
            logger.warning("榜单 %s 请求失败（第 %d 次）：%s", rank_type, attempt, sanitize(exc))
        _polite_sleep()
    logger.error("榜单 %s 重试 %d 次后仍失败，跳过。", rank_type, MAX_RETRY)
    return []


def fetch_book_chapters(session, url_book_id):
    """抓取单本书的完整章节列表，返回 (chapters, book_info)，失败返回 (None, None)。
    章节来自阅读页内嵌数据 reader.chapterInfos（chapterInfos 增量接口拿不到全量）。"""
    url = f"{READER_URL}/{url_book_id}"
    for attempt in range(1, MAX_RETRY + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            state = extract_state(response.text)
            if not state:
                logger.warning("阅读页 %s 未提取到内嵌数据（第 %d 次）", url_book_id, attempt)
                continue
            reader_mod = state.get("reader", {})
            chapters = reader_mod.get("chapterInfos", [])
            book_info = reader_mod.get("bookInfo", {}) or {}
            if chapters:
                return chapters, book_info
            logger.warning("阅读页 %s 章节为空（第 %d 次）", url_book_id, attempt)
        except requests.RequestException as exc:
            logger.warning("阅读页 %s 请求失败（第 %d 次）：%s", url_book_id, attempt, sanitize(exc))
        _polite_sleep()
    return None, None


def collect_chapters(session, book_id, entry, force=False):
    """采集并保存单本书章节。已入库且不强制刷新时跳过（增量去重）。返回是否采集。"""
    if library.has_book(book_id) and not force:
        logger.info("书库已有，跳过《%s》", entry.get("title", book_id))
        return False

    chapters, book_info = fetch_book_chapters(session, book_id)
    if not chapters:
        logger.error("《%s》章节抓取失败，未入库。", entry.get("title", book_id))
        return False

    book = {
        "bookId": book_id,
        "numericBookId": entry.get("numericBookId", str(book_info.get("bookId", ""))),
        "title": book_info.get("title", entry.get("title", "")),
        "author": book_info.get("author", entry.get("author", "")),
        "reader_url": f"{READER_URL}/{book_id}",
        "collected_at": library.now_str(),
        "chapter_count": len(chapters),
        # chapterUid/chapterIdx 为接口返回的真实字段；真实 read 请求所需的
        # 哈希 chapterId 需另行推导，属未来真实阅读阶段的工作，本期不涉及。
        "chapters": [
            {
                "chapterUid": ch.get("chapterUid"),
                "chapterIdx": ch.get("chapterIdx"),
                "title": ch.get("title", ""),
                "wordCount": ch.get("wordCount", 0),
            }
            for ch in chapters
        ],
    }
    library.save_book(book_id, book)
    logger.info("《%s》章节采集完成，共 %d 章。", book["title"], len(chapters))
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="微信读书榜单书库采集（只采集，不发 read 请求）")
    parser.add_argument(
        "--ranks", default="rising,all",
        help="要采集的榜单类型，逗号分隔，可选：%s（默认 rising,all）" % ",".join(RANK_TYPES),
    )
    parser.add_argument("--top", type=int, default=20, help="每榜采集前 N 名（默认 20，页面单页上限）")
    parser.add_argument("--chapters", action="store_true", help="同时抓取各书章节列表并入库")
    parser.add_argument("--force", action="store_true", help="已入库的书也强制重新抓取章节")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging()

    rank_types = [r.strip() for r in args.ranks.split(",") if r.strip()]
    unknown = [r for r in rank_types if r not in RANK_TYPES]
    if unknown:
        logger.warning("未知榜单类型（仍会尝试抓取）：%s", ", ".join(unknown))

    session = create_session()
    logger.info("开始采集榜单：%s（每榜前 %d 名）", ", ".join(rank_types), args.top)

    all_ranks = {}
    books_to_fetch = {}  # bookId -> 榜单条目，跨榜去重
    for rank_type in rank_types:
        entries = fetch_rank(session, rank_type)
        top_entries = entries[:args.top]
        all_ranks[rank_type] = top_entries
        for item in top_entries:
            if item.get("bookId"):
                books_to_fetch.setdefault(item["bookId"], item)
        _polite_sleep()

    if not any(all_ranks.values()):
        logger.error("所有榜单均抓取失败，请检查凭证（WXREAD_CURL_BASH / wxread_curl.txt）是否有效。")
        sys.exit(1)

    library.save_rank_snapshot(all_ranks)

    if args.chapters:
        logger.info("开始采集章节，共 %d 本不重复图书。", len(books_to_fetch))
        fetched = 0
        for book_id, entry in books_to_fetch.items():
            if collect_chapters(session, book_id, entry, force=args.force):
                fetched += 1
            _polite_sleep()
        logger.info("章节采集结束，本次新入库 %d 本。", fetched)

    total = sum(len(v) for v in all_ranks.values())
    logger.info("采集完成：榜单 %d 个、条目合计 %d 条、不重复图书 %d 本。",
                len(all_ranks), total, len(books_to_fetch))


if __name__ == "__main__":
    main()
