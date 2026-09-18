# -*- coding: utf-8 -*-
"""SellPilot 桌面版入口：把内嵌的 FastAPI 服务包成一个原生窗口。

同一个应用，两种启动方式（不产生第二套代码）：
    python server.py    纯 Web 模式 —— 浏览器访问 http://127.0.0.1:8623
    python main.py      桌面模式   —— 原生窗口；无 GUI 环境时自动回落默认浏览器

打包：python build.py  →  dist/SellPilot.exe（Windows）/ dist/SellPilot（macOS、Linux）
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

import uvicorn

import config
from server import app

WINDOW_TITLE = "SellPilot · 跨境选品与上架工作台"
WINDOW_SIZE = (1320, 860)
WINDOW_MIN = (960, 640)


def _say(message: str) -> None:
    """窗口模式下 stdout 可能为 None，打印失败不应影响启动。"""
    try:
        print(message, flush=True)
    except Exception:  # noqa: BLE001 - 无控制台时静默
        pass


def _redirect_output_when_headless() -> None:
    """打包成窗口程序后没有控制台：把输出落到 exe 旁的日志文件，便于排查。"""
    if not getattr(sys, "frozen", False) or sys.stdout is not None:
        return
    try:
        stream = open(config.BASE_DIR / "sellpilot.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except Exception:  # noqa: BLE001 - 日志不可写则放弃，不影响运行
        pass


def _pick_port(preferred: int) -> int:
    """优先用配置端口；被占用时让系统分配一个空闲端口（避免与已开实例打架）。"""
    with socket.socket() as probe:
        try:
            probe.bind((config.HOST, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as probe:
        probe.bind((config.HOST, 0))
        return int(probe.getsockname()[1])


def _wait_until_ready(port: int, timeout_s: float = 15.0) -> bool:
    """等服务真正监听后再开窗，避免首屏空白。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex((config.HOST, port)) == 0:
                return True
        time.sleep(0.05)
    return False


def main() -> int:
    _redirect_output_when_headless()

    port = _pick_port(int(config.PORT))
    url = f"http://{config.HOST}:{port}/"

    server = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": app, "host": config.HOST, "port": port, "log_level": "warning"},
        daemon=True,
    )
    server.start()

    if not _wait_until_ready(port):
        _say(f"服务启动超时，请检查端口 {port} 是否可用。")
        return 1

    _say(f"SellPilot 就绪 → {url}")

    try:
        import webview

        webview.create_window(WINDOW_TITLE, url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                              min_size=WINDOW_MIN)
        webview.start()      # 阻塞至窗口关闭
        return 0
    except Exception as exc:  # noqa: BLE001 - 无 GUI 后端（或缺依赖）→ 回落浏览器
        _say(f"未能创建原生窗口（{exc.__class__.__name__}: {exc}），改用默认浏览器打开。")

    webbrowser.open(url)
    try:
        server.join()            # 浏览器模式下服务需常驻，直到进程被结束
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
