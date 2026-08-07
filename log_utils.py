import logging
import os
import sys
from collections import deque

# 已注册的敏感凭证，任何日志输出前都会被替换为 ***
_SECRETS = set()

# 最近的日志回显（供本地 WebUI 展示），写入前已经脱敏
LOG_TAIL = deque(maxlen=100)


def register_secret(value):
    """注册敏感凭证（如 cookie 值、SendKey、curl 原文），日志输出时自动脱敏"""
    text = str(value or "").strip()
    # 过短的字符串不注册，避免误伤正常日志内容
    if len(text) >= 8:
        _SECRETS.add(text)


def sanitize(text):
    """将文本中出现的已注册凭证替换为 ***"""
    text = str(text)
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text


def mask(value, keep=2):
    """遮蔽敏感值，仅保留前 keep 位，如 ab***"""
    text = str(value or "")
    if len(text) <= keep:
        return "***"
    return f"{text[:keep]}***"


def _sanitize_record(record):
    """兜底脱敏：过滤日志消息与参数中的已注册凭证，
    防止异常堆栈/请求详情意外泄露 cookie 或 token"""
    if isinstance(record.msg, str):
        record.msg = sanitize(record.msg)
    if isinstance(record.args, tuple):
        record.args = tuple(
            sanitize(arg) if isinstance(arg, (str, Exception)) else arg
            for arg in record.args
        )
    elif isinstance(record.args, dict):
        record.args = {
            key: sanitize(value) if isinstance(value, (str, Exception)) else value
            for key, value in record.args.items()
        }


def setup_logging(width=120):
    active = False

    def clear():
        nonlocal active
        if not active:
            return
        print("\r" + " " * width + "\r", end="", flush=True)
        active = False

    def refresh_print(message):
        nonlocal active
        active = True
        print(f"\r{message:<{width}}", end="", flush=True)

    class RefreshSafeHandler(logging.Handler):
        def emit(self, record):
            clear()
            _sanitize_record(record)
            message = self.format(record)
            stream = sys.stderr if record.levelno >= logging.WARNING else sys.stdout
            stream.write(message + "\n")
            stream.flush()

    class TailHandler(logging.Handler):
        """将脱敏后的日志存入环形缓冲，供本地 WebUI 展示"""

        def emit(self, record):
            try:
                _sanitize_record(record)
                LOG_TAIL.append(self.format(record))
            except Exception:
                pass

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    # 支持通过环境变量调整日志级别，默认 INFO
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger.setLevel(getattr(logging, level, logging.INFO))

    formatter = logging.Formatter("%(asctime)s - %(levelname)-8s - %(message)s")
    handler = RefreshSafeHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    tail_handler = TailHandler()
    tail_handler.setFormatter(formatter)
    root_logger.addHandler(tail_handler)
    return refresh_print
