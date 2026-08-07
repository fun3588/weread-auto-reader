# runner.py 模拟阅读干跑：从书库随机挑书，按 pace 节奏打印"将要阅读"的章节与 URL
#
# 明确声明：本脚本只打印计划，不发送任何 read / 网络请求， purely dry-run。
# 真实刷时长由根目录主工程 main.py 承担，本 v2 阶段不做真实阅读。
#
# 节奏模型（见 pace.py）：每页 PAGE_SECONDS=60 秒。章节页数按字数估算
# （约 CHARS_PER_PAGE 字/页），据此把"阅读时长"折算为"逐章推进"。
import os
import sys
import time
import random
import logging
import argparse
import math

V2_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(V2_DIR)
for _path in (ROOT_DIR, V2_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from log_utils import setup_logging
import library
import pace

logger = logging.getLogger(__name__)

CHARS_PER_PAGE = 300   # 估算：每页约 300 字，用于把字数折算成页数


def pages_of(chapter):
    """按字数估算章节页数，至少 1 页"""
    word_count = chapter.get("wordCount") or 0
    return max(1, math.ceil(word_count / CHARS_PER_PAGE))


def fmt_clock(seconds):
    """把秒数格式化为 HH:MM:SS"""
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def simulate(book, minutes):
    """干跑：按时长预算逐章打印将要阅读的内容，不产生任何网络请求"""
    title = book.get("title", "")
    book_id = book.get("bookId", "")
    reader_url = book.get("reader_url", "")
    chapters = book.get("chapters", [])
    if not chapters:
        logger.warning("《%s》无章节数据，无法干跑。", title)
        return

    budget_seconds = minutes * 60
    logger.info("=" * 60)
    logger.info("[干跑] 不会发送任何 read 请求，仅打印阅读计划。")
    logger.info("[干跑] 书目：《%s》 bookId=%s", title, book_id)
    logger.info("[干跑] 阅读入口：%s", reader_url)
    logger.info("[干跑] 节奏：每页 %d 秒；本次模拟 %s 分钟（约 %d 页）",
                pace.PAGE_SECONDS, minutes, pace.pages_for_minutes(minutes))
    logger.info("-" * 60)

    elapsed = 0
    planned_chapters = 0
    planned_pages = 0
    for chapter in chapters:
        if elapsed >= budget_seconds:
            break
        pages = pages_of(chapter)
        chapter_seconds = pages * pace.PAGE_SECONDS
        logger.info("[%s] 将读 第 %s 章《%s》 约 %d 页 (uid=%s)",
                    fmt_clock(elapsed), chapter.get("chapterIdx"),
                    chapter.get("title", ""), pages, chapter.get("chapterUid"))
        logger.debug("        章节级入口：%s", reader_url)
        elapsed += chapter_seconds
        planned_chapters += 1
        planned_pages += pages

    logger.info("-" * 60)
    logger.info("[干跑] 计划阅读 %d 章 / 约 %d 页，累计 %s（预算 %d 秒）。",
                planned_chapters, planned_pages, fmt_clock(elapsed), int(budget_seconds))
    logger.info("[干跑] 结束，未发送任何 read 请求。")


def parse_args():
    parser = argparse.ArgumentParser(description="微信读书书库干跑模拟（不发送 read 请求）")
    parser.add_argument("--minutes", type=float, default=1.0, help="模拟阅读时长（分钟），默认 1")
    parser.add_argument("--book", default="", help="指定 bookId；缺省时从书库随机挑选")
    parser.add_argument("--list", action="store_true", help="仅列出书库中的书籍后退出")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging()

    book_ids = library.list_book_ids()
    if args.list:
        if not book_ids:
            logger.info("书库为空，请先运行 python v2/collector.py --chapters 采集。")
            return
        logger.info("书库共 %d 本书：", len(book_ids))
        for book_id in book_ids:
            book = library.load_book(book_id)
            if book:
                logger.info("  %s  《%s》 %s  %d 章",
                            book_id, book.get("title", ""), book.get("author", ""),
                            book.get("chapter_count", 0))
        return

    if not book_ids:
        logger.error("书库为空，无法干跑。请先运行 python v2/collector.py --chapters 采集。")
        sys.exit(1)

    if args.book:
        if args.book not in book_ids:
            logger.error("书库中不存在 bookId=%s，可用 --list 查看。", args.book)
            sys.exit(1)
        book_id = args.book
    else:
        book_id = random.choice(book_ids)

    book = library.load_book(book_id)
    if not book:
        logger.error("读取 %s 失败。", book_id)
        sys.exit(1)

    simulate(book, args.minutes)


if __name__ == "__main__":
    main()
