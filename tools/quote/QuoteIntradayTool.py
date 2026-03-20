from typing import Any, Dict

from .LongPortQuoteTool import LongPortQuoteTool
from utils import parse_trade_session, validate_symbol


class QuoteIntradayTool(LongPortQuoteTool):
    name = "quote_intraday"
    description = "获取标的当日分时"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "标的代码，例如 700.HK",
            },
            "trade_session": {
                "type": "string",
                "description": "可选值：Intraday、All",
            },
        },
        "required": ["symbol"],
    }

    def run(self, parameters: Dict[str, Any]) -> str:
        try:
            symbol = validate_symbol(parameters.get("symbol"))
            trade_session = parse_trade_session(parameters.get("trade_session"))
            ctx = self.get_quote_context()
            if trade_session is None:
                result = ctx.intraday(symbol)
            else:
                result = ctx.intraday(symbol, trade_session)
            return self.success(self.serialize(result))
        except Exception as exc:
            return self.fail(str(exc))
