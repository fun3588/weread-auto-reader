# push.py 推送模块，仅支持 ServerChan
import json
import logging
import random
import time

import requests

from config import SERVERCHAN_SPT
from log_utils import sanitize

logger = logging.getLogger(__name__)

SERVERCHAN_URL = "https://sctapi.ftqq.com/{}.send"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 10


def push(content, is_success=True):
    """通过 ServerChan 推送消息，返回是否推送成功"""
    if not SERVERCHAN_SPT:
        logger.warning("未配置 SERVERCHAN_SPT，跳过推送。")
        return False

    title = f"微信读书自动阅读-{'成功' if is_success else '失败'}"
    url = SERVERCHAN_URL.format(SERVERCHAN_SPT)
    payload = json.dumps({"title": title, "desp": content}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            # ServerChan 业务码为 0 才是真正推送成功
            if result.get("code") == 0:
                logger.info("ServerChan 推送成功。")
                return True
            logger.warning("ServerChan 业务返回异常：%s", sanitize(result))
        except (requests.RequestException, ValueError) as exc:
            # 异常消息中包含带 SendKey 的 URL，必须脱敏后再写日志
            logger.error("ServerChan 推送失败（第 %d/%d 次）：%s", attempt, MAX_ATTEMPTS, sanitize(exc))

        if attempt < MAX_ATTEMPTS:
            sleep_time = random.randint(30, 60)
            logger.info("%d 秒后重试...", sleep_time)
            time.sleep(sleep_time)

    return False
