# library.py 书库读写（JSON）与增量去重
#
# 数据结构：
#   v2/data/ranks_YYYY-MM-DD.json   榜单快照（榜单/排名/bookId/书名/作者/推荐值）
#   v2/data/books/{bookId}.json     单本书：章节列表 + 阅读 URL
#
# 说明：
# - bookId 指阅读页使用的哈希形态 id（即 book-detail deepLink 的 v= 参数），
#   与榜单 bookInfo 内的数字 bookId 不同，后者另存为 numericBookId。
# - 写入采用 临时文件 + os.replace 的原子方式，避免半截 JSON 污染书库。
import os
import json
import time
import logging

logger = logging.getLogger(__name__)

# v2/data 目录（相对本文件定位，独立于运行时工作目录）
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BOOKS_DIR = os.path.join(DATA_DIR, "books")


def ensure_dirs():
    """确保 data/ 与 data/books/ 存在"""
    os.makedirs(BOOKS_DIR, exist_ok=True)


def today_str():
    """当天日期，形如 2026-08-07"""
    return time.strftime("%Y-%m-%d")


def now_str():
    """当前时间戳，形如 2026-08-07 23:30:00"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load_json(path):
    """读取 JSON，文件不存在或损坏时返回 None"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("读取 %s 失败：%s", path, exc)
        return None


def _save_json(path, payload):
    """原子写入 JSON（先写临时文件再替换）"""
    ensure_dirs()
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


# ---------- 榜单快照 ----------

def rank_snapshot_path(date_str=None):
    date_str = date_str or today_str()
    return os.path.join(DATA_DIR, f"ranks_{date_str}.json")


def load_rank_snapshot(date_str=None):
    """读取某日榜单快照，不存在返回 None"""
    return _load_json(rank_snapshot_path(date_str))


def save_rank_snapshot(ranks, date_str=None):
    """保存榜单快照。ranks 形如 {榜单类型: [条目, ...]}"""
    date_str = date_str or today_str()
    payload = {
        "date": date_str,
        "collected_at": now_str(),
        "ranks": ranks,
    }
    path = rank_snapshot_path(date_str)
    _save_json(path, payload)
    logger.info("榜单快照已保存：%s", path)
    return path


# ---------- 单本书 ----------

def book_path(book_id):
    return os.path.join(BOOKS_DIR, f"{book_id}.json")


def has_book(book_id):
    """书库中是否已有该书（用于增量去重）"""
    return os.path.exists(book_path(book_id))


def load_book(book_id):
    """读取单本书数据，不存在返回 None"""
    return _load_json(book_path(book_id))


def save_book(book_id, book):
    """保存单本书（章节列表 + 阅读 URL）"""
    path = book_path(book_id)
    _save_json(path, book)
    logger.debug("书籍已保存：%s", path)
    return path


def list_book_ids():
    """列出书库中全部 bookId"""
    ensure_dirs()
    return sorted(
        name[:-5] for name in os.listdir(BOOKS_DIR)
        if name.endswith(".json") and not name.endswith(".tmp")
    )


def load_all_books():
    """读取书库全部书籍，返回 [book, ...]，损坏文件自动跳过"""
    books = []
    for book_id in list_book_ids():
        book = load_book(book_id)
        if book:
            books.append(book)
    return books
