from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

from longport.openapi import (
    Market,
    Order,
    OrderChargeDetail,
    OrderChargeFee,
    OrderChargeItem,
    OrderDetail,
    OrderHistoryDetail,
    OrderSide,
    OrderStatus,
    OrderType,
    OutsideRTH,
    TimeInForceType,
)

from .longport_quote_utils import parse_datetime, validate_symbol

if TYPE_CHECKING:
    # 以下类型仅在 openapi.pyi 中声明，运行时扩展模块不导出，供 Pyright/mypy 使用
    from longport.openapi import (
        AccountBalance,
        StockPosition,
        StockPositionChannel,
        StockPositionsResponse,
    )

# 订单列表项：列表接口返回 Order；详情为 OrderDetail，字段兼容 pack_order
OrderLike = Union[Order, OrderDetail]


def _enum_suffix(name: str) -> str:
    s = str(name)
    return s.split(".")[-1] if "." in s else s


def scalar_to_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [scalar_to_json(x) for x in value]
    if isinstance(value, dict):
        return {k: scalar_to_json(v) for k, v in value.items()}
    # Rust / SDK 枚举等
    return _enum_suffix(value)


def parse_order_type(value: Any) -> Any:
    raw = str(value).strip()
    if not raw:
        raise ValueError("order_type 不能为空")
    key = raw.upper().replace("-", "_")
    mapping = {
        "LO": OrderType.LO,
        "MO": OrderType.MO,
        "ELO": OrderType.ELO,
        "AO": OrderType.AO,
        "ALO": OrderType.ALO,
        "ODD": OrderType.ODD,
        "LIT": OrderType.LIT,
        "MIT": OrderType.MIT,
        "SLO": OrderType.SLO,
        "TSLPAMT": OrderType.TSLPAMT,
        "TSLPPCT": OrderType.TSLPPCT,
        "TSMAMT": OrderType.TSMAMT,
        "TSMPCT": OrderType.TSMPCT,
    }
    if key not in mapping:
        raise ValueError(
            "order_type 不合法，示例：LO、MO、LIT、MIT、ELO、TSLPPCT（见 LongPort 订单类型文档）"
        )
    return mapping[key]


def parse_order_side(value: Any) -> Any:
    raw = str(value).strip().upper()
    if raw == "BUY":
        return OrderSide.Buy
    if raw == "SELL":
        return OrderSide.Sell
    raise ValueError("side 不合法，可选：Buy、Sell")


def parse_market(value: Any) -> Optional[Any]:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip().upper()
    mapping = {
        "US": Market.US,
        "HK": Market.HK,
        "CN": Market.CN,
        "SG": Market.SG,
    }
    if raw not in mapping:
        raise ValueError("market 不合法，可选：US、HK、CN、SG")
    return mapping[raw]


def parse_order_status(value: Any) -> Any:
    raw = str(value).strip()
    if not raw:
        raise ValueError("订单状态不能为空")
    n = raw.replace("_", "")
    if n.lower().endswith("status"):
        n = n[: -len("status")]
    target = n.lower()
    for attr in dir(OrderStatus):
        if attr.startswith("_") or not attr[0].isupper():
            continue
        member = getattr(OrderStatus, attr)
        short = _enum_suffix(member).lower()
        if short == target:
            return member
    raise ValueError(f"不支持的订单状态: {raw}")


def parse_order_status_list(value: Any) -> Optional[List[Any]]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return [parse_order_status(p) for p in parts] if parts else None
    if isinstance(value, list):
        if not value:
            return None
        return [parse_order_status(x) for x in value]
    raise ValueError("status 应为字符串数组，或逗号分隔的状态列表")


def parse_time_in_force(value: Any) -> Any:
    raw = str(value).strip().upper().replace("-", "_")
    mapping = {
        "DAY": TimeInForceType.Day,
        "GTC": TimeInForceType.GoodTilCanceled,
        "GOOD_TIL_CANCELED": TimeInForceType.GoodTilCanceled,
        "GTD": TimeInForceType.GoodTilDate,
        "GOOD_TIL_DATE": TimeInForceType.GoodTilDate,
    }
    if raw not in mapping:
        raise ValueError("time_in_force 不合法，可选：Day、GTC、GTD")
    return mapping[raw]


def parse_outside_rth(value: Any) -> Optional[Any]:
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip().upper().replace("-", "_")
    mapping = {
        "RTH_ONLY": OutsideRTH.RTHOnly,
        "ANY_TIME": OutsideRTH.AnyTime,
        "OVERNIGHT": OutsideRTH.Overnight,
    }
    if raw not in mapping:
        raise ValueError("outside_rth 不合法，可选：RTH_ONLY、ANY_TIME、OVERNIGHT")
    return mapping[raw]


def parse_optional_symbol(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    return validate_symbol(value)


def parse_optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("数值格式不合法") from exc


def parse_required_decimal(value: Any, *, name: str = "quantity") -> Decimal:
    d = parse_optional_decimal(value)
    if d is None:
        raise ValueError(f"{name} 不能为空")
    return d


def parse_optional_date(value: Any) -> Optional[date]:
    if value is None or str(value).strip() == "":
        return None
    dt = parse_datetime(str(value).strip())
    return dt.date() if dt else None


def parse_optional_datetime(value: Any) -> Optional[datetime]:
    if value is None or str(value).strip() == "":
        return None
    return parse_datetime(str(value).strip())


def validate_order_id(value: Any) -> str:
    s = str(value).strip()
    if not s:
        raise ValueError("order_id 不能为空")
    return s


def validate_symbols_optional(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        return [validate_symbol(x) for x in value]
    raise ValueError("symbols 应为字符串数组")


def pack_order(o: OrderLike) -> dict[str, Any]:
    return {
        "order_id": o.order_id,
        "status": scalar_to_json(o.status),
        "stock_name": o.stock_name,
        "quantity": scalar_to_json(o.quantity),
        "executed_quantity": scalar_to_json(o.executed_quantity),
        "price": scalar_to_json(o.price),
        "executed_price": scalar_to_json(o.executed_price),
        "submitted_at": scalar_to_json(o.submitted_at),
        "side": scalar_to_json(o.side),
        "symbol": o.symbol,
        "order_type": scalar_to_json(o.order_type),
        "last_done": scalar_to_json(o.last_done),
        "trigger_price": scalar_to_json(o.trigger_price),
        "msg": o.msg,
        "tag": scalar_to_json(o.tag),
        "time_in_force": scalar_to_json(o.time_in_force),
        "expire_date": scalar_to_json(o.expire_date),
        "updated_at": scalar_to_json(o.updated_at),
        "trigger_at": scalar_to_json(o.trigger_at),
        "trailing_amount": scalar_to_json(o.trailing_amount),
        "trailing_percent": scalar_to_json(o.trailing_percent),
        "limit_offset": scalar_to_json(o.limit_offset),
        "trigger_status": scalar_to_json(o.trigger_status),
        "currency": o.currency,
        "outside_rth": scalar_to_json(o.outside_rth),
        "remark": o.remark,
    }


def pack_order_history_item(h: OrderHistoryDetail) -> dict[str, Any]:
    return {
        "price": scalar_to_json(h.price),
        "quantity": scalar_to_json(h.quantity),
        "status": scalar_to_json(h.status),
        "msg": h.msg,
        "time": scalar_to_json(h.time),
    }


def pack_charge_fee(f: OrderChargeFee) -> dict[str, Any]:
    return {
        "code": f.code,
        "name": f.name,
        "amount": scalar_to_json(f.amount),
        "currency": f.currency,
    }


def pack_charge_item(item: OrderChargeItem) -> dict[str, Any]:
    return {
        "code": scalar_to_json(item.code),
        "name": item.name,
        "fees": [pack_charge_fee(x) for x in item.fees],
    }


def pack_charge_detail(d: OrderChargeDetail) -> dict[str, Any]:
    return {
        "total_amount": scalar_to_json(d.total_amount),
        "currency": d.currency,
        "items": [pack_charge_item(x) for x in d.items],
    }


def pack_order_detail(d: OrderDetail) -> dict[str, Any]:
    base = pack_order(d)
    base.update(
        {
            "free_status": scalar_to_json(d.free_status),
            "free_amount": scalar_to_json(d.free_amount),
            "free_currency": d.free_currency,
            "deductions_status": scalar_to_json(d.deductions_status),
            "deductions_amount": scalar_to_json(d.deductions_amount),
            "deductions_currency": d.deductions_currency,
            "platform_deducted_status": scalar_to_json(d.platform_deducted_status),
            "platform_deducted_amount": scalar_to_json(d.platform_deducted_amount),
            "platform_deducted_currency": d.platform_deducted_currency,
            "history": [pack_order_history_item(x) for x in d.history],
            "charge_detail": pack_charge_detail(d.charge_detail),
        }
    )
    return base


def _norm_currency_code(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _available_cash_for_currency(b: AccountBalance, currency: str) -> Any:
    """
    Pick available_cash from cash_infos for the requested currency (case-insensitive).
    If no row matches, prefer the row for the account primary currency (b.currency),
    then the first row — so we do not pick a wrong currency when order differs from API.
    """
    want = _norm_currency_code(currency)
    primary = _norm_currency_code(b.currency)
    rows = b.cash_infos or []
    if not rows:
        return None
    for c in rows:
        if _norm_currency_code(c.currency) == want:
            return scalar_to_json(c.available_cash)
    for c in rows:
        if _norm_currency_code(c.currency) == primary:
            return scalar_to_json(c.available_cash)
    return scalar_to_json(rows[0].available_cash)


def pack_account_balance(
    b: AccountBalance,
    *,
    available_currency: Optional[str] = None,
) -> dict[str, Any]:
    """
    Three fields: net_assets, available cash (by currency), buy_power.
    If available_currency matches the tool request, use it for available; else b.currency.
    """
    ccy = _norm_currency_code(available_currency) or b.currency
    return {
        "net_assets": scalar_to_json(b.net_assets),
        "available": _available_cash_for_currency(b, ccy),
        "buy_power": scalar_to_json(b.buy_power),
    }


def pack_stock_position(p: StockPosition) -> dict[str, Any]:
    return {
        "symbol": p.symbol,
        "symbol_name": p.symbol_name,
        "quantity": scalar_to_json(p.quantity),
        "available_quantity": scalar_to_json(p.available_quantity),
        "currency": p.currency,
        "cost_price": scalar_to_json(p.cost_price),
        "market": scalar_to_json(p.market),
        "init_quantity": scalar_to_json(p.init_quantity),
    }


def pack_stock_channel(ch: StockPositionChannel) -> dict[str, Any]:
    return {
        "account_channel": ch.account_channel,
        "positions": [pack_stock_position(x) for x in ch.positions],
    }


def pack_stock_positions_response(resp: StockPositionsResponse) -> dict[str, Any]:
    return {
        "channels": [pack_stock_channel(x) for x in resp.channels],
    }


def pack_orders(orders: Sequence[Order]) -> List[dict[str, Any]]:
    return [pack_order(o) for o in orders]
