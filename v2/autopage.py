# autopage.py 真实浏览器自动翻页刷读：用 playwright 驱动系统 Chrome，逐本打开
# 榜单图书的阅读页，模拟真人阅读节奏（静置 + 翻页），精确计入微信读书阅读时长。
#
# 为什么用它：接口直发 read 请求即使 succ=1 也可能被风控判定异常而不计入排行榜
# 时长。本脚本用真实 Chrome 打开阅读器，行为与真人一致，阅读时长精确计入
# （实测：2 分钟阅读 = readingTime +120 秒，1:1 精确）。
#
# 依赖：pip install playwright（系统 Chrome 即可，无需下载 chromium）
#
# 用法：
#   python v2/autopage.py                                  # 刷全部榜单书（无限循环）
#   python v2/autopage.py --rounds 3                       # 只循环 3 轮
#   python v2/autopage.py --ranks rising,all --top 3       # 每榜前 3 名
#   python v2/autopage.py --book <bookId> --minutes 5      # 指定书刷 5 分钟（单轮）
#   python v2/autopage.py --dry-run                        # 只打印计划
#   python v2/autopage.py --show                           # 显示浏览器窗口（调试）
#
# 参数：
#   --minutes   每本书阅读分钟数（默认 5）
#   --interval  阅读节奏间隔秒数（默认 5，每 4 间隔翻一页 ≈ 20 秒/页）
#   --rounds    循环轮数（默认 0 = 无限循环，刷完一轮休息再刷）
#   --gap       两轮之间的休息分钟数（默认 5）
#   --proxy     HTTP 代理（默认用环境变量 HTTP_PROXY）
import os
import sys
import time
import json
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
from config import cookies, HTTP_PROXY
import library

logger = logging.getLogger(__name__)

RANK_TYPES = [
    "rising", "hot_search", "newbook", "all",
    "newrating_publish", "general_novel_rising", "newrating_potential_publish",
]

# 平台自适应 Chrome 路径：Windows 用系统 Chrome；Linux（GitHub Actions）用 playwright 自带 chromium
if sys.platform.startswith("win"):
    CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
else:
    CHROME_PATH = None  # 交给 playwright 使用其安装的 chromium

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

# 日志同时写文件，便于离线查看运行情况
LOG_FILE = os.path.join(V2_DIR, "autopage.log")


def parse_args():
    parser = argparse.ArgumentParser(description="真实浏览器自动翻页刷读（微信读书阅读时长计入，可无限循环）")
    parser.add_argument("--ranks", default="",
                        help="榜单类型逗号分隔（可选：%s）；缺省用全部榜单" % ",".join(RANK_TYPES))
    parser.add_argument("--top", type=int, default=0, help="每榜取前 N 名；0（默认）= 该榜全部")
    parser.add_argument("--book", default="", help="指定 bookId；指定后忽略榜单参数")
    parser.add_argument("--main-book", default="",
                        help="主刷书 bookId：每轮都刷它，之后再随机刷榜单书（可多个，逗号分隔）")
    parser.add_argument("--random-books", type=int, default=2,
                        help="每轮从榜单书里随机刷几本（配合 --main-book；默认 2）")
    parser.add_argument("--main-minutes", type=float, default=0,
                        help="主刷书每轮阅读分钟数（默认用 --minutes）")
    parser.add_argument("--minutes", type=float, default=5.0, help="每本书阅读分钟数（默认 5）")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="阅读节奏间隔秒数（默认 5，每 4 个间隔翻一页 ≈ 20 秒/页）")
    parser.add_argument("--rounds", type=int, default=0,
                        help="循环轮数（默认 0 = 无限循环，刷完一轮休息再刷）")
    parser.add_argument("--gap", type=float, default=5.0, help="两轮之间的休息分钟数（默认 5）")
    parser.add_argument("--proxy", default="", help="HTTP 代理，默认用环境变量 HTTP_PROXY")
    parser.add_argument("--headless", action="store_true", default=True, help="无头模式（默认）")
    parser.add_argument("--show", action="store_true", help="显示浏览器窗口（调试用）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不启动浏览器")
    return parser.parse_args()


def collect_book_ids(rank_types, top, book_id=None):
    """收集 bookId 列表：指定书 > 榜单书 > 全部书库"""
    if book_id:
        return [book_id]
    snapshot = library.load_rank_snapshot()
    if snapshot:
        ranks = snapshot.get("ranks", {})
        books, seen = [], set()
        for rtype in rank_types:
            entries = ranks.get(rtype) or []
            if top > 0:
                entries = entries[:top]
            for entry in entries:
                bid = entry.get("bookId")
                if bid and bid not in seen:
                    seen.add(bid)
                    books.append(bid)
        if books:
            return books
    return library.list_book_ids()


def wait_for_reader(page, timeout=40):
    """等待阅读器真正加载。用 window.__INITIAL_STATE__ 判断（比 HTML 文本可靠）。
    返回是否成功进入。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            has_state = page.evaluate(
                "typeof window.__INITIAL_STATE__ !== 'undefined' "
                "&& !!window.__INITIAL_STATE__"
            )
            if has_state:
                # 额外确认 reader 数据已就绪
                ready = page.evaluate(
                    "!!(window.__INITIAL_STATE__ && window.__INITIAL_STATE__.reader)"
                )
                if ready:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def read_book_with_browser(ctx, book_id, title, minutes, interval):
    """打开一本书的阅读页，按真人节奏"阅读" minutes 分钟。
    返回 (是否成功, read上报次数)。"""
    url = f"https://weread.qq.com/web/reader/{book_id}"
    page = ctx.new_page()
    logger.info("打开阅读页：%s", url)
    try:
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
    except Exception as exc:
        logger.warning("《%s》打开失败：%s", title, sanitize(exc))
        try:
            page.close()
        except Exception:
            pass
        return False, 0

    entered = wait_for_reader(page)
    if not entered:
        # 可能已超时但仍部分加载，再给一次机会
        time.sleep(5)
        try:
            entered = wait_for_reader(page, timeout=15)
        except Exception:
            entered = False
    if not entered:
        logger.warning("《%s》阅读器未加载（INITIAL_STATE 缺失），可能未登录或页面异常。", title)
        try:
            page.close()
        except Exception:
            pass
        return False, 0
    logger.info("《%s》阅读器已加载，开始阅读。", title)

    # 轻微滚动定位，模拟打开后的翻页手势
    try:
        page.mouse.move(500, 400)
        page.mouse.wheel(0, 300)
    except Exception:
        pass
    time.sleep(3)

    read_count = {"n": 0}
    page.on("request", lambda req: read_count.__setitem__(
        "n", read_count["n"] + 1) if "/web/book/read" in req.url else None)

    # 按真人节奏阅读：多数时间静置（时长自然累计），每约 20 秒翻页/滚动一次
    end = time.time() + minutes * 60
    turns = 0
    idle_since_turn = 0
    turn_cycle = max(2, int(interval * 4))
    while time.time() < end:
        time.sleep(interval)
        idle_since_turn += interval
        if idle_since_turn >= turn_cycle:
            try:
                action = random.choice(["ArrowRight", "Space", "ArrowDown", "wheel"])
                if action == "wheel":
                    page.mouse.wheel(0, random.randint(600, 900))
                else:
                    page.keyboard.press(action)
                turns += 1
                idle_since_turn = 0
                if turns % 3 == 0:
                    logger.info("《%s》已翻页 %d 次，read 上报 %d 次",
                                title, turns, read_count["n"])
            except Exception as exc:
                logger.warning("《%s》翻页异常：%s", title, sanitize(exc))
                time.sleep(3)

    logger.info("《%s》阅读 %g 分钟，翻页 %d 次，read 上报 %d 次。",
                title, minutes, turns, read_count["n"])
    try:
        page.close()
    except Exception:
        pass
    return True, read_count["n"]


def build_browser(proxy, headless):
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    launch_opts = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if CHROME_PATH:
        launch_opts["executable_path"] = CHROME_PATH
    if proxy:
        launch_opts["proxy"] = {"server": proxy}
        logger.info("浏览器代理：%s", proxy)
    browser = p.chromium.launch(**launch_opts)
    ctx = browser.new_context(user_agent=UA)
    for name, value in cookies.items():
        if not value:
            continue
        try:
            ctx.add_cookies([{"name": name, "value": value, "domain": ".weread.qq.com", "path": "/"}])
        except Exception as exc:
            logger.debug("cookie %s 注入跳过：%s", name, sanitize(exc))
    return p, browser, ctx


def run_round(ctx, books_to_read, minutes, interval):
    """刷一轮。books_to_read 为 [(book_id, title, minutes), ...]。返回 read 上报总数。"""
    total_reads = 0
    ok_books = 0
    for book_id, title, bminutes in books_to_read:
        logger.info("=" * 50)
        logger.info("开始《%s》 bookId=%s（%g 分钟）", title, book_id, bminutes)
        try:
            ok, reads = read_book_with_browser(ctx, book_id, title, bminutes, interval)
        except Exception as exc:
            logger.warning("《%s》异常：%s", title, sanitize(exc))
            ok, reads = False, 0
        total_reads += reads
        if ok:
            ok_books += 1
        time.sleep(random.randint(3, 5))
    logger.info("本轮完成：成功 %d/%d 本，read 上报 %d 次。",
                ok_books, len(books_to_read), total_reads)
    return total_reads


def build_round_books(args, rank_book_ids):
    """构造一轮要刷的书列表 [(book_id, title, minutes), ...]。
    - 指定 --book：只刷该书
    - 指定 --main-book：每轮刷主书 + 随机刷 --random-books 本榜单书
    - 否则：刷全部榜单书"""
    def load(bid):
        book = library.load_book(bid)
        return book.get("title", "") if book else ""

    if args.book:
        return [(args.book, load(args.book) or args.book, args.minutes)]

    if args.main_book:
        main_ids = [b.strip() for b in args.main_book.split(",") if b.strip()]
        main_minutes = args.main_minutes or args.minutes
        books = [(bid, load(bid) or bid, main_minutes) for bid in main_ids]
        # 随机补充榜单书
        pool = [bid for bid in rank_book_ids if bid not in set(main_ids)]
        if pool and args.random_books > 0:
            picks = random.sample(pool, min(args.random_books, len(pool)))
            for bid in picks:
                books.append((bid, load(bid) or bid, args.minutes))
        return books

    return [(bid, load(bid) or bid, args.minutes) for bid in rank_book_ids]


def main():
    args = parse_args()
    setup_logging()

    # 日志写文件（追加）
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="a")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(fh)
    logger.info("=" * 60)
    logger.info("autopage 启动，日志文件：%s", LOG_FILE)

    rank_types = [r.strip() for r in args.ranks.split(",") if r.strip()] or RANK_TYPES
    rank_book_ids = collect_book_ids(rank_types, args.top, args.book)
    if args.book:
        rank_book_ids = []  # 指定单书时无需榜单
    if not rank_book_ids and not args.main_book and not args.book:
        logger.error("没有可刷的书籍，请先运行 python v2/collector.py 采集。")
        sys.exit(1)

    if args.dry_run:
        for book_id, title, bmin in build_round_books(args, rank_book_ids):
            logger.info("[dry-run] bookId=%s 《%s》 将阅读 %g 分钟", book_id, title, bmin)
        return

    proxy = args.proxy or HTTP_PROXY or os.getenv("HTTP_PROXY", "")
    p, browser, ctx = build_browser(proxy, args.headless and not args.show)

    try:
        rounds = args.rounds
        round_no = 0
        while True:
            round_no += 1
            books_to_read = build_round_books(args, rank_book_ids)
            logger.info("########## 第 %d 轮开始（%d 本） ##########", round_no, len(books_to_read))
            try:
                run_round(ctx, books_to_read, args.minutes, args.interval)
            except Exception as exc:
                logger.error("第 %d 轮异常：%s", round_no, sanitize(exc))
            if rounds > 0 and round_no >= rounds:
                break
            gap = args.gap * 60
            logger.info("第 %d 轮完成，休息 %g 分钟后继续...", round_no, args.gap)
            time.sleep(gap)
    finally:
        try:
            browser.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass

    logger.info("已按设置完成 %d 轮，退出。", round_no)


if __name__ == "__main__":
    main()
