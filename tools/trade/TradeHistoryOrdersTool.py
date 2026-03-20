from typing import Any, Dict

from utils.longport_trade_utils import (
    pack_orders,
    parse_market,
    parse_optional_datetime,
    parse_optional_symbol,
    parse_order_side,
    parse_order_status_list,
)

from .LongPortTradeTool import LongPortTradeTool


class TradeHistoryOrdersTool(LongPortTradeTool):
    name = "trade_history_orders"
    description = "获取历史订单，对应 LongPort /v1/trade/order/history"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "筛选标的，可选"},
            "status": {
                "type": "array",
                "items": {"type": "string"},
                "description": "订单状态列表，可选，如 Filled、New；也可传逗号分隔字符串",
            },
            "side": {"type": "string", "description": "Buy 或 Sell，可选"},
            "market": {"type": "string", "description": "US、HK 等，可选"},
            "start_at": {
                "type": "string",
                "description": "开始时间，可选，格式同 quote 工具（如 YYYY-MM-DD）",
            },
            "end_at": {
                "type": "string",
                "description": "结束时间，可选",
            },
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
            start_at = parse_optional_datetime(parameters.get("start_at"))
            end_at = parse_optional_datetime(parameters.get("end_at"))
            rows = self.get_trade_context().history_orders(
                symbol=symbol,
                status=status,
                side=side,
                market=market,
                start_at=start_at,
                end_at=end_at,
            )
            return self.success({"orders": pack_orders(rows)})
        except Exception as exc:
            return self.fail(str(exc))
