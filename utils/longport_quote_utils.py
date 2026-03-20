from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional

from longport.openapi import AdjustType, Period, TradeSessions


def serialize_longport_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {str(key): serialize_longport_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_longport_value(item) for item in value]

    for method_name in ("model_dump", "dict", "_asdict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return serialize_longport_value(method())
            except TypeError:
                continue

    public_attrs: Dict[str, Any] = {}
    for attr in dir(value):
        if attr.startswith("_"):
            continue
        try:
            attr_value = getattr(value, attr)
        except Exception:
            continue
        if callable(attr_value):
            continue
        public_attrs[attr] = serialize_longport_value(attr_value)

    if public_attrs:
        return public_attrs
    return str(value)


def parse_period(value: str) -> Period:
    mapping = {
        "day": Period.Day,
        "week": Period.Week,
        "month": Period.Month,
        "quarter": Period.Quarter,
        "year": Period.Year,
        "min_1": Period.Min_1,
        "min_2": Period.Min_2,
        "min_3": Period.Min_3,
        "min_5": Period.Min_5,
        "min_10": Period.Min_10,
        "min_15": Period.Min_15,
        "min_20": Period.Min_20,
        "min_30": Period.Min_30,
        "min_45": Period.Min_45,
        "min_60": Period.Min_60,
        "min_120": Period.Min_120,
        "min_180": Period.Min_180,
        "min_240": Period.Min_240,
    }
    normalized = str(value).strip().lower()
    if normalized not in mapping:
        raise ValueError("period 不合法，可选值如 Day、Week、Month、Min_1、Min_5、Min_15")
    return mapping[normalized]


def parse_adjust_type(value: str) -> AdjustType:
    mapping = {
        "noadjust": AdjustType.NoAdjust,
        "forwardadjust": AdjustType.ForwardAdjust,
    }
    normalized = str(value).strip().lower()
    if normalized not in mapping:
        raise ValueError("adjust_type 不合法，可选值为 NoAdjust、ForwardAdjust")
    return mapping[normalized]


def parse_trade_session(value: Optional[str]) -> Optional[TradeSessions]:
    if value is None or str(value).strip() == "":
        return None
    mapping = {
        "intraday": TradeSessions.Intraday,
        "all": TradeSessions.All,
    }
    normalized = str(value).strip().lower()
    if normalized not in mapping:
        raise ValueError("trade_session 不合法，可选值为 Intraday、All")
    return mapping[normalized]


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None or str(value).strip() == "":
        return None
    normalized = str(value).strip()
    formats = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d %H%M",
        "%Y%m%d %H%M%S",
        "%Y-%m-%d",
        "%Y%m%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError("时间格式不合法，支持 YYYY-MM-DD、YYYYMMDD、YYYY-MM-DD HH:MM")


def parse_date(value: Optional[str]) -> Optional[date]:
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def validate_symbol(symbol: Any) -> str:
    normalized = str(symbol).strip()
    if not normalized:
        raise ValueError("symbol 不能为空")
    return normalized


def validate_symbols(symbols: Any) -> list[str]:
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("symbols 必须是非空数组")
    normalized = [validate_symbol(symbol) for symbol in symbols]
    if len(normalized) > 500:
        raise ValueError("symbols 数量不能超过 500")
    return normalized


def validate_count(count: Any, *, min_value: int = 1, max_value: int = 1000) -> int:
    try:
        normalized = int(count)
    except (TypeError, ValueError):
        raise ValueError(f"count 必须是 {min_value} 到 {max_value} 之间的整数")
    if not min_value <= normalized <= max_value:
        raise ValueError(f"count 必须是 {min_value} 到 {max_value} 之间的整数")
    return normalized
