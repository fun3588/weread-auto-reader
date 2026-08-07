"""本地挂机测试：持续循环阅读，Ctrl+C 停止。

用法（项目根目录或本目录均可）：
    python localTest/run_local.py

凭证来源优先级：环境变量 WXREAD_CURL_BASH > 项目根目录的 wxread_curl.txt
推送：配置环境变量 SERVERCHAN_SPT 即启用 ServerChan 推送；
      推送内容仅为固定文案（完成/失败通知），wxread_curl.txt 中的凭证
      不会进入任何推送消息与 WebUI 页面。
可选环境变量：
    READ_NUM        每轮阅读次数（默认 400，约 3 小时 20 分钟一轮）
    SERVERCHAN_SPT  ServerChan SendKey，配置后启用推送
    LOG_LEVEL       日志级别（默认 INFO，调试可设 DEBUG）
"""
import os
import sys
import time
import random

# 使项目根目录可导入（main/config/push/log_utils）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 自动加载抓包 curl 命令（未设置环境变量时）
if not os.getenv("WXREAD_CURL_BASH"):
    curl_file = os.path.join(ROOT, "wxread_curl.txt")
    if os.path.exists(curl_file):
        with open(curl_file, encoding="utf-8") as f:
            os.environ["WXREAD_CURL_BASH"] = f.read().strip()
        print("已从 wxread_curl.txt 加载抓包命令。")
    else:
        print("错误：未设置 WXREAD_CURL_BASH 环境变量，且未找到 wxread_curl.txt。")
        sys.exit(1)

# 本地挂机默认参数
os.environ.setdefault("READ_NUM", "400")     # 每轮阅读次数
# 推送：设置了 SERVERCHAN_SPT 则启用，未设置则跳过推送（push 模块自行处理）
if os.getenv("SERVERCHAN_SPT"):
    print("推送已启用（ServerChan）。")
else:
    print("未配置 SERVERCHAN_SPT，本次运行不推送；设置该环境变量即可启用。")

import main  # noqa: E402  环境变量就绪后再导入
from log_utils import LOG_TAIL  # noqa: E402
import webui  # noqa: E402  与本脚本同目录

WINDOW_PAUSE_RANGE = (300, 600)  # 轮与轮之间休息 5-10 分钟，模拟间歇使用


def main_loop():
    # 启动本地 WebUI（仅 127.0.0.1，端口从 3000 起探测）
    port = webui.start_webui(lambda: main.RUNTIME_STATE, lambda: LOG_TAIL)
    print(f"WebUI 监控已启动：http://127.0.0.1:{port}")

    round_no = 0
    while True:
        round_no += 1
        main.RUNTIME_STATE["round"] = round_no
        print(f"\n===== 第 {round_no} 轮挂机阅读开始 =====", flush=True)
        try:
            main.main()
        except KeyboardInterrupt:
            print("\n已手动停止挂机。")
            return
        except SystemExit as exc:
            print(f"本轮异常终止：{exc}")
        except Exception as exc:  # 兜底，防止意外崩溃打断挂机
            print(f"本轮出现未捕获异常：{exc}")

        pause = random.randint(*WINDOW_PAUSE_RANGE)
        print(f"本轮结束，休息 {pause} 秒后开始下一轮（Ctrl+C 停止）...", flush=True)
        try:
            time.sleep(pause)
        except KeyboardInterrupt:
            print("\n已手动停止挂机。")
            return


if __name__ == "__main__":
    main_loop()
