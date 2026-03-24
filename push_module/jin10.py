"""
金十快讯推送模块：定时拉取最新快讯，通过回调推送给 main。

与 LongPort set_on_candlestick 模式一致：
- main 调用 set_on_news(callback) 注册
- Jin10NewsPusher 负责拉取，有新快讯时调用 callback(items)
"""

import datetime
import logging
import threading
import time
from typing import Callable, List, Optional

import requests

logger = logging.getLogger("Jin10")

URL = "https://flash-api.jin10.com/get_flash_list"
HEADERS = {
    "x-app-id": "SO1EJGmNgCtmpcPF",
    "x-version": "1.0.0",
}
CHANNEL = "-8200"


def fetch_flash_list(max_time: Optional[str] = None) -> List[dict]:
    """拉取金十快讯，返回 data 数组。"""
    params = {
        "max_time": max_time or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "channel": CHANNEL,
    }
    try:
        r = requests.get(URL, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        if data.get("status") == 200:
            return data.get("data") or []
    except Exception as e:
        logger.warning("金十快讯拉取失败: %s", e)
    return []


class Jin10NewsPusher:
    """
    定时拉取金十快讯，有新快讯时回调 on_news(items)。
    """

    def __init__(self, interval_seconds: int = 60):
        self._interval = interval_seconds
        self._on_news: Optional[Callable[[List[dict]], None]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_max_time: Optional[str] = None  # 上次最新快讯时间，用于增量

    def set_on_news(self, callback: Callable[[List[dict]], None]) -> None:
        """注册回调：收到新快讯时调用 callback(items)。"""
        self._on_news = callback

    def start(self) -> None:
        """启动后台线程，定时拉取并推送。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="Jin10NewsPusher",
            daemon=True,
        )
        self._thread.start()
        logger.info("Jin10NewsPusher 已启动, 间隔 %ds", self._interval)

    def stop(self) -> None:
        """停止后台线程。"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            items = fetch_flash_list(None)  # 始终拉最新
            if items:
                if self._last_max_time is None:
                    new_items = []  # 首次轮询只预热，不推送
                else:
                    new_items = [x for x in items if x.get("time", "") > self._last_max_time]
                if new_items and self._on_news:
                    self._on_news(new_items)
                self._last_max_time = items[0].get("time")
            self._stop.wait(self._interval)
