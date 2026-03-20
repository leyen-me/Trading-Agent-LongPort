from typing import Any, Dict

from utils.longport_trade_utils import (
    pack_orders,
    parse_market,
    parse_optional_symbol,
    parse_order_side,
    parse_order_status_list,
    validate_order_id,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeTodayOrdersTool(LongPortTradeTool):
    name = "trade_today_orders"
    description = "获取当日订单，对应 LongPort /v1/trade/order/today"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "筛选标的，可选"},
            "status": {
                "type": "array",
                "items": {"type": "string"},
                "description": "订单状态列表，可选",
            },
            "side": {"type": "string", "description": "Buy 或 Sell，可选"},
            "market": {"type": "string", "description": "US、HK 等，可选"},
            "order_id": {"type": "string", "description": "指定订单 ID，可选"},
        },
        "required": [],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = parse_optional_symbol(parameters.get("symbol"))
            status = parse_order_status_list(parameters.get("status"))
            side_raw = parameters.get("side")
            side = parse_order_side(side_raw) if side_raw not in (None, "") else None
            market = parse_market(parameters.get("market"))
            oid = parameters.get("order_id")
            order_id = validate_order_id(oid) if oid not in (None, "") else None
            rows = self.get_trade_context().today_orders(
                symbol=symbol,
                status=status,
                side=side,
                market=market,
                order_id=order_id,
            )
            return self.success({"orders": pack_orders(rows)})
        except Exception as exc:
            return self.fail(str(exc))
