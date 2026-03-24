
# standard library
from datetime import datetime
import json
import logging
import os
import threading

from typing import Any, Dict, List, Optional

# self defined
from config import Config
from push_module import Jin10NewsPusher

trading_agent = None
_agent_operation_lock = threading.Lock()

logger = logging.getLogger(__name__)

def on_jin10_news(items: List[Dict[str, Any]]) -> None:
    """接收金十快讯推送，汇总后注入 agent。"""
    try:
        if not items or trading_agent is None:
            return
        lines = []
        for i, item in enumerate(items[:5], 1):  # 最多 5 条，避免上下文过长
            content = (item.get("data") or {}).get("content", "")
            if content:
                lines.append(f"{i}. {content[:200]}{'...' if len(content) > 200 else ''}")
        if not lines:
            return
        text = "【金十快讯】收到新快讯：\n" + "\n".join(lines)
        with _agent_operation_lock:
            trading_agent.chat(text, silent=True)
    except Exception:
        logger.exception("处理金十快讯失败")


def init() -> None:
    if Config.JIN10_ENABLED:
        jin10_pusher = Jin10NewsPusher(interval_seconds=Config.JIN10_INTERVAL)
        jin10_pusher.set_on_news(on_jin10_news)
        jin10_pusher.start()