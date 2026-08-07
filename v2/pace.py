# pace.py 阅读节奏参数：每页约 60 秒、每天 20 小时（约 1200 页/天）
#
# 本模块只描述"未来真实阅读"时应采用的节奏，供 runner.py 干跑推演。
# 当前 v2 阶段不发送任何 read 请求；真实刷时长仍由根目录主工程 main.py 承担。
#
# 推导关系：
#   每天秒数 = DAILY_HOURS * 3600
#   每天页数 = 每天秒数 / PAGE_SECONDS ≈ 20 * 3600 / 60 = 1200 页
# 未来构造真实阅读请求时，应按 PAGE_SECONDS 为每次请求的 rt（阅读时长，秒）取值，
# 即以 rt≈60 的节奏逐页上报，使单日累计接近 DAILY_HOURS 小时。

PAGE_SECONDS = 60      # 每页阅读耗时（秒），对应真实请求的 rt 字段
DAILY_HOURS = 20       # 每日目标阅读小时数
SECONDS_PER_HOUR = 3600


def daily_seconds():
    """每日目标阅读总秒数"""
    return DAILY_HOURS * SECONDS_PER_HOUR


def daily_pages():
    """按当前节奏推导的每日页数（约 1200）"""
    return daily_seconds() // PAGE_SECONDS


def pages_for_minutes(minutes):
    """给定分钟数可阅读的页数，供 runner.py 短时干跑使用"""
    return int(minutes * 60 // PAGE_SECONDS)


if __name__ == "__main__":
    print(f"每页 {PAGE_SECONDS} 秒，每天 {DAILY_HOURS} 小时 -> 约 {daily_pages()} 页/天")
