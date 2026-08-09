# readall.py 刷榜单全部书籍：每本随机读几章，每章至少 N 秒（默认 60，确保计入阅读时长）
#
# 与 reader.py 不同：reader 按节奏逐章推进一本书；本脚本一次性遍历榜单全部书籍，
# 每本随机抽取若干章，逐章发送真实 read 请求，且每章之间保证至少 --min-rt 秒的
# 真实阅读间隔（rt 字段 >= --min-rt），便于服务端记录阅读时间。
#
# 计入时长依赖 reader.py 的动态会话逻辑（psvts/pc/token/b 均为当前会话动态值）。
#
# 用法：
#   python v2/readall.py                              # 刷全部榜单全部书籍，每本随机 3 章
#   python v2/readall.py --top 5                      # 每榜取前 5 名
#   python v2/readall.py --chapters 5                 # 每本随机读 5 章
#   python v2/readall.py --min-rt 90                  # 每章至少 90 秒
#   python v2/readall.py --ranks rising,all --dry-run # 只打印计划，不发请求
import os
import sys
import time
import random
import logging
import argparse

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

from log_utils import setup_logging, sanitize
from config import HTTP_PROXY, cookies
import library
import reader  # 复用 create_session/refresh_cookie/build_data/send_read/fetch_reader_session

logger = logging.getLogger(__name__)

# 全部榜单类型（collector.RANK_TYPES 保持一致）
RANK_TYPES = [
    "rising", "hot_search", "newbook", "all",
    "newrating_publish", "general_novel_rising", "newrating_potential_publish",
]

MAX_FAIL_COUNT = 5


def parse_args():
    parser = argparse.ArgumentParser(description="刷榜单全部书籍（每本随机读几章，每章至少 N 秒）")
    parser.add_argument("--ranks", default="",
                        help="榜单类型逗号分隔（可选：%s）；缺省用全部榜单" % ",".join(RANK_TYPES))
    parser.add_argument("--top", type=int, default=0, help="每榜取前 N 名；0（默认）= 该榜全部")
    parser.add_argument("--chapters", type=int, default=3, help="每本书随机阅读章节数（默认 3）")
    parser.add_argument("--min-rt", type=int, default=60, help="每章至少阅读秒数（默认 60，便于计入时长）")
    parser.add_argument("--proxy", default="", help="HTTP 代理，默认用环境变量 HTTP_PROXY")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    return parser.parse_args()


def collect_book_ids(rank_types, top):
    """从榜单快照收集图书 bookId（跨榜去重）"""
    snapshot = library.load_rank_snapshot()
    if not snapshot:
        logger.error("无榜单快照，请先运行 python v2/collector.py。")
        return []
    ranks = snapshot.get("ranks", {})
    books, seen = [], set()
    for rtype in rank_types:
        entries = ranks.get(rtype) or []
        if top > 0:
            entries = entries[:top]
        for entry in entries:
            book_id = entry.get("bookId")
            if book_id and book_id not in seen:
                seen.add(book_id)
                books.append(book_id)
    return books


def read_one_chapter(session, book, chapter, session_info, rt, dry_run):
    """发送一章阅读请求，rt >= min_rt。返回 (是否成功)"""
    book_id_hashed = reader.idgen.e(session_info[0])
    uid = chapter.get("chapterUid")
    cid = reader.idgen.e(uid) if uid is not None else None
    if dry_run:
        logger.info("  将读 第 %s 章《%s》 uid=%s chapterId=%s",
                    chapter.get("chapterIdx"), chapter.get("title", ""), uid, cid)
        return True

    payload, _ = reader.build_data(book_id_hashed, chapter, session_info, rt)
    res = reader.send_read(session, payload)
    if res is None:
        logger.warning("  第 %s 章请求失败（网络/解析异常）", chapter.get("chapterIdx"))
        return False
    if not res.get('succ'):
        logger.warning("  第 %s 章 read 失败：%s", chapter.get("chapterIdx"), sanitize(res))
        reader.refresh_cookie(session)
        return False
    logger.info("  第 %s 章《%s》计入成功（rt=%ds）",
                chapter.get("chapterIdx"), chapter.get("title", ""), payload.get('rt'))
    return True


def read_book(session, book, chapters, num_chapters, min_rt, dry_run):
    """对一本书随机选出 num_chapters 章逐一阅读。返回成功次数。"""
    title = book.get("title", "")
    book_id = book.get("bookId", "")
    url_book_id = book_id

    # 每本书先获取动态阅读会话
    session_info = reader.fetch_reader_session(session, url_book_id)
    if not session_info:
        logger.error("《%s》获取阅读会话失败，跳过。", title)
        return 0

    num = min(num_chapters, len(chapters))
    chosen = random.sample(chapters, num)
    logger.info("《%s》 bookId=%s 随机读 %d 章（每章至少 %d 秒）", title, book_id, num, min_rt)

    success = 0
    fail_count = 0
    last_time = int(time.time())
    for chapter in chosen:
        # 保证距上次请求至少 min_rt 秒，使 rt 字段自然 >= min_rt（dry-run 跳过等待）
        wait = min_rt - (int(time.time()) - last_time)
        if wait > 0 and not dry_run:
            time.sleep(wait)
        ok = read_one_chapter(session, book, chapter, session_info, min_rt, dry_run)
        if ok:
            success += 1
            last_time = int(time.time())
            fail_count = 0
        else:
            fail_count += 1
        if not dry_run and fail_count >= MAX_FAIL_COUNT:
            logger.error("《%s》连续失败 %d 次，终止本书。", title, fail_count)
            break
    logger.info("《%s》完成，成功 %d 章。", title, success)
    return success


def main():
    args = parse_args()
    setup_logging()

    rank_types = [r.strip() for r in args.ranks.split(",") if r.strip()] or RANK_TYPES
    proxy = args.proxy or HTTP_PROXY or os.getenv("HTTP_PROXY", "")

    session = reader.create_session(proxy)
    if not args.dry_run and not reader.refresh_cookie(session):
        logger.error("无法刷新 wr_skey，请检查凭证。")
        sys.exit(1)
    if not args.dry_run:
        logger.info("cookie 刷新成功。")

    book_ids = collect_book_ids(rank_types, args.top)
    if not book_ids:
        logger.error("榜单无图书，请先采集。")
        sys.exit(1)
    logger.info("榜单 %s 共 %d 本不重复图书。", ",".join(rank_types), len(book_ids))

    total_success = 0
    for book_id in book_ids:
        book = library.load_book(book_id)
        if not book or not book.get("chapters"):
            logger.warning("书库无章节数据 bookId=%s，跳过。", book_id)
            continue
        total_success += read_book(session, book, book.get("chapters"), args.chapters,
                                   args.min_rt, args.dry_run)
        if not args.dry_run:
            time.sleep(random.randint(3, 6))

    logger.info("全部完成，共成功 %d 章。", total_success)


if __name__ == "__main__":
    main()
