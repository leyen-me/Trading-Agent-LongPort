"""
LongPort 行情接口返回值 → 可 JSON 序列化的 dict / list。

按 SDK 公开字段显式拼装，避免通用反射序列化带来的环引用、类型异常等问题。
字段参考：longport openapi.pyi（SecurityQuote、Candlestick 等）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from longport.openapi import Candlestick, PrePostQuote, SecurityQuote


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, type):
        return getattr(value, "__name__", str(value))
    return str(value)

def pack_pre_post_quote(q: PrePostQuote) -> Optional[Dict[str, PrePostQuote]]:
    if q is None:
        return None
    return {
        "last_done": _scalar(q.last_done),
        "timestamp": _scalar(q.timestamp),
        "volume": _scalar(q.volume),
        "turnover": _scalar(q.turnover),
        "high": _scalar(q.high),
        "low": _scalar(q.low),
        "prev_close": _scalar(q.prev_close),
    }


def pack_security_quote(q: SecurityQuote) -> Dict[str, SecurityQuote]:
    return {
        "symbol": _scalar(q.symbol),
        "last_done": _scalar(q.last_done),
        "prev_close": _scalar(q.prev_close),
        "open": _scalar(q.open),
        "high": _scalar(q.high),
        "low": _scalar(q.low),
        "timestamp": _scalar(q.timestamp),
        "volume": _scalar(q.volume),
        "turnover": _scalar(q.turnover),
        "trade_status": _scalar(q.trade_status),
        "pre_market_quote": pack_pre_post_quote(getattr(q, "pre_market_quote", None)),
        "post_market_quote": pack_pre_post_quote(getattr(q, "post_market_quote", None)),
        "overnight_quote": pack_pre_post_quote(getattr(q, "overnight_quote", None)),
    }


def pack_quotes(items: List[SecurityQuote]) -> List[Dict[str, SecurityQuote]]:
    return [pack_security_quote(x) for x in items]


def pack_candlestick(c: Candlestick) -> Dict[str, Candlestick]:
    return {
        "open": _scalar(c.open),
        "high": _scalar(c.high),
        "low": _scalar(c.low),
        "close": _scalar(c.close),
        "volume": _scalar(c.volume),
        "turnover": _scalar(c.turnover),
        "timestamp": _scalar(c.timestamp)
    }


def pack_candlesticks(symbol: str, rows: List[Candlestick]) -> Dict[str, List[Candlestick]]:
    return {
        "symbol": symbol,
        "candlesticks": [pack_candlestick(x) for x in rows],
    }