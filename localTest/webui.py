"""本地 WebUI：实时展示挂机阅读运行状态。

- 仅用 Python 标准库，无新增依赖
- 只绑定 127.0.0.1，不对外网暴露
- 展示内容不含任何凭证；日志回显写入前已经脱敏
- 端口从 3000 开始探测，占用则随机尝试 3001-3099
"""
import json
import random
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>微信读书挂机监控</title>
<style>
  body { background:#12141a; color:#dfe3ea; font-family:"Segoe UI",Microsoft YaHei,sans-serif; margin:0; padding:24px; }
  h1 { font-size:20px; margin:0 0 16px; }
  .cards { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
  .card { background:#1c1f27; border:1px solid #2a2e3a; border-radius:10px; padding:14px 18px; min-width:150px; }
  .card .label { color:#8a91a0; font-size:12px; margin-bottom:6px; }
  .card .value { font-size:22px; font-weight:600; }
  .bar-outer { background:#1c1f27; border:1px solid #2a2e3a; border-radius:10px; height:26px; overflow:hidden; margin-bottom:16px; }
  .bar-inner { background:linear-gradient(90deg,#3f8cff,#6ee7a8); height:100%; width:0%; transition:width 1s; }
  .logs { background:#0d0f13; border:1px solid #2a2e3a; border-radius:10px; padding:12px; height:320px; overflow-y:auto;
          font-family:Consolas,monospace; font-size:12px; line-height:1.7; white-space:pre-wrap; }
  .status-reading { color:#6ee7a8; } .status-done { color:#3f8cff; }
  .status-error { color:#ff7a7a; } .status-idle { color:#8a91a0; }
  .footer { color:#5b6170; font-size:12px; margin-top:12px; }
</style>
</head>
<body>
<h1>微信读书自动阅读 - 本地挂机监控</h1>
<div class="cards">
  <div class="card"><div class="label">状态</div><div class="value" id="status">-</div></div>
  <div class="card"><div class="label">轮次</div><div class="value" id="round">-</div></div>
  <div class="card"><div class="label">本轮进度</div><div class="value" id="progress">-</div></div>
  <div class="card"><div class="label">累计成功</div><div class="value" id="success">-</div></div>
  <div class="card"><div class="label">计入时长</div><div class="value" id="minutes">-</div></div>
  <div class="card"><div class="label">连续失败</div><div class="value" id="fails">-</div></div>
  <div class="card"><div class="label">最近结果</div><div class="value" id="last" style="font-size:14px">-</div></div>
  <div class="card"><div class="label">密钥刷新时间</div><div class="value" id="cookie" style="font-size:14px">-</div></div>
  <div class="card"><div class="label">本轮开始</div><div class="value" id="started" style="font-size:14px">-</div></div>
</div>
<div class="bar-outer"><div class="bar-inner" id="bar"></div></div>
<div class="logs" id="logs"></div>
<div class="footer">页面每 3 秒自动刷新 | 仅监听 127.0.0.1 | 展示内容不含凭证，日志已脱敏</div>
<script>
const STATUS_TEXT = {reading:"阅读中", done:"本轮完成", error:"异常终止", idle:"待启动"};
async function refresh() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const s = data.state;
    const setStatus = document.getElementById("status");
    setStatus.textContent = STATUS_TEXT[s.status] || s.status;
    setStatus.className = "value status-" + s.status;
    document.getElementById("round").textContent = s.round || "-";
    document.getElementById("progress").textContent = s.index + " / " + s.read_num;
    document.getElementById("success").textContent = s.success_count;
    document.getElementById("minutes").textContent = (s.success_count * 0.5).toFixed(1) + " 分钟";
    document.getElementById("fails").textContent = s.fail_count;
    document.getElementById("last").textContent = s.last_result || "-";
    document.getElementById("cookie").textContent = s.cookie_refreshed_at || "-";
    document.getElementById("started").textContent = s.started_at || "-";
    const pct = s.read_num > 0 ? Math.min(100, (s.index - 1) / s.read_num * 100) : 0;
    document.getElementById("bar").style.width = pct + "%";
    const logsBox = document.getElementById("logs");
    const stick = logsBox.scrollTop + logsBox.clientHeight >= logsBox.scrollHeight - 30;
    logsBox.textContent = data.logs.join("\\n");
    if (stick) logsBox.scrollTop = logsBox.scrollHeight;
  } catch (e) { /* 服务重启中，忽略 */ }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


def find_free_port(start=3000):
    """优先 start，被占用则在 start+1 ~ start+99 随机探测可用端口"""
    candidates = [start] + random.sample(range(start + 1, start + 100), 99)
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"端口 {start}-{start + 99} 均不可用")


def start_webui(get_state, get_logs, start_port=3000):
    """在后台线程启动 WebUI，返回实际监听端口"""
    port = find_free_port(start_port)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/status":
                payload = {"state": get_state(), "logs": list(get_logs())}
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, fmt, *args):  # 静默访问日志，避免刷屏
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
