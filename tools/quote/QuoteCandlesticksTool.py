from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import (
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
            "symbol": {"type": "string", "description": "标的代码，例如 700.HK"},
            "period": {
                "type": "string",
                "description": "K 线周期，例如 Day、Week、Month、Min_1、Min_5、Min_15",
            },
            "count": {
                "type": "integer",
                "description": "返回数量，范围 1-1000",
            },
            "adjust_type": {
                "type": "string",
                "description": "复权类型，可选 NoAdjust、ForwardAdjust，默认 NoAdjust",
            },
            "trade_session": {
                "type": "string",
                "description": "可选值：Intraday、All",
            },
        },
        "required": ["symbol", "period", "count"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            period = parse_period(parameters.get("period"))
            count = validate_count(parameters.get("count"))
            adjust_type = parse_adjust_type(parameters.get("adjust_type", "NoAdjust"))
            trade_session = parse_trade_session(parameters.get("trade_session"))
            ctx = self.get_quote_context()
            if trade_session is None:
                result = ctx.candlesticks(symbol, period, count, adjust_type)
            else:
                result = ctx.candlesticks(
                    symbol,
                    period,
                    count,
                    adjust_type,
                    trade_session,
                )
            return self.success(self.serialize(result))
        except Exception as exc:
            return self.fail(str(exc))


if __name__ == "__main__":
    tool = QuoteCandlesticksTool()
    print(tool.run({"symbol": "700.HK", "period": "Day", "count": 10}))