"""
LongPort 行情接口返回值 → 可 JSON 序列化的 dict / list。

按 SDK 公开字段显式拼装，避免通用反射序列化带来的环引用、类型异常等问题。
字段参考：longport openapi.pyi（SecurityStaticInfo、SecurityQuote、Candlestick 等）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


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


def _derivative_tags(items: Any) -> List[str]:
    if not items:
        return []
    out: List[str] = []
    for d in items:
        if isinstance(d, type):
            out.append(getattr(d, "__name__", str(d)))
        elif isinstance(d, Enum):
            out.append(d.name)
        else:
            out.append(str(d))
    return out


def pack_pre_post_quote(q: Any) -> Optional[Dict[str, Any]]:
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


def pack_security_quote(q: Any) -> Dict[str, Any]:
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


def pack_static_info_row(s: Any) -> Dict[str, Any]:
    board = getattr(s, "board", None)
    board_out = board.__name__ if isinstance(board, type) else _scalar(board)
    return {
        "symbol": _scalar(s.symbol),
        "name_cn": _scalar(s.name_cn),
        "name_en": _scalar(s.name_en),
        "name_hk": _scalar(s.name_hk),
        "exchange": _scalar(s.exchange),
        "currency": _scalar(s.currency),
        "lot_size": _scalar(s.lot_size),
        "total_shares": _scalar(s.total_shares),
        "circulating_shares": _scalar(s.circulating_shares),
        "hk_shares": _scalar(s.hk_shares),
        "eps": _scalar(s.eps),
        "eps_ttm": _scalar(s.eps_ttm),
        "bps": _scalar(s.bps),
        "dividend_yield": _scalar(s.dividend_yield),
        "stock_derivatives": _derivative_tags(getattr(s, "stock_derivatives", None)),
        "board": board_out,
        "listing_date": _scalar(getattr(s, "listing_date", None)),
    }


def pack_static_info(items: List[Any]) -> List[Dict[str, Any]]:
    return [pack_static_info_row(x) for x in items]


def pack_quotes(items: List[Any]) -> List[Dict[str, Any]]:
    return [pack_security_quote(x) for x in items]


def pack_intraday_line(line: Any) -> Dict[str, Any]:
    return {
        "price": _scalar(line.price),
        "timestamp": _scalar(line.timestamp),
        "volume": _scalar(line.volume),
        "turnover": _scalar(line.turnover),
        "avg_price": _scalar(line.avg_price),
    }


def pack_intraday(symbol: str, lines: List[Any]) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "lines": [pack_intraday_line(x) for x in lines],
    }


def pack_candlestick(c: Any) -> Dict[str, Any]:
    return {
        "open": _scalar(c.open),
        "high": _scalar(c.high),
        "low": _scalar(c.low),
        "close": _scalar(c.close),
        "volume": _scalar(c.volume),
        "turnover": _scalar(c.turnover),
        "timestamp": _scalar(c.timestamp),
        "trade_session": _scalar(getattr(c, "trade_session", None)),
    }


def pack_candlesticks(symbol: str, rows: List[Any]) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "candlesticks": [pack_candlestick(x) for x in rows],
    }


def pack_watchlist_security(s: Any) -> Dict[str, Any]:
    return {
        "symbol": _scalar(s.symbol),
        "market": _scalar(s.market),
        "name": _scalar(s.name),
        "watched_price": _scalar(getattr(s, "watched_price", None)),
        "watched_at": _scalar(s.watched_at),
    }


def pack_watchlist_group(g: Any) -> Dict[str, Any]:
    secs = getattr(g, "securities", None) or []
    return {
        "id": _scalar(g.id),
        "name": _scalar(g.name),
        "securities": [pack_watchlist_security(x) for x in secs],
    }


def pack_watchlist(groups: List[Any]) -> List[Dict[str, Any]]:
    return [pack_watchlist_group(x) for x in groups]
