from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import (
    pack_candlesticks,
    parse_adjust_type,
    parse_period,
    parse_trade_session,
    validate_count,
    validate_symbol,
)


class QuoteCandlesticksTool(LongPortQuoteTool):
    name = "quote_candlesticks"
    description = "获取标的 K 线"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "标的代码，例如 TSLA.US"},
            "period": {
                "type": "string",
                "description": "K 线周期，例如 Day、Week、Month、Min_1、Min_5、Min_15",
            },
            "count": {
                "type": "integer",
                "description": "返回数量，范围 1-1000",
            }
        },
        "required": ["symbol", "period", "count"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            period = parse_period(parameters.get("period"))
            count = validate_count(parameters.get("count"))
            adjust_type = parse_adjust_type(parameters.get("adjust_type", "NoAdjust"))
            ctx = self.get_quote_context()
            rows = ctx.candlesticks(symbol, period, count, adjust_type)
            return self.success(pack_candlesticks(symbol, rows))
        except Exception as exc:
            return self.fail(str(exc))